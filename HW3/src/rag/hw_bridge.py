"""HW1/HW2 程式碼（hwlib）的唯一使用位置（規格 2.1）。

其他模組不得 import hwlib，一律透過這裡的函式與 `Ranker`。
hwlib 會直接 print 到 stdout；這裡每次呼叫 hwlib 都以 `redirect_stdout(sys.stderr)` 包住，
讓 stdout 只留給 HW3 的結果（規格 1.6-6）。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from collections.abc import Iterator
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from hwlib import build_norms, documents, indexer, rank, tokenizer, warc, writer

PREPROCESSOR_CONFIG = {"casefold": True, "stopword": True, "stem": True, "lemma": False}
NORM_SCHEME = "ltc"          # build_norms 的 doc 端 scheme
RANK_SCHEME = "ltc.ltc"      # rank() 的 SMART scheme

T = TypeVar("T")


def _to_stderr():
    return redirect_stdout(sys.stderr)


def _quiet_iter(it: Iterator[T]) -> Iterator[T]:
    """只在推進 hwlib 的 generator 時轉向 stdout。

    不能把整個 generator 包在 `with redirect_stdout(...)` 裡：generator 暫停在 yield 時
    context 仍然有效，呼叫端在兩次 next() 之間的 print 也會被轉到 stderr。
    """
    while True:
        with _to_stderr():
            try:
                item = next(it)
            except StopIteration:
                return
        yield item


def _check_limit(limit: int | None) -> None:
    if limit is not None and limit < 1:
        raise ValueError(f"limit must be None or >= 1, got {limit!r}")


# ---------------------------------------------------------------------------
# 讀取語料
# ---------------------------------------------------------------------------

def iter_documents(warc_path, limit: int | None = None) -> Iterator[tuple[int, str, str, str]]:
    """產出 (docid, trec_id, url, cleaned_text)，依 WARC 內順序。

    docid = TREC-ID 尾碼整數（不是流水號）。被排除的文件不會產出；
    清理後為空字串的文件仍會產出。limit 計算的是產出的篇數。
    """
    _check_limit(limit)
    with _to_stderr():
        docs = documents.iter_documents(str(warc_path))
    for n, doc in enumerate(_quiet_iter(docs), 1):
        yield doc.doc_num, doc.trec_id, doc.url, doc.text
        if limit is not None and n >= limit:
            return


def iter_raw_records(warc_path) -> Iterator[bytes]:
    """逐筆產出 WARC record 的原始 bytes（以 b"WARC/0.18" 開頭的行切割）；依序串接 = 原檔。"""
    with _to_stderr():
        records = warc.iter_records(warc_path)
    yield from _quiet_iter(records)


@dataclass(frozen=True, slots=True)
class TargetInfo:
    """inject 驗證用的目標文件資訊（規格 1.5 規則 2）。"""
    docid: int                 # TREC-ID 尾碼整數
    content_type: str          # HTTP Content-Type 的 MIME 部分：小寫、去掉參數；缺少時為 "(none)"
    cleaned_text: str | None   # 與 iter_documents 的 cleaned_text 相同；hwlib 排除此文件時為 None


def inspect_targets(warc_path, trec_ids: set[str]) -> dict[str, TargetInfo]:
    """只讀一次 WARC，回傳 {trec_id: TargetInfo}；只對目標 record 執行清理。

    - 只看 WARC-Type 為 response 的 record（與 iter_documents 相同的集合）。
    - 找不到的 trec_id 不會出現在回傳的 dict 中。
    - 所有目標都找到後立即停止讀取。
    """
    wanted = set(trec_ids)
    found: dict[str, TargetInfo] = {}
    if not wanted:
        return found
    with _to_stderr():
        responses = warc.iter_responses(warc_path)
    for resp in _quiet_iter(responses):
        if resp.trec_id not in wanted or resp.trec_id in found:
            continue
        with _to_stderr():
            doc = documents.to_document(resp)
        found[resp.trec_id] = TargetInfo(
            docid=resp.doc_num,
            content_type=resp.content_type,
            cleaned_text=None if doc is None else doc.text,
        )
        if len(found) == len(wanted):
            break
    return found


# ---------------------------------------------------------------------------
# 前處理
# ---------------------------------------------------------------------------

_PRE: tokenizer.Preprocessor | None = None


def _preprocessor() -> tokenizer.Preprocessor:
    """模組層級單例；第一次使用時才建立（初始化約 1.8 秒）。"""
    global _PRE
    if _PRE is None:
        with _to_stderr():
            _PRE = tokenizer.Preprocessor(**PREPROCESSOR_CONFIG)
    return _PRE


def preprocess(text: str) -> list[str]:
    """stop + stem 前處理，回傳 term 序列（與索引使用同一套設定）。"""
    pre = _preprocessor()
    with _to_stderr():
        return [t for _, t in pre.process(text)]


# ---------------------------------------------------------------------------
# 建置詞彙索引與 norms
# ---------------------------------------------------------------------------

def _check_docid_contiguous(index_dir) -> None:
    """規格 2.3：doc_map 的 key 必須恰好是 0..N-1，且 metadata 的 N == len(doc_map)。"""
    index_dir = Path(index_dir)
    with (index_dir / "doc_map.json").open("r", encoding="utf-8") as f:
        keys = set(json.load(f))
    with (index_dir / "metadata.json").open("r", encoding="utf-8") as f:
        n_meta = json.load(f)["N"]
    expected = {str(i) for i in range(len(keys))}
    if keys != expected:
        missing = sorted(expected - keys, key=int)[:5]
        extra = sorted(keys - expected, key=int)[:5]
        raise ValueError(
            f"{index_dir}/doc_map.json: docid 不是連續的 0..{len(keys) - 1}"
            f"（缺少例如 {missing}，多出例如 {extra}）"
        )
    if n_meta != len(keys):
        raise ValueError(f"{index_dir}/metadata.json: N = {n_meta}，但 doc_map 有 {len(keys)} 筆")


def build_lexical_index(warc_path, index_dir, limit: int | None = None) -> dict:
    """建立 stop+stem 詞彙索引（lexicon.tsv、postings.bin、doc_map.json、metadata.json）。

    依 HW1 run_build 的核心邏輯，但不用 Indexer.build()（會 print）與 write_all()
    （會多寫出 postings.txt、dictionary.txt）。metadata.json 最後寫。
    寫完後執行 docid 連續性檢查，不成立就 raise。

    Returns:
        Indexer 的統計：{"N", "vocab_size", "total_tokens", "avg_doc_len"}。
    """
    _check_limit(limit)
    pre = _preprocessor()
    with _to_stderr():
        ix = indexer.Indexer(spimi=False)
        for n, doc in enumerate(documents.iter_documents(str(warc_path)), 1):
            ix.add_document(doc, pre.process(doc.text))
            if limit is not None and n >= limit:
                break
        w = writer.IndexWriter(index_dir)
        w.write_binary_format(ix)
        w.write_doc_map(ix)
        w.write_metadata(ix, config=dict(PREPROCESSOR_CONFIG))
        stats = dict(ix.stats)
    _check_docid_contiguous(index_dir)
    return stats


def build_doc_norms(index_dir) -> None:
    """產生 ltc 的 doc_norms.bin 與 doc_norms.meta.json；必須在 metadata.json 寫完之後呼叫。"""
    with _to_stderr():
        build_norms.build_norms(index_dir, NORM_SCHEME)


# ---------------------------------------------------------------------------
# 排序
# ---------------------------------------------------------------------------

class Ranker:
    """HW2 的 VSM 排序器（ltc.ltc、自由文字路徑）。lexical.py 只使用這個介面。"""

    N: int

    def __init__(self, index_dir) -> None:
        with _to_stderr():
            self._reader = writer.IndexReader(index_dir)
            meta_pre = self._reader.get_metadata().get("preprocessor")
            if meta_pre != PREPROCESSOR_CONFIG:
                raise ValueError(
                    f"{index_dir}: 索引的 preprocessor 設定 {meta_pre!r} "
                    f"與 hw_bridge 的 {PREPROCESSOR_CONFIG!r} 不同"
                )
            # 讓 sha256 / N 檢查在載入時就失敗，而不是第一次查詢時
            self._reader.get_norms(NORM_SCHEME)
            self.N = self._reader.N

    def search(self, terms: list[str], k: int) -> list[tuple[int, float]]:
        """回傳 [(docid, score)]，依 (-round(score, 6), docid) 排序，取前 k 筆。

        terms 為空，或所有 term 的 df 都是 0 時回傳 []。
        """
        if not terms:
            return []
        with _to_stderr():
            hits = rank.rank(Counter(terms), None, self._reader, scheme=RANK_SCHEME)
        return hits[:k]


def load_ranker(index_dir) -> Ranker:
    return Ranker(index_dir)
