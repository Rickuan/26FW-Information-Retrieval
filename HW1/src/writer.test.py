"""writer.test.py — M4 IndexWriter & Reader 測試

分兩段：
  Part 1：單元測試 — VByte、postings block、作業格式、單次走訪 write_all、IndexReader
  Part 2：整合測試 — 真實 Indexer（全記憶體模式 vs SPIMI 模式），逐 byte 一致性驗證

執行：
  uv run python writer.test.py
  uv run python writer.test.py ../dataset/04.warc 100
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from array import array
from pathlib import Path

# 確保可以 import 模組
sys.path.insert(0, str(Path(__file__).parent))

from indexer import DocEntry, Indexer, Posting
from tokenizer import Preprocessor
from writer import (
    IndexReader,
    IndexWriter,
    decode_postings_block,
    decode_vbyte,
    encode_postings_block,
    encode_vbyte,
    format_line,
    parse_postings_line,
    write_binary_format,
    write_dictionary,
    write_postings_text,
)

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


def check(name: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))
    return condition


def file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class MockIndexer:
    """最小 Indexer stub，用於 Part 1 獨立單元測試。"""

    def __init__(self, index: dict[str, list[Posting]], doc_map: dict[int, DocEntry], spimi: bool = False) -> None:
        self.index = index
        self.doc_map = doc_map
        self.spimi = spimi

    def iter_postings(self):
        for term in sorted(self.index):
            yield term, self.index[term]

    def get_stats(self) -> dict:
        N = len(self.doc_map)
        vocab_size = len(self.index)
        total_tokens = sum(e.doc_len for e in self.doc_map.values())
        avg_doc_len = total_tokens / N if N else 0.0
        return {
            "N": N,
            "vocab_size": vocab_size,
            "total_tokens": total_tokens,
            "avg_doc_len": avg_doc_len,
        }


all_passed = True


def section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ===========================================================================
# Part 1: Unit Tests
# ===========================================================================

# ---------------------------------------------------------------------------
# 4-C：VByte AC
# ---------------------------------------------------------------------------
section("Part 1: Step 4-C — VByte encode / decode")

cases_vbyte = [
    (0,     b"\x00"),
    (1,     b"\x01"),
    (127,   b"\x7f"),
    (128,   b"\x80\x01"),
    (300,   b"\xac\x02"),
    (16383, b"\xff\x7f"),
    (16384, b"\x80\x80\x01"),
]

for n, expected in cases_vbyte:
    encoded = encode_vbyte(n)
    ok = check(f"encode_vbyte({n}) == {expected!r}", encoded == expected, repr(encoded))
    all_passed = all_passed and ok

# decode round-trip
for n, _ in cases_vbyte:
    decoded, new_offset = decode_vbyte(encode_vbyte(n), 0)
    ok = check(f"decode(encode({n})) == {n}", decoded == n, f"got {decoded}")
    all_passed = all_passed and ok

# ---------------------------------------------------------------------------
# 4-D：encode_postings_block / decode_postings_block round-trip
# ---------------------------------------------------------------------------
section("Part 1: Step 4-D — postings block encode / decode round-trip")

sample_postings = [
    Posting(doc_num=1,   tf=3, positions=array("I", [2, 5, 10])),
    Posting(doc_num=5,   tf=1, positions=array("I", [1])),
    Posting(doc_num=128, tf=2, positions=array("I", [3, 7])),
    Posting(doc_num=300, tf=5, positions=array("I", [1, 2, 3, 4, 5])),
]

encoded_block = encode_postings_block(sample_postings)
decoded = decode_postings_block(encoded_block)

ok = check("decoded length == original", len(decoded) == len(sample_postings))
all_passed = all_passed and ok

for orig, dec in zip(sample_postings, decoded):
    ok1 = check(f"  doc_num {orig.doc_num} matches", dec.doc_num == orig.doc_num)
    ok2 = check(f"  tf      {orig.doc_num} matches", dec.tf == orig.tf)
    ok3 = check(f"  pos     {orig.doc_num} matches", dec.positions == orig.positions)
    ok4 = check(f"  pos type is array('I')", isinstance(dec.positions, array) and dec.positions.typecode == "I")
    all_passed = all_passed and ok1 and ok2 and ok3 and ok4

# ---------------------------------------------------------------------------
# 4-A：format_line 與 parse_postings_line
# ---------------------------------------------------------------------------
section("Part 1: Step 4-A — 作業規定格式 (format_line & parse_postings_line)")

fmt_line = format_line("computer", [
    Posting(12, 2, array("I", [5, 40])),
    Posting(87, 1, array("I", [3])),
    Posting(301, 4, array("I", [1, 9, 22, 30])),
])
expected_line = "computer, 3: <12, 2: <5, 40>; 87, 1: <3>; 301, 4: <1, 9, 22, 30>>\n"
ok = check("format_line 產生符合 Fig. 2.11 格式", fmt_line == expected_line, fmt_line.strip())
all_passed = all_passed and ok

parsed_term, parsed_df, parsed_plist = parse_postings_line(fmt_line)
ok = check("parse_postings_line term == 'computer'", parsed_term == "computer")
ok = check("parse_postings_line df == 3", parsed_df == 3) and ok
ok = check(
    "parse_postings_line plist match",
    parsed_plist == [(12, 2, [5, 40]), (87, 1, [3]), (301, 4, [1, 9, 22, 30])],
) and ok
all_passed = all_passed and ok

# 測試帶有逗號的特殊 term（例如 "10,000"）
special_line = format_line("10,000", [Posting(1, 1, array("I", [4]))])
s_term, s_df, s_plist = parse_postings_line(special_line)
ok = check("parse_postings_line 支援含逗號 term ('10,000')", s_term == "10,000" and s_df == 1)
all_passed = all_passed and ok

# ---------------------------------------------------------------------------
# 4-A/B/D/E/F：IndexWriter & IndexReader with MockIndexer
# ---------------------------------------------------------------------------
section("Part 1: Step 4-A ~ 4-F — IndexWriter & IndexReader (Mock)")

mock_index = {
    "information": [
        Posting(1, 3, array("I", [1, 4, 9])),
        Posting(5, 2, array("I", [2, 8])),
    ],
    "retrieval": [
        Posting(2, 1, array("I", [3])),
        Posting(5, 4, array("I", [1, 2, 5, 7])),
    ],
    "system": [
        Posting(1, 2, array("I", [5, 6])),
    ],
}
mock_doc_map = {
    1: DocEntry("clueweb-1", 20, "http://example.com/1"),
    2: DocEntry("clueweb-2", 15, "http://example.com/2"),
    5: DocEntry("clueweb-5", 30, "http://example.com/5"),
}
mock_indexer = MockIndexer(mock_index, mock_doc_map)

with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    writer = IndexWriter(tmp_path)

    # 4-A：dictionary.txt & postings.txt
    writer.write_dictionary(mock_indexer)
    writer.write_postings_text(mock_indexer)

    dict_path = tmp_path / "dictionary.txt"
    post_path = tmp_path / "postings.txt"

    ok = check("dictionary.txt 存在", dict_path.exists())
    all_passed = all_passed and ok
    ok = check("postings.txt 存在", post_path.exists())
    all_passed = all_passed and ok

    dict_lines = dict_path.read_text(encoding="utf-8").splitlines()
    post_lines = post_path.read_text(encoding="utf-8").splitlines()

    ok = check("dictionary 行數 == vocab_size (3)", len(dict_lines) == len(mock_index))
    ok = check("postings 行數 == vocab_size (3)", len(post_lines) == len(mock_index)) and ok
    ok = check("dictionary 已依字典序排列", dict_lines == sorted(mock_index.keys())) and ok
    all_passed = all_passed and ok

    # 驗證 postings.txt 第 i 行的 term == dictionary.txt 第 i 行
    lines_match = all(p.split(", ", 1)[0] == d for d, p in zip(dict_lines, post_lines))
    ok = check("postings.txt 第 i 行 term == dictionary.txt 第 i 行", lines_match)
    all_passed = all_passed and ok

    # 4-B：metadata + doc_map
    preprocessor_cfg = {"casefold": True, "stopword": False, "stem": False}
    writer.write_metadata(mock_indexer, preprocessor_cfg)
    writer.write_doc_map(mock_indexer)

    meta_path = tmp_path / "metadata.json"
    doc_map_path = tmp_path / "doc_map.json"

    with meta_path.open() as f:
        meta = json.load(f)
    with doc_map_path.open() as f:
        doc_map_json = json.load(f)

    required_keys = {"N", "vocab_size", "total_tokens", "avg_doc_len", "created_at", "preprocessor", "spimi"}
    ok = check("metadata.json schema 完整（含 spimi）", required_keys.issubset(meta.keys()))
    ok = check("metadata N == 3", meta["N"] == 3) and ok
    ok = check("metadata spimi == False", meta["spimi"] is False) and ok
    ok = check("doc_map_json len == N", len(doc_map_json) == meta["N"]) and ok
    ok = check("doc_map key 為字串", all(isinstance(k, str) for k in doc_map_json)) and ok
    all_passed = all_passed and ok

    # 4-D：Binary format (postings.bin + lexicon.tsv)
    writer.write_binary_format(mock_indexer)

    bin_path = tmp_path / "postings.bin"
    lex_path = tmp_path / "lexicon.tsv"
    ok = check("postings.bin 存在", bin_path.exists())
    ok = check("lexicon.tsv 存在", lex_path.exists()) and ok
    all_passed = all_passed and ok

    lex_lines = lex_path.read_text(encoding="utf-8").splitlines()
    ok = check("lexicon.tsv 行數 == vocab_size", len(lex_lines) == len(mock_index))
    all_passed = all_passed and ok

    # 4-E：IndexReader 讀取測試
    reader = IndexReader(tmp_path)
    for term, orig_postings in mock_index.items():
        read_back = reader.get_postings(term)
        ok1 = check(f"  reader.get_postings('{term}') df 一致", len(read_back) == len(orig_postings))
        all_passed = all_passed and ok1
        for orig, dec in zip(orig_postings, read_back):
            ok2 = check(f"    doc_num {orig.doc_num}", dec.doc_num == orig.doc_num)
            ok3 = check(f"    tf      {orig.doc_num}", dec.tf == orig.tf)
            ok4 = check(f"    pos     {orig.doc_num}", dec.positions == orig.positions)
            ok5 = check(f"    pos is array('I')", isinstance(dec.positions, array) and dec.positions.typecode == "I")
            all_passed = all_passed and ok2 and ok3 and ok4 and ok5

    # get_doc 需回傳 DocEntry 物件
    doc = reader.get_doc(1)
    ok = check(
        "reader.get_doc(1) 回傳 DocEntry 且 trec_id == 'clueweb-1'",
        isinstance(doc, DocEntry) and doc.trec_id == "clueweb-1" and doc.doc_len == 20,
    )
    all_passed = all_passed and ok

    ok = check("reader.get_doc(999) is None", reader.get_doc(999) is None)
    all_passed = all_passed and ok

    # term in reader & vocab_size
    ok = check("'information' in reader", "information" in reader)
    ok = check("'nonexistent' not in reader", "nonexistent" not in reader) and ok
    ok = check(f"reader.vocab_size() == {len(mock_index)}", reader.vocab_size() == len(mock_index)) and ok
    all_passed = all_passed and ok

    # 4-F：Step 4-F write_all 單次走訪產出與獨立輸出逐 byte 相同
    with tempfile.TemporaryDirectory() as write_all_tmpdir:
        writer_all = IndexWriter(write_all_tmpdir)
        writer_all.write_all(mock_indexer, preprocessor_cfg)

        target_files = ["dictionary.txt", "postings.txt", "postings.bin", "lexicon.tsv", "doc_map.json"]
        for fname in target_files:
            h1 = file_sha1(tmp_path / fname)
            h2 = file_sha1(Path(write_all_tmpdir) / fname)
            ok = check(f"write_all 輸出 {fname} 與獨立輸出逐 byte 相同", h1 == h2)
            all_passed = all_passed and ok


# ===========================================================================
# Part 2: Real Indexer Integration Tests
# ===========================================================================
section("Part 2: Real Indexer Integration Tests (Memory vs SPIMI)")


class DummyDoc:
    def __init__(self, doc_num: int, trec_id: str, url: str, text: str):
        self.doc_num = doc_num
        self.trec_id = trec_id
        self.url = url
        self.text = text


sample_corpus = [
    DummyDoc(1, "clueweb12-0000tw-00-00001", "https://example.com/1",
             "Information retrieval and web search engines are essential tools."),
    DummyDoc(2, "clueweb12-0000tw-00-00002", "https://example.com/2",
             "Search engines index web pages to provide relevant search results."),
    DummyDoc(3, "clueweb12-0000tw-00-00003", "https://example.com/3",
             "Natural language processing and information extraction improve search."),
    DummyDoc(4, "clueweb12-0000tw-00-00004", "https://example.com/4",
             "Inverted index compression uses variable byte encoding and delta gap."),
    DummyDoc(5, "clueweb12-0000tw-00-00005", "https://example.com/5",
             "Information retrieval systems evaluate precision and recall metrics."),
]

pre = Preprocessor(casefold=True, stopword=False, stem=False)
cfg = {"casefold": True, "stopword": False, "stem": False}

# 1. 建置全記憶體模式 Indexer
idx_mem = Indexer(spimi=False)
for d in sample_corpus:
    idx_mem.add_document(d, pre.process(d.text))
idx_mem.get_stats()

# 2. 建置 SPIMI 模式 Indexer（設定極小 flush_every=10 強制觸發多次 partial flush & merge）
with tempfile.TemporaryDirectory() as spimi_tmp:
    idx_spimi = Indexer(spimi=True, flush_every=10, tmp_dir=spimi_tmp)
    for d in sample_corpus:
        idx_spimi.add_document(d, pre.process(d.text))
    idx_spimi._flush_partial()
    idx_spimi._merge_partials()
    idx_spimi.get_stats()

    # 驗證兩者 stats
    ok = check("SPIMI stats['vocab_size'] == Memory stats['vocab_size']",
               idx_spimi.stats["vocab_size"] == idx_mem.stats["vocab_size"])
    all_passed = all_passed and ok

    with tempfile.TemporaryDirectory() as out_mem_dir, tempfile.TemporaryDirectory() as out_spimi_dir:
        writer_mem = IndexWriter(out_mem_dir)
        writer_mem.write_all(idx_mem, cfg)

        writer_spimi = IndexWriter(out_spimi_dir)
        writer_spimi.write_all(idx_spimi, cfg)

        # 驗證 5 個產物檔案在全記憶體與 SPIMI 輸出下逐 byte 完全一致！
        for fname in ["dictionary.txt", "postings.txt", "postings.bin", "lexicon.tsv", "doc_map.json"]:
            h_mem = file_sha1(Path(out_mem_dir) / fname)
            h_spimi = file_sha1(Path(out_spimi_dir) / fname)
            ok = check(f"SPIMI vs Memory 模式下 {fname} 逐 byte 相同", h_mem == h_spimi)
            all_passed = all_passed and ok

        # 驗證 postings.txt 格式與內容
        post_path = Path(out_mem_dir) / "postings.txt"
        post_lines = post_path.read_text(encoding="utf-8").splitlines()

        # 抽查 5 個 term
        check_terms = ["information", "search", "engines", "retrieval", "web"]
        for t in check_terms:
            t_lines = [l for l in post_lines if l.startswith(f"{t}, ")]
            ok1 = check(f"postings.txt 可找到 term '{t}'", len(t_lines) == 1)
            all_passed = all_passed and ok1
            if t_lines:
                pt, df, plist = parse_postings_line(t_lines[0])
                orig_p = idx_mem.get_postings(t)
                ok2 = check(f"  term '{t}' df == {len(orig_p)}", df == len(orig_p))
                matched = [(p.doc_num, p.tf, list(p.positions)) for p in orig_p] == plist
                ok3 = check(f"  term '{t}' postings 完全一致", matched)
                all_passed = all_passed and ok2 and ok3

        # 驗證 IndexReader
        reader = IndexReader(out_mem_dir)
        reader_ok = True
        for term, orig_postings in idx_mem.iter_postings():
            read_p = reader.get_postings(term)
            if len(read_p) != len(orig_postings):
                reader_ok = False
                break
            for p1, p2 in zip(orig_postings, read_p):
                if (p1.doc_num, p1.tf, list(p1.positions)) != (p2.doc_num, p2.tf, list(p2.positions)):
                    reader_ok = False
                    break
        ok = check("IndexReader.get_postings 全部詞與 Indexer 一致", reader_ok)
        all_passed = all_passed and ok

        # 驗證 postings.bin 大小 < 未壓縮（每整數 4 bytes）的 60%
        # 未壓縮大小：每个 posting 有 doc_num, tf, n_pos，以及每个 pos 都是 4 bytes
        bin_size = (Path(out_mem_dir) / "postings.bin").stat().st_size
        total_integers = 0
        for _, plist in idx_mem.iter_postings():
            for p in plist:
                total_integers += 3 + len(p.positions)  # doc, tf, n_pos, positions
        raw_size = total_integers * 4
        compression_ratio = bin_size / raw_size if raw_size else 1.0
        ok = check(
            f"postings.bin 壓縮率 ({compression_ratio:.1%}) < 60%",
            compression_ratio < 0.6,
            f"bin: {bin_size}B vs raw: {raw_size}B",
        )
        all_passed = all_passed and ok

    idx_spimi.cleanup()


# ===========================================================================
# Optional: WARC Integration Test if dataset provided
# ===========================================================================
warc_arg = sys.argv[1] if len(sys.argv) > 1 else None
if warc_arg and Path(warc_arg).exists():
    import time
    n_docs = int(sys.argv[2]) if len(sys.argv) > 2 else 500
    section(f"Part 3: Real WARC Integration & AC Verification ({warc_arg}, limit={n_docs})")

    t_b0 = time.time()
    idx_warc = Indexer().build(warc_arg, Preprocessor(), limit=n_docs, progress=500 if n_docs >= 1000 else 0)
    build_time = time.time() - t_b0
    stats = idx_warc.stats
    print(f"  Indexed {stats['N']} docs in {build_time:.2f}s | vocab: {stats['vocab_size']}, tokens: {stats['total_tokens']}")

    with tempfile.TemporaryDirectory() as warc_out:
        warc_out_path = Path(warc_out)
        writer_warc = IndexWriter(warc_out_path)

        t_w0 = time.time()
        writer_warc.write_all(idx_warc, {"casefold": True, "stopword": False, "stem": False})
        write_time = time.time() - t_w0
        print(f"  write_all() completed in {write_time:.2f}s")

        # 1. dictionary.txt 驗證
        dict_path = warc_out_path / "dictionary.txt"
        dict_lines = dict_path.read_text(encoding="utf-8").splitlines()
        ok1 = check("dictionary.txt 行數 == vocab_size", len(dict_lines) == stats["vocab_size"])
        ok2 = check("dictionary.txt 嚴格字典序排列", dict_lines == sorted(dict_lines))
        all_passed = all_passed and ok1 and ok2

        # 2. postings.txt 驗證
        post_path = warc_out_path / "postings.txt"
        post_lines = post_path.read_text(encoding="utf-8").splitlines()
        ok3 = check("postings.txt 行數 == dictionary.txt 行數", len(post_lines) == len(dict_lines))
        lines_match = all(p.split(", ", 1)[0] == d for d, p in zip(dict_lines[:100], post_lines[:100]))
        ok4 = check("postings.txt 第 i 行 term == dictionary.txt 第 i 行（抽查前 100 行）", lines_match)
        all_passed = all_passed and ok3 and ok4

        # 3. lexicon.tsv 與 doc_map.json 驗證
        lex_lines = (warc_out_path / "lexicon.tsv").read_text(encoding="utf-8").splitlines()
        with (warc_out_path / "doc_map.json").open() as f:
            dm_json = json.load(f)
        ok5 = check("lexicon.tsv 行數 == vocab_size", len(lex_lines) == stats["vocab_size"])
        ok6 = check("doc_map.json 項目數 == N", len(dm_json) == stats["N"])
        all_passed = all_passed and ok5 and ok6

        # 4. postings.bin 壓縮率驗證
        bin_size = (warc_out_path / "postings.bin").stat().st_size
        total_integers = 0
        for _, plist in idx_warc.iter_postings():
            for p in plist:
                total_integers += 3 + len(p.positions)
        raw_size = total_integers * 4
        compression_ratio = bin_size / raw_size if raw_size else 1.0
        ok7 = check(
            f"postings.bin 壓縮率 ({compression_ratio:.1%}) < 60%",
            compression_ratio < 0.6,
            f"bin: {bin_size:,} bytes vs raw: {raw_size:,} bytes",
        )
        all_passed = all_passed and ok7

        # 5. IndexReader 與 postings.txt 解析雙重抽查（高頻詞 + 隨機詞）
        reader_warc = IndexReader(warc_out_path)
        top_terms = sorted(idx_warc._cols, key=idx_warc.df, reverse=True)[:5]
        sample_terms = top_terms + list(idx_warc.index.keys())[:5]
        for t in sample_terms:
            orig = idx_warc.get_postings(t)
            rb = reader_warc.get_postings(t)
            orig_tuples = [(p.doc_num, p.tf, list(p.positions)) for p in orig]
            rb_tuples = [(p.doc_num, p.tf, list(p.positions)) for p in rb]
            ok_r = check(f"  term '{t}' (df={len(orig)}) Reader round-trip 一致", orig_tuples == rb_tuples)

            # 同時驗證 postings.txt 裡的文字解析
            # 找到該 term 在 postings.txt 的行
            idx_in_dict = dict_lines.index(t)
            pt, df, plist = parse_postings_line(post_lines[idx_in_dict])
            ok_txt = check(f"  term '{t}' postings.txt 解析一致", pt == t and df == len(orig) and plist == orig_tuples)
            all_passed = all_passed and ok_r and ok_txt

        print("\n  [WARC Output Summary]")
        print(f"    - dictionary.txt : {dict_path.stat().st_size:,} bytes ({len(dict_lines):,} terms)")
        print(f"    - postings.txt   : {post_path.stat().st_size:,} bytes")
        print(f"    - postings.bin   : {bin_size:,} bytes (compressed to {compression_ratio:.1%})")
        print(f"    - lexicon.tsv    : {(warc_out_path / 'lexicon.tsv').stat().st_size:,} bytes")
        print(f"    - doc_map.json   : {(warc_out_path / 'doc_map.json').stat().st_size:,} bytes")
        print(f"    - metadata.json  : {(warc_out_path / 'metadata.json').stat().st_size:,} bytes")


# ===========================================================================
# 結果總結
# ===========================================================================
section("Test Summary")
print(f"\n  Overall: {'ALL PASSED ✓' if all_passed else 'SOME FAILED ✗'}\n")
sys.exit(0 if all_passed else 1)
