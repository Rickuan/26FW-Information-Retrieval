"""M4：Index Writer & Reader

實作步驟（按計畫順序）：
  4-A  write_dictionary / write_postings_text — 作業規定格式（含 positions）
  4-B  write_metadata / write_doc_map        — JSON 元資料
  4-C  encode_vbyte / decode_vbyte           — VByte 壓縮工具（LEB128 變體）
  4-D  write_binary_format                   — postings.bin + lexicon.tsv
  4-E  IndexReader                            — lazy-load lexicon，seek + decode
  4-F  write_all                             — 單次 iter_postings() 走訪寫出所有檔案

Block 二進制格式（每個 term，按字典序）：
  [df: uint32 big-endian]
  per posting（delta-encoded doc_num, 原始 tf, 原始 n_pos, delta positions）:
    [Δdoc_num: VByte][tf: VByte][n_pos: VByte][Δpos…: VByte …]

lexicon.tsv（字典序，TAB 分隔）：
  term TAB df TAB byte_offset TAB byte_length
"""
from __future__ import annotations

import csv
import json
import struct
from array import array
from datetime import datetime, timezone
from pathlib import Path

from indexer import DocEntry, Indexer, Posting


# ---------------------------------------------------------------------------
# Step 4-A helpers：作業規定格式（Fig. 2.11）
# ---------------------------------------------------------------------------

def format_line(term: str, plist: list[Posting]) -> str:
    """作業規定格式：term, df: <docID, tf: <pos1, pos2, …>; docID, tf: <pos1, …>; …>"""
    body = "; ".join(f"{p.doc_num}, {p.tf}: <{', '.join(map(str, p.positions))}>" for p in plist)
    return f"{term}, {len(plist)}: <{body}>\n"


def parse_postings_line(line: str) -> tuple[str, int, list[tuple[int, int, list[int]]]]:
    """解析作業規定格式 postings.txt 的單一行，供驗證使用。

    依計畫說明：以第一個 ", " 切出 term（term 可能含逗號但無空格，例如 10,000）。
    Returns:
        (term, df, [(doc_num, tf, positions), ...])
    """
    line = line.rstrip("\r\n")
    term, rest = line.split(", ", 1)
    df_str, rest = rest.split(": <", 1)
    df = int(df_str)
    if not rest.endswith(">"):
        raise ValueError(f"Invalid line format: missing closing '>': {line!r}")
    body = rest[:-1]
    if not body:
        return term, df, []

    postings = []
    # 每筆 posting 以 "; " 分隔
    for entry_str in body.split("; "):
        doc_tf_str, pos_block = entry_str.split(": <", 1)
        doc_str, tf_str = doc_tf_str.split(", ", 1)
        doc_num = int(doc_str)
        tf = int(tf_str)
        pos_str = pos_block.rstrip(">")
        positions = [int(p) for p in pos_str.split(", ")] if pos_str else []
        postings.append((doc_num, tf, positions))

    return term, df, postings


def write_dictionary(indexer: Indexer, path: str | Path) -> None:
    """將排序後詞彙寫入 dictionary.txt，一行一個。"""
    path = Path(path)
    with path.open("w", encoding="utf-8") as f:
        for term, _ in indexer.iter_postings():
            f.write(f"{term}\n")


def write_postings_text(indexer: Indexer, path: str | Path) -> None:
    """將 index 依作業規定格式寫入 postings.txt。"""
    path = Path(path)
    with path.open("w", encoding="utf-8") as f:
        for term, plist in indexer.iter_postings():
            f.write(format_line(term, plist))


# ---------------------------------------------------------------------------
# Step 4-C：VByte 壓縮工具
# ---------------------------------------------------------------------------

def encode_vbyte(n: int) -> bytes:
    """將非負整數 n 編碼為 VByte（variable-byte）格式。

    每個 byte 的最高位（continuation bit）：
      0 = 最後一個 byte
      1 = 還有後續 byte
    註：此為 LEB128 變體（低位在前、非最後 byte 設最高位）。

    範例：
      encode_vbyte(1)   -> b'\\x01'
      encode_vbyte(127) -> b'\\x7f'
      encode_vbyte(128) -> b'\\x80\\x01'
      encode_vbyte(300) -> b'\\xac\\x02'
    """
    if n < 0:
        raise ValueError(f"VByte 只支援非負整數，got {n}")
    out = bytearray()
    while True:
        out.append(n & 0x7F)
        n >>= 7
        if n == 0:
            break
        # 設定最高位表示「還有後續 byte」
        out[-1] |= 0x80
    return bytes(out)


def decode_vbyte(data: bytes | bytearray | memoryview, offset: int) -> tuple[int, int]:
    """從 data[offset:] 解碼一個 VByte 整數。

    Returns:
        (value, new_offset)：解碼後的整數值，以及下一個未讀 byte 的位移量。
    """
    value = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            break
        shift += 7
    return value, offset


# ---------------------------------------------------------------------------
# Step 4-D helpers：posting block encode / decode
# ---------------------------------------------------------------------------

def encode_postings_block(postings: list[Posting]) -> bytes:
    """將一個 term 的 postings list 編碼為二進制 block。

    格式：
      [df: uint32 big-endian]
      per posting（delta-encoded doc_num, 原始 tf, 原始 n_pos, delta positions）:
        [Δdoc_num: VByte][tf: VByte][n_pos: VByte][Δpos...: VByte]

    Args:
        postings: list of Posting（doc_num 已嚴格遞增）
    """
    buf = bytearray()
    df = len(postings)
    buf += struct.pack(">I", df)  # uint32 big-endian

    prev_doc = 0
    for p in postings:
        delta_doc = p.doc_num - prev_doc
        prev_doc = p.doc_num

        buf += encode_vbyte(delta_doc)
        buf += encode_vbyte(p.tf)
        buf += encode_vbyte(len(p.positions))

        prev_pos = 0
        for pos in p.positions:
            buf += encode_vbyte(pos - prev_pos)
            prev_pos = pos

    return bytes(buf)


def decode_postings_block(data: bytes | bytearray | memoryview) -> list[Posting]:
    """將 encode_postings_block 產生的二進制 block 解碼回 list[Posting]。

    Returns:
        list of Posting，其中 positions 為 array('I')
    """
    offset = 0
    df = struct.unpack_from(">I", data, offset)[0]
    offset += 4

    postings: list[Posting] = []
    prev_doc = 0
    for _ in range(df):
        delta_doc, offset = decode_vbyte(data, offset)
        doc_num = prev_doc + delta_doc
        prev_doc = doc_num

        tf, offset = decode_vbyte(data, offset)
        n_pos, offset = decode_vbyte(data, offset)

        positions = array("I")
        prev_pos = 0
        for _ in range(n_pos):
            delta_pos, offset = decode_vbyte(data, offset)
            pos = prev_pos + delta_pos
            positions.append(pos)
            prev_pos = pos

        postings.append(Posting(doc_num=doc_num, tf=tf, positions=positions))

    return postings


def write_binary_format(indexer: Indexer, output_dir: str | Path) -> None:
    """將 index 以 VByte+Delta 壓縮格式寫入 postings.bin，並生成 lexicon.tsv。"""
    out_dir = Path(output_dir)
    bin_path = out_dir / "postings.bin"
    lex_path = out_dir / "lexicon.tsv"

    with bin_path.open("wb") as bin_f, lex_path.open("w", encoding="utf-8", newline="") as lex_f:
        writer = csv.writer(lex_f, delimiter="\t", lineterminator="\n")
        offset = 0
        for term, plist in indexer.iter_postings():
            block = encode_postings_block(plist)
            byte_len = len(block)
            bin_f.write(block)
            writer.writerow([term, len(plist), offset, byte_len])
            offset += byte_len


# ---------------------------------------------------------------------------
# IndexWriter 類別
# ---------------------------------------------------------------------------

class IndexWriter:
    """將 Indexer 序列化到磁碟。

    Args:
        output_dir: 輸出目錄路徑（字串或 Path）。不存在時自動建立。
    """

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Step 4-F：單次走訪寫出所有檔案（主程式首選）
    # ------------------------------------------------------------------

    def write_all(self, indexer: Indexer, config: dict | None = None) -> None:
        """單次走訪 iter_postings() 寫出所有產物。

        包含：
          - dictionary.txt（排序後詞彙，一行一個）
          - postings.txt（作業規定格式）
          - postings.bin（VByte + Delta 二進制 block）
          - lexicon.tsv（term TAB df TAB offset TAB length）
          - doc_map.json（文件對照表）
          - metadata.json（統計資料與配置）
        """
        dict_path = self.output_dir / "dictionary.txt"
        post_text_path = self.output_dir / "postings.txt"
        bin_path = self.output_dir / "postings.bin"
        lex_path = self.output_dir / "lexicon.tsv"

        with (
            dict_path.open("w", encoding="utf-8") as dict_f,
            post_text_path.open("w", encoding="utf-8") as post_f,
            bin_path.open("wb") as bin_f,
            lex_path.open("w", encoding="utf-8", newline="") as lex_f,
        ):
            lex_writer = csv.writer(lex_f, delimiter="\t", lineterminator="\n")
            offset = 0
            for term, plist in indexer.iter_postings():
                # 1. dictionary.txt
                dict_f.write(f"{term}\n")

                # 2. postings.txt
                post_f.write(format_line(term, plist))

                # 3. postings.bin & lexicon.tsv
                block = encode_postings_block(plist)
                byte_len = len(block)
                bin_f.write(block)
                lex_writer.writerow([term, len(plist), offset, byte_len])
                offset += byte_len

        self.write_doc_map(indexer)
        self.write_metadata(indexer, config or {})

    # ------------------------------------------------------------------
    # Step 4-A：作業規定文字格式
    # ------------------------------------------------------------------

    def write_dictionary(self, indexer: Indexer) -> None:
        """將排序後詞彙寫入 dictionary.txt。"""
        write_dictionary(indexer, self.output_dir / "dictionary.txt")

    def write_postings_text(self, indexer: Indexer) -> None:
        """將 index 依作業規定格式寫入 postings.txt。"""
        write_postings_text(indexer, self.output_dir / "postings.txt")


    # ------------------------------------------------------------------
    # Step 4-B：metadata.json + doc_map.json
    # ------------------------------------------------------------------

    def write_metadata(self, indexer: Indexer, config: dict | None = None) -> None:
        """將索引元資料寫入 metadata.json。

        Fields：N, vocab_size, total_tokens, avg_doc_len,
                created_at（ISO 8601 UTC）, preprocessor, spimi
        """
        stats = indexer.get_stats() if hasattr(indexer, "get_stats") else indexer.stats
        meta = {
            "N": stats["N"],
            "vocab_size": stats["vocab_size"],
            "total_tokens": stats["total_tokens"],
            "avg_doc_len": stats["avg_doc_len"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "preprocessor": config if config is not None else {},
            "spimi": bool(getattr(indexer, "spimi", False)),
        }
        out_path = self.output_dir / "metadata.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def write_doc_map(self, indexer: Indexer | dict[int, DocEntry]) -> None:
        """將 doc_map 寫入 doc_map.json。

        Key 為字串化的 doc_num。
        Value：{'trec_id': str, 'doc_len': int, 'url': str}
        """
        doc_map = indexer.doc_map if hasattr(indexer, "doc_map") else indexer
        doc_map_out = {
            str(doc_num): {
                "trec_id": entry.trec_id,
                "doc_len": entry.doc_len,
                "url": entry.url,
            }
            for doc_num, entry in doc_map.items()
        }
        out_path = self.output_dir / "doc_map.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(doc_map_out, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # Step 4-D：Binary format — postings.bin + lexicon.tsv
    # ------------------------------------------------------------------

    def write_binary_format(self, indexer: Indexer) -> None:
        """以 iter_postings() 將 index 壓縮寫入 postings.bin，並生成 lexicon.tsv。"""
        write_binary_format(indexer, self.output_dir)


# ---------------------------------------------------------------------------
# Step 4-E：IndexReader — lazy-load lexicon，seek + decode
# ---------------------------------------------------------------------------

class IndexReader:
    """從磁碟讀取由 IndexWriter 產生的索引。

    使用 lazy-load：建構時只讀 lexicon.tsv（小），postings.bin 依需求 seek。

    Args:
        output_dir: IndexWriter 的輸出目錄路徑。
    """

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self._lexicon: dict[str, tuple[int, int]] | None = None  # term → (offset, length)
        self._postings_path = self.output_dir / "postings.bin"
        self._doc_map: dict[int, DocEntry] | None = None
        self._metadata: dict | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_lexicon(self) -> dict[str, tuple[int, int]]:
        """Lazy-load lexicon.tsv 為 dict[term, (offset, length)]。"""
        if self._lexicon is not None:
            return self._lexicon
        lex_path = self.output_dir / "lexicon.tsv"
        lexicon: dict[str, tuple[int, int]] = {}
        with lex_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f, delimiter="\t")
            for row in reader:
                term, _df, offset, length = row[0], int(row[1]), int(row[2]), int(row[3])
                lexicon[term] = (offset, length)
        self._lexicon = lexicon
        return lexicon

    def _load_doc_map(self) -> dict[int, DocEntry]:
        """Lazy-load doc_map.json 為 dict[doc_num, DocEntry]。"""
        if self._doc_map is not None:
            return self._doc_map
        with (self.output_dir / "doc_map.json").open("r", encoding="utf-8") as f:
            raw = json.load(f)
        self._doc_map = {
            int(k): DocEntry(trec_id=v["trec_id"], doc_len=v["doc_len"], url=v["url"])
            for k, v in raw.items()
        }
        return self._doc_map

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_postings(self, term: str) -> list[Posting]:
        """取得 term 的 postings list。

        Returns:
            list of Posting，其中 positions 為 array('I')。
            若 term 不存在，回傳空 list。
        """
        lexicon = self._load_lexicon()
        if term not in lexicon:
            return []
        offset, length = lexicon[term]
        with self._postings_path.open("rb") as f:
            f.seek(offset)
            data = f.read(length)
        return decode_postings_block(data)

    def get_doc(self, doc_num: int) -> DocEntry | None:
        """取得 doc_num 對應的文件資訊。

        Returns:
            DocEntry 物件；若不存在，回傳 None。
        """
        doc_map = self._load_doc_map()
        return doc_map.get(doc_num)

    def get_metadata(self) -> dict:
        """讀取 metadata.json。"""
        if self._metadata is not None:
            return self._metadata
        with (self.output_dir / "metadata.json").open("r", encoding="utf-8") as f:
            self._metadata = json.load(f)
        return self._metadata

    def vocab_size(self) -> int:
        """詞彙量（等同 lexicon.tsv 行數）。"""
        return len(self._load_lexicon())

    def __contains__(self, term: str) -> bool:
        """支援 `term in reader` 語法。"""
        return term in self._load_lexicon()
