"""一鍵重建所有建置期產物：`main.py build`（規格 2.8，A4）。

階段依序為 index → norms → docstore → embed → vectorstore，前後寫入 build_meta
（開始時 status = "in_progress"，全部完成後改為 "done"）。

- 目標資料夾：沒有 `--limit` 時為 `paths(False)`；有 `--limit N` 時為 `paths(True)`（fixtures）。
  build 不讀 `[runtime] use_fixtures`。
- build_meta 存在時先與目前的 config / `--limit` 比對，不一致就停止並提示 `--force`；
  build_meta 不存在但目標中已有產物時也停止（不沿用來源不明的產物）。
- 跳過規則與連帶重建見 `_run_stages`；docid 連續性檢查每次建置都執行。
- 進度與耗時只寫 stderr；stdout 不輸出。
- exit code：0 完成；1 階段執行失敗；2 前置條件不符；130 Ctrl-C（build_meta 保持 in_progress）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from rag import hw_bridge
from rag.config import HW3_ROOT, get_config, paths
from rag.docstore import DocStore, build_docstore
from rag.embed import PrefixedOllamaEmbeddings
from rag.vectorstore import build_vectorstore, ckpt_meta_from_config, embed_passages, is_embed_done

HELP = "一鍵重建詞彙索引、docstore、embedding 與向量庫（--limit N 時輸出到 fixtures）"
LIMIT_EXAMPLE = "範例：uv run python src/main.py build --limit 200（fixtures：語料前 200 篇）"
STAGES = ("index", "norms", "docstore", "embed", "vectorstore")
# 這次建置的目標（--force 只刪除這些路徑與它們的 .tmp）
TARGET_KEYS = ("index_dir", "docstore", "vectorstore_dir", "embed_ckpt_dir", "build_meta")
FORCE_HINT = "加上 --force 清空這次建置的目標後重建"


class BuildPreconditionError(RuntimeError):
    """前置條件不符（exit 2）：輸入不存在、limit 不合法、build_meta 不一致等。"""


class BuildMismatchError(BuildPreconditionError):
    """既有 build_meta 與目前的 config / --limit 不一致。"""


class UnmanagedArtifactsError(BuildPreconditionError):
    """目標中已有產物，但沒有 build_meta（來源不明）。"""


def _log(msg: str) -> None:
    print(f"[build] {msg}", file=sys.stderr, flush=True)


def _rel(path: Path) -> str:
    try:
        return str(Path(path).relative_to(HW3_ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------- build_meta

def expected_meta(cfg: dict[str, Any], limit: int | None) -> dict[str, Any]:
    """build_meta 中 status 以外的欄位（規格 1.4），由目前的 config 與 --limit 產生。"""
    e, r = cfg["embed"], cfg["retrieval"]
    return {
        "embed_model": e["model"], "query_prefix": e["query_prefix"], "doc_prefix": e["doc_prefix"],
        "dim": e["dim"], "passage_words": r["passage_words"], "passage_stride": r["passage_stride"],
        "limit": limit, "inject_tokens": list(cfg.get("inject", {}).get("tokens", [])),
    }


def _write_meta(meta_path: Path, expected: dict[str, Any], status: str) -> None:
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = meta_path.with_name(meta_path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump({"status": status, **expected}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, meta_path)


def _check_meta(meta_path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    """比對既有 build_meta 的 8 個欄位；不一致 raise BuildMismatchError，回傳既有內容。"""
    try:
        old = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(old, dict):
            raise ValueError("不是 JSON 物件")
    except (OSError, ValueError) as e:
        raise BuildMismatchError(f"無法解析 {_rel(meta_path)}（{e}）；{FORCE_HINT}") from e
    diff = [f"  {k}: build_meta={old.get(k)!r} 目前={v!r}" for k, v in expected.items() if old.get(k) != v]
    if diff:
        scope = "（有 --limit，只會清空 fixtures 的產物）" if expected["limit"] is not None else ""
        raise BuildMismatchError(f"{_rel(meta_path)} 與目前的設定不一致：\n" + "\n".join(diff)
                                 + f"\n{FORCE_HINT}{scope}")
    return old


# ---------------------------------------------------------------- 目標與 --force

def _target_paths(p: dict[str, Path]) -> list[Path]:
    out: list[Path] = []
    for key in TARGET_KEYS:
        out.append(p[key])
        if key != "index_dir":
            out.append(p[key].with_name(p[key].name + ".tmp"))
    return out


def _check_safe(targets: list[Path], fixtures_root: Path, fixtures: bool) -> None:
    """刪除前的防呆：位於 HW3/ 之內；fixtures 建置只能在 fixtures_dir 內，正式建置不得在其內。"""
    for t in targets:
        if t == HW3_ROOT or HW3_ROOT not in t.parents:
            raise RuntimeError(f"拒絕刪除 HW3/ 以外的路徑：{t}")
        inside = fixtures_root in t.parents
        if inside != fixtures:
            raise RuntimeError(f"拒絕刪除 {_rel(t)}：與這次建置的目標（{'fixtures' if fixtures else '正式'}）不符")


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


# ---------------------------------------------------------------- 階段

def _index_complete(index_dir: Path) -> bool:
    """metadata.json 由 hwlib 最後寫入：存在且可解析 ⇒ index 階段完成（norms 的 sha256 再確認內容）。"""
    try:
        return isinstance(json.loads((index_dir / "metadata.json").read_text(encoding="utf-8")), dict)
    except (OSError, ValueError):
        return False


def _run_stages(cfg: dict[str, Any], p: dict[str, Path], limit: int | None,
                report: dict[str, dict[str, Any]]) -> None:
    warc = cfg["corpus"]["injected_warc"]
    index_dir, db_path = p["index_dir"], p["docstore"]
    ckpt_dir, vs_dir = p["embed_ckpt_dir"], p["vectorstore_dir"]

    def stage(name: str, skip_reason: str | None, fn) -> bool:
        """skip_reason 不是 None 就跳過；回傳是否執行。"""
        t0 = time.perf_counter()
        if skip_reason is not None:
            _log(f"{name}: skip（{skip_reason}）")
            report[name] = {"action": "skip", "seconds": time.perf_counter() - t0}
            return False
        _log(f"{name}: run")
        detail = fn()
        report[name] = {"action": "run", "seconds": time.perf_counter() - t0}
        _log(f"{name}: done {report[name]['seconds']:.1f} s" + (f"  {detail}" if detail else ""))
        return True

    # index：metadata.json 不完整就整個資料夾重建
    def do_index():
        if index_dir.exists():
            shutil.rmtree(index_dir)
        return hw_bridge.build_lexical_index(warc, index_dir, limit)
    index_ran = stage("index", "metadata.json 已存在" if _index_complete(index_dir) else None, do_index)
    hw_bridge.check_docid_contiguous(index_dir)          # 每次建置都檢查（規格 2.3）
    _log("docid 連續性檢查通過")

    # norms：index 未重建且 Ranker 載入成功（preprocessor、sha256、N 檢查）就跳過
    norms_skip = None
    if not index_ran:
        try:
            ranker = hw_bridge.load_ranker(index_dir)
            norms_skip = f"Ranker 載入檢查通過，N = {ranker.N}"
        except (FileNotFoundError, ValueError) as e:
            _log(f"norms: 需要重建（{e}）")

    def do_norms():
        hw_bridge.build_doc_norms(index_dir)
        return f"N = {hw_bridge.load_ranker(index_dir).N}"
    stage("norms", norms_skip, do_norms)

    # docstore：index 重建時一併重建（寫入後會與新的 doc_map 比對）
    def do_docstore():
        db_path.unlink(missing_ok=True)
        r = cfg["retrieval"]
        return build_docstore(warc, db_path, limit, doc_map_path=index_dir / "doc_map.json",
                              passage_words=r["passage_words"], passage_stride=r["passage_stride"])
    docstore_skip = None if index_ran or not db_path.is_file() else "docstore 已存在"
    docstore_ran = stage("docstore", docstore_skip, do_docstore)

    # embed：checkpoint 設定相同且涵蓋全部 pid 就跳過；否則續跑
    with DocStore(db_path) as ds:
        n_passages = ds.count_passages()
    ckpt_meta = ckpt_meta_from_config(cfg, limit=limit, n_passages=n_passages)
    emb = PrefixedOllamaEmbeddings.from_config("build", cfg)
    embed_skip = f"checkpoint 涵蓋全部 {n_passages} 段" if is_embed_done(ckpt_dir, ckpt_meta) else None
    embed_ran = stage("embed", embed_skip, lambda: embed_passages(
        db_path, ckpt_dir, emb, batch_size=cfg["embed"]["batch_size"], ckpt_meta=ckpt_meta))

    # vectorstore：上游有執行就重組；目錄存在 ⇔ 完整（原子寫入）
    vs_skip = None if docstore_ran or embed_ran or not vs_dir.is_dir() else "向量庫已存在"
    stage("vectorstore", vs_skip, lambda: build_vectorstore(db_path, ckpt_dir, vs_dir, emb))


# ---------------------------------------------------------------- 對外介面

def build(limit: int | None, force: bool, cfg: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """執行建置；回傳 {階段: {"action": "run"/"skip", "seconds": float}}。

    Raises:
        BuildPreconditionError（含 BuildMismatchError、UnmanagedArtifactsError）：前置條件不符。
    """
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
        raise BuildPreconditionError(f"--limit 必須是 ≥ 1 的整數，收到 {limit!r}。{LIMIT_EXAMPLE}")
    cfg = cfg if cfg is not None else get_config()
    fixtures = limit is not None
    p = paths(fixtures, cfg)
    warc = Path(cfg["corpus"]["injected_warc"])
    meta_path = p["build_meta"]
    targets = _target_paths(p)
    expected = expected_meta(cfg, limit)
    t_start = time.perf_counter()

    _log(f"目標：{'fixtures（limit = ' + str(limit) + '）' if fixtures else '正式產物（全量）'}；"
         + "、".join(_rel(p[k]) for k in TARGET_KEYS))
    if not warc.is_file():
        raise BuildPreconditionError(f"找不到輸入 {_rel(warc)}；請先執行 `uv run python tools/inject_warc.py`")

    if force:
        _check_safe(targets, p["fixtures_dir"], fixtures)
        existing = [t for t in targets if t.exists() or t.is_symlink()]
        for t in existing:
            _remove(t)
        _log("--force：已清空 " + ("、".join(_rel(t) for t in existing) if existing else "（目標皆不存在）"))
    elif meta_path.is_file():
        old = _check_meta(meta_path, expected)
        if old.get("status") == "in_progress":
            _log("上次建置未完成（status = in_progress），這次從中斷處繼續")
    else:
        existing = [t for t in targets if t.exists()]
        if existing:
            raise UnmanagedArtifactsError(
                f"{_rel(meta_path)} 不存在，但目標中已有產物（來源不明）：" + "、".join(_rel(t) for t in existing)
                + f"\n{FORCE_HINT}")

    _write_meta(meta_path, expected, "in_progress")
    report: dict[str, dict[str, Any]] = {}
    _run_stages(cfg, p, limit, report)
    _write_meta(meta_path, expected, "done")

    total = time.perf_counter() - t_start
    _log("完成（build_meta status = done）。各階段耗時：")
    for name in STAGES:
        r = report[name]
        _log(f"  {name:<12}{r['action']:<6}{r['seconds']:9.1f} s")
    _log(f"  {'total':<18}{total:9.1f} s")
    return report


def _limit_arg(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"必須是 ≥ 1 的整數，收到 {value!r}") from None
    if n < 1:
        raise argparse.ArgumentTypeError(f"必須是 ≥ 1 的整數，收到 {n}")
    return n


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--limit", type=_limit_arg, metavar="N",
                        help="只處理語料前 N 篇，輸出到 fixtures（必須寫出數字，例如 --limit 200）")
    parser.add_argument("--force", action="store_true",
                        help="清空這次建置的目標（有 --limit 時只清 fixtures）後全部重建")
    parser.epilog = LIMIT_EXAMPLE + "；全量：uv run python src/main.py build"


def run(args: argparse.Namespace) -> int:
    try:
        build(args.limit, args.force)
    except BuildPreconditionError as e:
        _log(f"錯誤：{e}")
        return 2
    except KeyboardInterrupt:
        _log("已中斷；build_meta 保持 status = in_progress，重新執行同一指令即可從中斷處繼續")
        return 130
    except Exception:
        traceback.print_exc(file=sys.stderr)
        _log("建置失敗（見上方訊息）；修正後重新執行同一指令即可繼續")
        return 1
    return 0
