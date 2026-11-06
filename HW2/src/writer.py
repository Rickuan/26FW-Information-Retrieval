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
import hashlib
import json
import mmap
from bisect import bisect_left
import struct
from array import array
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from indexer import DocEntry, Indexer, Posting
from weighting import LOG_BASE, formula, norm_filenames


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

_NORM_SOURCES = ("lexicon.tsv", "postings.bin", "metadata.json")


def _fingerprint(path: Path) -> dict:
    """回傳檔案的 {"size", "sha256"}，供 meta 的 sources 記錄與核對。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return {"size": path.stat().st_size, "sha256": h.hexdigest()}


class IndexReader:
    """從磁碟讀取由 IndexWriter 產生的索引。

    使用 lazy-load：建構時只讀 lexicon.tsv（小），postings.bin 依需求 seek。

    Args:
        output_dir: IndexWriter 的輸出目錄路徑。
    """

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self._lexicon: dict[str, tuple[int, int, int]] | None = None  # term → (df, offset, length)
        self._postings_path = self.output_dir / "postings.bin"
        self._doc_map: dict[int, DocEntry] | None = None
        self._metadata: dict | None = None
        self._vocab: list[str] | None = None  # vocabulary() 快取；與 lexicon 共用字串
        self._norms: dict[str, array] = {}  # get_norms() 快取：scheme → array('d')
        self._mm: mmap.mmap | None = None  # postings.bin 的唯讀 mmap（get_doc_tf 共用）
        # get_champions() 快取：r → (term → (offset, length), champions.r<r>.bin 的內容)
        self._champions: dict[int, tuple[dict[str, tuple[int, int]], bytes]] = {}
        # get_doc_tf 的 LRU 快取（0 = 關閉）：term → (array('I'), array('I'))
        self._tf_cache: OrderedDict[str, tuple[array, array]] = OrderedDict()
        self._tf_cache_size = 0
        self._tf_hits = 0
        self._tf_misses = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_lexicon(self) -> dict[str, tuple[int, int, int]]:
        """Lazy-load lexicon.tsv 為 dict[term, (df, offset, length)]。"""
        if self._lexicon is not None:
            return self._lexicon
        lex_path = self.output_dir / "lexicon.tsv"
        lexicon: dict[str, tuple[int, int, int]] = {}
        with lex_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f, delimiter="\t")
            for row in reader:
                term, df, offset, length = row[0], int(row[1]), int(row[2]), int(row[3])
                lexicon[term] = (df, offset, length)
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

    def _postings_mm(self) -> mmap.mmap:
        """第一次呼叫時以唯讀 mmap 開啟 postings.bin 並快取，之後共用同一個物件。"""
        if self._mm is None:
            with self._postings_path.open("rb") as f:
                self._mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        return self._mm

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
        _df, offset, length = lexicon[term]
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

    # ------------------------------------------------------------------
    # HW2 接口 stub（T1 / T2 / T3）
    # ------------------------------------------------------------------

    @property
    def N(self) -> int:
        """T1：文件總數，即 metadata["N"]。"""
        return int(self.get_metadata()["N"])

    def df(self, term: str) -> int:
        """T1：term 的 document frequency。

        Returns:
            lexicon 中記錄的 df；term 不存在時回傳 0。
        """
        entry = self._load_lexicon().get(term)
        return entry[0] if entry else 0

    def get_norms(self, scheme: str = "ltc") -> array:
        """T2：每篇文件的 vector norm |d|。

        第一次呼叫時核對 meta（log_base、formula、scheme、N、來源檔 size 與 sha256）。
        預設 "ltc" 讀 doc_norms.bin；其他 scheme（加分）讀 doc_norms.<scheme>.bin。
        normalization 為 n 的 scheme 直接回傳全 1.0 的陣列，不讀檔。

        Returns:
            array('d')，下標 = doc_num。

        Raises:
            FileNotFoundError: norm 檔不存在（請先跑 build_norms.py）。
            ValueError: meta 與目前的 index 或公式不一致。
        """
        cached = self._norms.get(scheme)
        if cached is not None:
            return cached
        formula(scheme)  # 先驗證 scheme（不合法時拋出 ValueError）
        if scheme[2] == "n":  # |d| 依定義是 1，不讀檔
            self._norms[scheme] = array("d", [1.0]) * self.N
            return self._norms[scheme]
        bin_name, meta_name = norm_filenames(scheme)
        bin_path = self.output_dir / bin_name
        meta_path = self.output_dir / meta_name
        if not bin_path.exists() or not meta_path.exists():
            raise FileNotFoundError(
                f"{bin_path if not bin_path.exists() else meta_path} not found; "
                "run build_norms.py first"
            )
        with meta_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)
        expected = {"log_base": LOG_BASE, "formula": formula(scheme), "scheme": scheme,
                    "N": self.N, "count": self.N}
        for key, want in expected.items():
            if meta.get(key) != want:
                raise ValueError(f"{meta_name}: {key} is {meta.get(key)!r}, expected {want!r}")
        self._check_sources(meta, meta_name, _NORM_SOURCES)
        if bin_path.stat().st_size != 8 * self.N:
            raise ValueError(
                f"{bin_name}: size is {bin_path.stat().st_size}, expected {8 * self.N}"
            )
        norms = array("d")
        with bin_path.open("rb") as f:
            norms.fromfile(f, self.N)
        self._norms[scheme] = norms
        return norms

    def _check_sources(self, meta: dict, meta_name: str, names: tuple[str, ...]) -> None:
        """核對 meta["sources"] 中每個來源檔的 size 與 sha256 是否與目前的 index 相符。"""
        sources = meta.get("sources", {})
        for name in names:
            rec = sources.get(name)
            if rec is None:
                raise ValueError(f"{meta_name}: sources missing {name}")
            actual = _fingerprint(self.output_dir / name)
            for key in ("size", "sha256"):
                if rec.get(key) != actual[key]:
                    raise ValueError(f"{meta_name}: sources[{name}].{key} does not match index")

    def get_doc_tf(self, term: str) -> tuple[list[int], list[int]]:
        """T3：只取 doc_num 與 tf（略過 positions，不建 Posting 物件）。

        Returns:
            (doc_nums, tfs)，doc_nums 嚴格遞增；term 不存在時回傳 ([], [])。

        Raises:
            ValueError: block 的 df 標頭或長度與 lexicon 不一致。
        """
        if self._tf_cache_size == 0 or term not in self._load_lexicon():
            return self._decode_doc_tf(term)
        cached = self._tf_cache.get(term)
        if cached is not None:
            self._tf_cache.move_to_end(term)
            self._tf_hits += 1
            return list(cached[0]), list(cached[1])
        self._tf_misses += 1
        docs, tfs = self._decode_doc_tf(term)
        self._tf_cache[term] = (array("I", docs), array("I", tfs))
        if len(self._tf_cache) > self._tf_cache_size:
            self._tf_cache.popitem(last=False)
        return docs, tfs

    def _decode_doc_tf(self, term: str) -> tuple[list[int], list[int]]:
        """get_doc_tf 的核心路徑：從 mmap 直接解出 (doc_nums, tfs)，不經快取。"""
        entry = self._load_lexicon().get(term)
        if entry is None:
            return [], []
        df, offset, length = entry
        mm = self._postings_mm()
        end = offset + length
        (block_df,) = struct.unpack_from(">I", mm, offset)
        if block_df != df:
            raise ValueError(f"postings block of {term!r}: df header {block_df} != lexicon {df}")
        pos = offset + 4
        docs: list[int] = []
        tfs: list[int] = []
        doc = 0
        for _ in range(df):
            # Δdoc
            value = 0
            shift = 0
            while True:
                b = mm[pos]
                pos += 1
                value |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
            doc += value
            # tf
            value = 0
            shift = 0
            while True:
                b = mm[pos]
                pos += 1
                value |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
            docs.append(doc)
            tfs.append(value)
            # n_pos
            n_pos = 0
            shift = 0
            while True:
                b = mm[pos]
                pos += 1
                n_pos |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
            # 跳過 n_pos 個 VByte：只掃到最高位為 0 的 byte，不做數值運算
            for _ in range(n_pos):
                while mm[pos] & 0x80:
                    pos += 1
                pos += 1
        if pos != end:
            raise ValueError(f"postings block of {term!r}: decoded to {pos}, expected {end}")
        return docs, tfs

    # ------------------------------------------------------------------
    # HW2 加分接口 stub（T1 / T3）
    # ------------------------------------------------------------------

    def vocabulary(self) -> list[str]:
        """T1 加分：排序過的全部 term（與 lexicon.tsv 順序相同）。

        回傳快取的同一個 list，呼叫端不可修改。
        """
        if self._vocab is None:
            # lexicon.tsv 已依 Python 字串順序排序，dict 保留插入順序，不必再排
            self._vocab = list(self._load_lexicon())
        return self._vocab

    def prefix_terms(self, prefix: str) -> list[str]:
        """T1 加分：依字典序回傳以 prefix 開頭的 term（排序 list + bisect）。

        Raises:
            ValueError: prefix 是空字串。
        """
        if not prefix:
            raise ValueError("prefix must be non-empty")
        vocab = self.vocabulary()
        lo = bisect_left(vocab, prefix)
        if ord(prefix[-1]) == 0x10FFFF:
            # 最後一個字元已是最大 code point，無法 +1 求上界，改為線性往後掃
            hi = lo
            while hi < len(vocab) and vocab[hi].startswith(prefix):
                hi += 1
        else:
            hi = bisect_left(vocab, prefix[:-1] + chr(ord(prefix[-1]) + 1), lo)
        return vocab[lo:hi]

    def _load_champions(self, r: int) -> tuple[dict[str, tuple[int, int]], bytes]:
        """載入並核對 champions.r<r>.*；結果依 r 快取。"""
        cached = self._champions.get(r)
        if cached is not None:
            return cached
        stem = f"champions.r{r}"
        paths = {ext: self.output_dir / f"{stem}.{ext}" for ext in ("bin", "tsv", "meta.json")}
        for path in paths.values():
            if not path.exists():
                raise FileNotFoundError(
                    f"{path} not found; run "
                    f"`uv run python HW2/src/build_champions.py --index-dir {self.output_dir} --r {r}`"
                )
        meta_name = paths["meta.json"].name
        with paths["meta.json"].open("r", encoding="utf-8") as f:
            meta = json.load(f)
        expected = {"r": r, "rule": "(-tf, doc)",
                    "format": "u32be n + n*(vbyte dgap, vbyte tf)", "N": self.N}
        for key, want in expected.items():
            if meta.get(key) != want:
                raise ValueError(f"{meta_name}: {key} is {meta.get(key)!r}, expected {want!r}")
        self._check_sources(meta, meta_name, ("lexicon.tsv", "postings.bin"))
        table: dict[str, tuple[int, int]] = {}
        with paths["tsv"].open("r", encoding="utf-8", newline="") as f:
            for row in csv.reader(f, delimiter="\t"):
                if int(row[1]) != r:
                    raise ValueError(f"{paths['tsv'].name}: n of {row[0]!r} is {row[1]}, expected {r}")
                table[row[0]] = (int(row[2]), int(row[3]))
        if len(table) != meta.get("count"):
            raise ValueError(
                f"{paths['tsv'].name}: {len(table)} rows, meta count is {meta.get('count')!r}"
            )
        loaded = (table, paths["bin"].read_bytes())
        self._champions[r] = loaded
        return loaded

    def get_champions(self, term: str, r: int = 50) -> tuple[list[int], list[int]]:
        """T3 加分：讀取 T2 產出的 champion list（tf 前 r 名）。

        Returns:
            (doc_nums, tfs)，doc_nums 嚴格遞增；df ≤ r 時等同 get_doc_tf(term)；
            term 不存在時回傳 ([], [])（此時不載入 champion 檔）。

        Raises:
            FileNotFoundError: champions.r<r>.* 不存在（請先跑 build_champions.py）。
            ValueError: r < 1，或 meta／tsv 與目前的 index 不一致。
        """
        if r < 1:
            raise ValueError(f"r must be >= 1, got {r}")
        entry = self._load_lexicon().get(term)
        if entry is None:
            return [], []
        table, data = self._load_champions(r)
        df = entry[0]
        if df <= r:
            return self.get_doc_tf(term)
        loc = table.get(term)
        if loc is None:
            raise ValueError(f"champions.r{r}.tsv: missing {term!r} (df {df} > r)")
        offset, length = loc
        end = offset + length
        (n,) = struct.unpack_from(">I", data, offset)
        if n != r:
            raise ValueError(f"champions.r{r}.bin: block of {term!r} has n={n}, expected {r}")
        pos = offset + 4
        docs: list[int] = []
        tfs: list[int] = []
        doc = 0
        for _ in range(n):
            gap, pos = decode_vbyte(data, pos)
            tf, pos = decode_vbyte(data, pos)
            doc += gap
            docs.append(doc)
            tfs.append(tf)
        if pos != end:
            raise ValueError(f"champions.r{r}.bin: block of {term!r} decoded to {pos}, expected {end}")
        return docs, tfs

    def set_doc_tf_cache(self, maxsize: int) -> None:
        """T3 加分：設定 get_doc_tf 的 LRU 快取大小；0 = 關閉（預設）。重設時清空快取與計數。

        Raises:
            ValueError: maxsize < 0。
        """
        if maxsize < 0:
            raise ValueError(f"maxsize must be >= 0, got {maxsize}")
        self._tf_cache_size = maxsize
        self._tf_cache.clear()
        self._tf_hits = 0
        self._tf_misses = 0

    def doc_tf_cache_info(self) -> tuple[int, int]:
        """T3 加分：回傳 get_doc_tf 快取的 (hits, misses)。"""
        return self._tf_hits, self._tf_misses
