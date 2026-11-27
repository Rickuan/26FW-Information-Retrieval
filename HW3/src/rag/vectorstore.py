"""Embedding 階段（checkpoint、可續跑）、FAISS 向量庫的組裝與載入（規格 2.5，A3）。

- 唯一匯入 faiss / LangChain FAISS / DistanceStrategy 的模組。DistanceStrategy 必須從
  `langchain_community.vectorstores.utils` 匯入（從 `.vectorstores` 會拿到 kinetica 的同名 enum，
  FAISS 會在不報錯的情況下改建 IndexFlatL2）。
- checkpoint（`embed_ckpt_dir/`）：
  - `ckpt_meta.json`：embed 設定 + passage 參數 + limit + n_passages；與目前不同就清空重來。
  - 每批一檔 `{start:07d}-{end:07d}.npy`：float32 (end-start, dim)，已 normalize，pid 範圍 [start, end)。
  - 原子寫入（`.tmp` → os.replace）；續跑時只保留從 pid 0 起首尾相接的檔案。
- FAISS 的第 i 個向量 = pid i（依 pid 順序加入）；metadata `{"pid", "docid"}`、id = `str(pid)`。
- 檢查一律用明確 raise，不用 assert 敘述（python -O 會略過）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from langchain_community.vectorstores import FAISS
from langchain_community.vectorstores.utils import DistanceStrategy

from rag.config import get_config, paths, require_build_done
from rag.docstore import DocStore
from rag.embed import PrefixedOllamaEmbeddings

CKPT_META = "ckpt_meta.json"
_CKPT_RE = re.compile(r"^(\d{7})-(\d{7})\.npy$")
# build_meta 欄位 → config [embed] 欄位（load 時比對；規格 2.5）
_EMBED_FIELDS = {"embed_model": "model", "query_prefix": "query_prefix",
                 "doc_prefix": "doc_prefix", "dim": "dim"}


class EmbedMismatchError(RuntimeError):
    """build_meta 的 embed 設定與目前 config 不一致（需要 build --force）。"""


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- checkpoint

def ckpt_meta_from_config(cfg: dict[str, Any], *, limit: int | None, n_passages: int) -> dict[str, Any]:
    """產生要寫入 / 比對的 ckpt_meta（A3 第 3 節、Q3）。"""
    e, r = cfg["embed"], cfg["retrieval"]
    return {"embed_model": e["model"], "query_prefix": e["query_prefix"], "doc_prefix": e["doc_prefix"],
            "dim": e["dim"], "passage_words": r["passage_words"], "passage_stride": r["passage_stride"],
            "limit": limit, "n_passages": n_passages}


def _ckpt_name(start: int, end: int) -> str:
    return f"{start:07d}-{end:07d}.npy"


def _scan_ckpt(ckpt_dir: Path, dim: int, n_passages: int, *, repair: bool) -> int:
    """回傳從 pid 0 起首尾相接、形狀正確的 checkpoint 涵蓋到的 end。

    repair=True 時刪除 `.tmp` 與第一個不合格檔案（缺口、形狀錯、無法讀取）及其後的所有檔案。
    """
    files = sorted((int(m[1]), int(m[2]), p) for p in ckpt_dir.iterdir()
                   if (m := _CKPT_RE.match(p.name)))
    covered, bad_from = 0, None
    for i, (start, end, p) in enumerate(files):
        ok = start == covered and start < end <= n_passages
        if ok:
            try:
                arr = np.load(p, mmap_mode="r")
                ok = arr.shape == (end - start, dim) and arr.dtype == np.float32
            except (OSError, ValueError):
                ok = False
        if not ok:
            bad_from = i
            break
        covered = end
    if repair:
        for p in ckpt_dir.glob("*.tmp"):
            p.unlink()
        if bad_from is not None:
            _log(f"[embed] checkpoint 從 {files[bad_from][2].name} 起不連續或損壞，刪除 {len(files) - bad_from} 個檔案")
            for _, _, p in files[bad_from:]:
                p.unlink()
    return covered


def _prepare_ckpt_dir(ckpt_dir: Path, ckpt_meta: dict[str, Any]) -> None:
    """ckpt_meta 不存在或不同 → 清空目錄並寫入新的 meta。"""
    meta_path = ckpt_dir / CKPT_META
    old = None
    if meta_path.is_file():
        try:
            old = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            old = None
    if old == ckpt_meta:
        return
    if ckpt_dir.exists():
        diff = sorted(k for k in ckpt_meta if not isinstance(old, dict) or old.get(k) != ckpt_meta[k])
        _log(f"[embed] checkpoint 設定不同（{', '.join(diff) if old else '沒有 ckpt_meta'}），清空重來")
        shutil.rmtree(ckpt_dir)
    ckpt_dir.mkdir(parents=True)
    tmp = meta_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ckpt_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, meta_path)


def embed_passages(db_path, ckpt_dir, embeddings: PrefixedOllamaEmbeddings, *,
                   batch_size: int, ckpt_meta: dict[str, Any]) -> dict[str, Any]:
    """把 docstore 的所有 passage 依 pid 分批 embed，每批存一個 checkpoint；可中斷後續跑。

    Args:
        db_path: docstore.sqlite（A2）。
        ckpt_dir: `paths(...)["embed_ckpt_dir"]`。
        embeddings: build 模式的 PrefixedOllamaEmbeddings。
        batch_size: 每批段數（config `[embed] batch_size`）；不入 ckpt_meta，續跑只看 pid 範圍。
        ckpt_meta: `ckpt_meta_from_config(...)` 的結果；其 n_passages 必須等於 docstore 的段數。

    Returns:
        {n_passages, n_batches, n_new_batches, resumed_from, seconds}
    """
    if batch_size < 1:
        raise ValueError(f"batch_size 必須 ≥ 1，收到 {batch_size}")
    ckpt_dir, t0 = Path(ckpt_dir), time.perf_counter()
    dim = int(ckpt_meta["dim"])
    with DocStore(db_path) as ds:
        n = ds.count_passages()
        if ckpt_meta["n_passages"] != n:
            raise ValueError(f"ckpt_meta.n_passages = {ckpt_meta['n_passages']}，docstore 有 {n} 段")
        _prepare_ckpt_dir(ckpt_dir, ckpt_meta)
        start = resumed_from = _scan_ckpt(ckpt_dir, dim, n, repair=True)
        if 0 < start < n:
            _log(f"[embed] 從 pid {start} 續跑（已完成 {start}/{n}）")
        n_new, last_log = 0, time.perf_counter()
        it = ds.iter_passages(start)
        while start < n:
            batch = [p for _, p in zip(range(batch_size), it)]
            end = start + len(batch)
            if not batch or batch[0].pid != start or batch[-1].pid != end - 1:
                raise ValueError(f"docstore 的 pid 不連續（預期 [{start}, {end})）")
            vecs = np.asarray(embeddings.embed_documents([p.text for p in batch]), dtype=np.float32)
            if vecs.shape != (len(batch), dim):
                raise ValueError(f"embedding 形狀 {vecs.shape}，預期 {(len(batch), dim)}（模型或 dim 不符？）")
            final = ckpt_dir / _ckpt_name(start, end)
            tmp = final.with_name(final.name + ".tmp")
            with open(tmp, "wb") as f:
                np.save(f, vecs)
            os.replace(tmp, final)
            start, n_new = end, n_new + 1
            if time.perf_counter() - last_log >= 10 or start == n:
                el = time.perf_counter() - t0
                rate = (start - resumed_from) / el if el > 0 else 0.0
                eta = (n - start) / rate if rate > 0 else 0.0
                _log(f"[embed] {start}/{n} 段（{rate:.1f} 段/秒，剩餘約 {eta / 60:.1f} 分鐘）")
                last_log = time.perf_counter()
    n_files = sum(1 for p in ckpt_dir.iterdir() if _CKPT_RE.match(p.name))
    return {"n_passages": n, "n_batches": n_files, "n_new_batches": n_new,
            "resumed_from": resumed_from, "seconds": time.perf_counter() - t0}


def is_embed_done(ckpt_dir, ckpt_meta: dict[str, Any]) -> bool:
    """checkpoint 設定相同且涵蓋全部 passage（給 build.py 的跳過判斷；不修改任何檔案）。"""
    ckpt_dir = Path(ckpt_dir)
    meta_path = ckpt_dir / CKPT_META
    if not meta_path.is_file():
        return False
    try:
        if json.loads(meta_path.read_text(encoding="utf-8")) != ckpt_meta:
            return False
    except (OSError, json.JSONDecodeError):
        return False
    n = ckpt_meta["n_passages"]
    return _scan_ckpt(ckpt_dir, int(ckpt_meta["dim"]), n, repair=False) == n


# ---------------------------------------------------------------- 組裝

def _check_ip(vs: FAISS, dim: int) -> None:
    if not isinstance(vs.index, faiss.IndexFlatIP):
        raise TypeError(f"向量索引是 {type(vs.index).__name__}，預期 IndexFlatIP（DistanceStrategy 匯入錯誤？）")
    if vs.index.d != dim:
        raise ValueError(f"向量維度 {vs.index.d} 與 config 的 dim {dim} 不一致")


def build_vectorstore(db_path, ckpt_dir, vectorstore_dir,
                      embeddings: PrefixedOllamaEmbeddings) -> dict[str, Any]:
    """從 checkpoint 逐批組裝 FAISS（第一批 from_embeddings，其餘 add_embeddings），存到 vectorstore_dir。

    先寫到 `<vectorstore_dir>.tmp/`，完成後才換成正式目錄（目錄存在 ⇔ 完整）；既有的正式目錄會被取代。

    Returns:
        {ntotal, n_batches, seconds}
    """
    ckpt_dir, vs_dir, t0 = Path(ckpt_dir), Path(vectorstore_dir), time.perf_counter()
    meta = json.loads((ckpt_dir / CKPT_META).read_text(encoding="utf-8"))
    dim = int(meta["dim"])
    with DocStore(db_path) as ds:
        n = ds.count_passages()
        if meta["n_passages"] != n:
            raise ValueError(f"checkpoint 的 n_passages = {meta['n_passages']}，docstore 有 {n} 段")
        if _scan_ckpt(ckpt_dir, dim, n, repair=False) != n:
            raise RuntimeError("embedding checkpoint 不完整，請先完成 embed 階段")
        files = sorted(p for p in ckpt_dir.iterdir() if _CKPT_RE.match(p.name))
        it, vs = ds.iter_passages(0), None
        for p in files:
            m = _CKPT_RE.match(p.name)
            start, end = int(m[1]), int(m[2])
            vecs = np.load(p)
            passages = [ps for _, ps in zip(range(end - start), it)]
            if [ps.pid for ps in passages] != list(range(start, end)):
                raise ValueError(f"{p.name} 與 docstore 的 pid 對不上")
            pairs = [(ps.text, v) for ps, v in zip(passages, vecs)]
            metas = [{"pid": ps.pid, "docid": ps.docid} for ps in passages]
            ids = [str(ps.pid) for ps in passages]
            if vs is None:
                vs = FAISS.from_embeddings(text_embeddings=pairs, embedding=embeddings, metadatas=metas,
                                           ids=ids, distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT)
                _check_ip(vs, dim)
            else:
                vs.add_embeddings(pairs, metadatas=metas, ids=ids)
            del vecs, passages, pairs, metas, ids
    if vs is None or vs.index.ntotal != n:
        raise ValueError(f"向量數 {0 if vs is None else vs.index.ntotal} ≠ passage 數 {n}")
    tmp = vs_dir.with_name(vs_dir.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    vs.save_local(str(tmp))
    if vs_dir.exists():
        shutil.rmtree(vs_dir)
    os.replace(tmp, vs_dir)
    return {"ntotal": vs.index.ntotal, "n_batches": len(files), "seconds": time.perf_counter() - t0}


# ---------------------------------------------------------------- 載入

def open_vectorstore(vectorstore_dir, build_meta_path, cfg: dict[str, Any] | None = None) -> FAISS:
    """建置完成檢查 → embed 設定比對 → load_local（查詢模式 embeddings、內積）→ IndexFlatIP / dim 檢查。

    Raises:
        BuildNotDoneError: build_meta 不存在或 status 不是 "done"。
        EmbedMismatchError: build_meta 的 embed 設定與 config 的 [embed] 不一致。
        FileNotFoundError: 向量庫檔案不存在。
    """
    cfg = cfg or get_config()
    meta = require_build_done(build_meta_path)
    e = cfg["embed"]
    diff = [f"{mk}: build={meta.get(mk)!r} config={e[ck]!r}"
            for mk, ck in _EMBED_FIELDS.items() if meta.get(mk) != e[ck]]
    if diff:
        raise EmbedMismatchError("向量庫的 embedding 設定與目前 config 不一致（" + "；".join(diff)
                                 + "）。請執行 `uv run python src/main.py build --force` 重建")
    vs_dir = Path(vectorstore_dir)
    if not (vs_dir / "index.faiss").is_file() or not (vs_dir / "index.pkl").is_file():
        raise FileNotFoundError(f"找不到向量庫 {vs_dir}（index.faiss / index.pkl），請重新執行 build")
    vs = FAISS.load_local(str(vs_dir), PrefixedOllamaEmbeddings.from_config("query", cfg),
                          allow_dangerous_deserialization=True,
                          distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT)   # load_local 不保存它
    _check_ip(vs, int(e["dim"]))
    return vs


def load_vectorstore(fixtures: bool) -> FAISS:
    """給 semantic（B）使用：`load_vectorstore(cfg["runtime"]["use_fixtures"])`。"""
    p = paths(fixtures)
    return open_vectorstore(p["vectorstore_dir"], p["build_meta"])
