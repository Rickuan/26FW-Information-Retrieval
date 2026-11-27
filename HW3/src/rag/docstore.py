"""SQLite doc store：建置（給 build.py 的 docstore 階段）與唯讀存取（規格 1.4、2.4）。

設計見 plans/A2-docstore-passages.md：
- build_docstore 寫到 `<db_path>.tmp`，全部成功並通過檢查後才 os.replace 成 db_path，
  所以 db_path 存在 ⇔ 內容完整（build.py 的「產物已存在就跳過」可直接看檔案）。
- DocStore 以唯讀模式開啟，提供 get_doc / get_passage / get_passages_by_doc，
  以及給 embedding 階段使用的 count_passages / iter_passages。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from rag import hw_bridge
from rag.passages import number_passages

# 與規格 1.4 完全相同；idx_passages_docid 在資料寫完後才建立
SCHEMA_TABLES = """
CREATE TABLE docs (
  docid   INTEGER PRIMARY KEY,
  trec_id TEXT NOT NULL,
  url     TEXT,
  text    TEXT NOT NULL
);
CREATE TABLE passages (
  pid        INTEGER PRIMARY KEY,
  docid      INTEGER NOT NULL REFERENCES docs(docid),
  start_word INTEGER NOT NULL,
  end_word   INTEGER NOT NULL,
  text       TEXT NOT NULL
);
"""
SCHEMA_INDEX = "CREATE INDEX idx_passages_docid ON passages(docid);"

BATCH_DOCS = 1000   # 每累積這麼多篇就 executemany 一次


@dataclass(frozen=True, slots=True)
class Doc:
    docid: int
    trec_id: str
    url: str | None
    text: str


@dataclass(frozen=True, slots=True)
class Passage:
    pid: int
    docid: int
    start_word: int
    end_word: int
    text: str


# ---------------------------------------------------------------------------
# 建置
# ---------------------------------------------------------------------------

def _check_against_doc_map(conn: sqlite3.Connection, doc_map_path: Path) -> None:
    """文件數與 docid 集合必須與 doc_map.json 一致；pid 必須是 0..N-1 連續。"""
    with Path(doc_map_path).open("r", encoding="utf-8") as f:
        doc_map_ids = {int(k) for k in json.load(f)}
    n_docs = conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    if n_docs != len(doc_map_ids):
        raise ValueError(f"docstore 有 {n_docs} 篇文件，但 {doc_map_path} 有 {len(doc_map_ids)} 筆")
    ids = {r[0] for r in conn.execute("SELECT docid FROM docs")}
    if ids != doc_map_ids:
        diff = sorted(ids ^ doc_map_ids)[:5]
        raise ValueError(f"docstore 的 docid 集合與 {doc_map_path} 不同（例如 {diff}）")
    n, lo, hi = conn.execute("SELECT COUNT(*), MIN(pid), MAX(pid) FROM passages").fetchone()
    if n and (lo != 0 or hi != n - 1):
        raise ValueError(f"pid 不連續：{n} 段，MIN = {lo}，MAX = {hi}")


def build_docstore(
    warc_path,
    db_path,
    limit: int | None,
    *,
    doc_map_path,
    passage_words: int,
    passage_stride: int,
) -> dict:
    """由 hw_bridge.iter_documents 建立 docs 與 passages 表。

    Args:
        warc_path: 輸入 WARC（build 時為 injected_warc）。
        db_path: 輸出的 docstore.sqlite；上層資料夾會自動建立，已存在時會被取代。
        limit: None 或 >= 1（前 N 篇，與索引階段相同）。
        doc_map_path: 同一次建置的 index 階段寫出的 doc_map.json，用來檢查文件數。
        passage_words, passage_stride: 切分參數（config 的 [retrieval]）。

    Returns:
        {"n_docs", "n_passages", "n_empty_docs", "seconds"}
    """
    t0 = time.perf_counter()
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = db_path.with_name(db_path.name + ".tmp")
    tmp_path.unlink(missing_ok=True)

    n_docs = n_passages = n_empty = 0
    conn = sqlite3.connect(tmp_path, isolation_level=None)
    try:
        # tmp 檔失敗就丟棄，不需要 journal 與 fsync
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.executescript(SCHEMA_TABLES)
        conn.execute("BEGIN")

        doc_rows: list[tuple[int, str, str, str]] = []

        def flush() -> None:
            nonlocal n_passages
            p_rows = list(number_passages(
                ((d, t) for d, _, _, t in doc_rows), passage_words, passage_stride))
            # number_passages 每次從 0 編號；這裡平移成全域 pid
            p_rows = [(pid + n_passages, *rest) for pid, *rest in p_rows]
            conn.executemany("INSERT INTO docs VALUES (?, ?, ?, ?)", doc_rows)
            conn.executemany("INSERT INTO passages VALUES (?, ?, ?, ?, ?)", p_rows)
            n_passages += len(p_rows)
            doc_rows.clear()

        for docid, trec_id, url, text in hw_bridge.iter_documents(warc_path, limit):
            doc_rows.append((docid, trec_id, url, text))
            n_docs += 1
            if not text.split():
                n_empty += 1
            if len(doc_rows) >= BATCH_DOCS:
                flush()
        flush()

        conn.execute(SCHEMA_INDEX)
        conn.execute("COMMIT")
        _check_against_doc_map(conn, doc_map_path)
    except BaseException:
        conn.close()
        tmp_path.unlink(missing_ok=True)
        raise
    conn.close()
    os.replace(tmp_path, db_path)
    return {
        "n_docs": n_docs,
        "n_passages": n_passages,
        "n_empty_docs": n_empty,
        "seconds": time.perf_counter() - t0,
    }


# ---------------------------------------------------------------------------
# 唯讀存取
# ---------------------------------------------------------------------------

class DocStore:
    """唯讀的 docstore 連線；可用 `with DocStore(path) as ds:`。"""

    def __init__(self, db_path) -> None:
        db_path = Path(db_path)
        if not db_path.is_file():
            raise FileNotFoundError(f"找不到 docstore：{db_path}（請先執行 build）")
        # 唯讀 URI；check_same_thread=False 讓 LangChain 的 batch() 跨執行緒查詢（只讀，安全）
        self._conn = sqlite3.connect(
            f"{db_path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
        self.path = db_path

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> DocStore:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def get_doc(self, docid: int) -> Doc:
        row = self._conn.execute(
            "SELECT docid, trec_id, url, text FROM docs WHERE docid = ?", (docid,)).fetchone()
        if row is None:
            raise KeyError(docid)
        return Doc(*row)

    def get_passage(self, pid: int) -> Passage:
        row = self._conn.execute(
            "SELECT pid, docid, start_word, end_word, text FROM passages WHERE pid = ?",
            (pid,)).fetchone()
        if row is None:
            raise KeyError(pid)
        return Passage(*row)

    def get_passages_by_doc(self, docid: int) -> list[Passage]:
        """依 pid 排序；空文件或 docid 不存在時回傳 []。"""
        rows = self._conn.execute(
            "SELECT pid, docid, start_word, end_word, text FROM passages "
            "WHERE docid = ? ORDER BY pid", (docid,)).fetchall()
        return [Passage(*r) for r in rows]

    def count_passages(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0]

    def iter_passages(self, start_pid: int = 0) -> Iterator[Passage]:
        """依 pid 遞增產出 pid >= start_pid 的 passage（embedding 階段分批與續跑用）。"""
        cur = self._conn.execute(
            "SELECT pid, docid, start_word, end_word, text FROM passages "
            "WHERE pid >= ? ORDER BY pid", (start_pid,))
        while rows := cur.fetchmany(1000):
            for r in rows:
                yield Passage(*r)
