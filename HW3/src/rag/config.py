"""讀取 HW3 設定（規格 1.3）。

- 讀 `HW3/config.toml`；若 `HW3/config.local.toml` 存在，以它逐鍵覆寫：
  表格（dict）遞迴合併，其他值（含陣列）整個取代。
- 覆寫檔不得包含 `[embed]`、`[paths]` 或 `[[inject.tokens]]`，否則 raise `ConfigError`。
- `[corpus]` 底下的路徑以 `HW3/` 為基準解析成絕對路徑（`pathlib.Path`），與目前的工作目錄無關。
- `[paths]` 在回傳的 dict 中保留 config.toml 的**相對路徑字串**（已驗證）；要取得絕對路徑，
  一律呼叫 `paths(fixtures)`：
  - `paths(False)`：`HW3/<相對路徑>`（正式產物）
  - `paths(True)`：`HW3/<fixtures_dir>/<相對路徑>`（fixtures，規格 2.8）
  兩套路徑都由同一份相對路徑計算，不會出現 `fixtures/fixtures/...`。
- `[runtime] use_fixtures`（只在 config.local.toml 設定，預設 false）：query 與 eval 讀到 true 時改用
  `paths(True)`；build 不讀它（有 `--limit` 時用 `paths(True)`，沒有時用 `paths(False)`）。
- `require_build_done(build_meta_path)`：lexical、semantic、eval 啟動時以 `paths(...)["build_meta"]`
  呼叫，建置未完成就 raise。
"""
from __future__ import annotations

import copy
import json
import os
import tomllib
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

HW3_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = HW3_ROOT / "config.toml"
LOCAL_CONFIG_PATH = HW3_ROOT / "config.local.toml"


class ConfigError(ValueError):
    """設定檔內容不合法。"""


class BuildNotDoneError(RuntimeError):
    """建置產物不存在或建置未完成，不能查詢。"""


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """回傳 base 被 override 逐鍵覆寫後的新 dict：兩邊都是 dict 時遞迴，否則整個取代。"""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _check_local(local: dict[str, Any], local_path: Path) -> None:
    """覆寫檔不得修改會影響共用產物或產物位置的設定（規格 1.3）。"""
    errors = []
    if "embed" in local:
        errors.append("[embed]（embedding 模型、前綴、維度必須與他人一致，否則向量不相容）")
    if "paths" in local:
        errors.append("[paths]（要改用 fixtures，請設定 [runtime] use_fixtures = true）")
    inject = local.get("inject")
    if isinstance(inject, dict) and "tokens" in inject:
        errors.append("[[inject.tokens]]（埋入設定的唯一來源是 config.toml，否則語料與 gold_docids 會不一致）")
    if errors:
        raise ConfigError(f"{local_path} 不得覆寫：" + "；".join(errors))


def _abs(root: Path, rel: str) -> Path:
    # normpath 而不是 resolve()：不跟隨 symlink（dataset/04.warc 可能是 symlink），讓路徑維持在 HW3/ 底下
    return Path(os.path.normpath(root / rel))


def _resolve_corpus(cfg: dict[str, Any]) -> None:
    table = cfg.get("corpus")
    if not isinstance(table, dict):
        raise ConfigError("config 缺少 [corpus] 表格")
    for key, value in table.items():
        if not isinstance(value, str):
            raise ConfigError(f"[corpus].{key} 必須是路徑字串，實際為 {value!r}")
        table[key] = _abs(HW3_ROOT, value)


def _check_paths(cfg: dict[str, Any]) -> None:
    """[paths] 必須是 HW3/ 底下的相對路徑；fixtures_dir 以外的路徑不得位於 fixtures_dir 之內。"""
    table = cfg.get("paths")
    if not isinstance(table, dict):
        raise ConfigError("config 缺少 [paths] 表格")
    if "fixtures_dir" not in table:
        raise ConfigError("[paths] 缺少 fixtures_dir")
    norm: dict[str, PurePosixPath] = {}
    for key, value in table.items():
        if not isinstance(value, str) or not value:
            raise ConfigError(f"[paths].{key} 必須是非空的路徑字串，實際為 {value!r}")
        p = PurePosixPath(os.path.normpath(value))
        if p.is_absolute() or p.parts[0] == ".." or str(p) == ".":
            raise ConfigError(f"[paths].{key} = {value!r} 必須是 HW3/ 底下的相對路徑")
        norm[key] = p
    fx = norm["fixtures_dir"]
    for key, p in norm.items():
        if key != "fixtures_dir" and (p == fx or fx in p.parents):
            raise ConfigError(
                f"[paths].{key} = {table[key]!r} 位於 fixtures_dir 之內；"
                "fixtures 路徑由 paths(True) 自動計算，[paths] 只寫正式產物的位置"
            )


def _check_runtime(cfg: dict[str, Any]) -> None:
    runtime = cfg.setdefault("runtime", {})
    if not isinstance(runtime, dict):
        raise ConfigError("[runtime] 必須是表格")
    runtime.setdefault("use_fixtures", False)
    if not isinstance(runtime["use_fixtures"], bool):
        raise ConfigError(f"[runtime].use_fixtures 必須是 true / false，實際為 {runtime['use_fixtures']!r}")


def load_config(
    config_path: Path | str = CONFIG_PATH,
    local_path: Path | str | None = LOCAL_CONFIG_PATH,
) -> dict[str, Any]:
    """讀取並合併設定，回傳新的 dict（呼叫端可自由修改）。

    Args:
        config_path: 主設定檔。
        local_path: 本機覆寫檔；None 或檔案不存在時不覆寫。
    """
    with Path(config_path).open("rb") as f:
        cfg = tomllib.load(f)
    if local_path is not None and Path(local_path).is_file():
        with Path(local_path).open("rb") as f:
            local = tomllib.load(f)
        _check_local(local, Path(local_path))
        cfg = _merge(cfg, local)
    _resolve_corpus(cfg)
    _check_paths(cfg)
    _check_runtime(cfg)
    return cfg


@lru_cache(maxsize=1)
def _cached() -> dict[str, Any]:
    return load_config()


def get_config() -> dict[str, Any]:
    """預設設定（HW3/config.toml + config.local.toml），整個 process 只讀一次；回傳深複本。"""
    return copy.deepcopy(_cached())


def paths(fixtures: bool, cfg: dict[str, Any] | None = None) -> dict[str, Path]:
    """由 config.toml 的 [paths] 相對路徑計算絕對路徑。

    Args:
        fixtures: False → `HW3/<rel>`；True → `HW3/<fixtures_dir>/<rel>`。
            `fixtures_dir` 本身兩種模式都是 `HW3/<fixtures_dir>`。
        cfg: 已載入的設定；None 時使用 get_config()。

    Returns:
        {key: 絕對 Path}，key 與 [paths] 相同。
    """
    if cfg is None:
        cfg = get_config()
    rel = cfg["paths"]
    fixtures_root = _abs(HW3_ROOT, rel["fixtures_dir"])
    base = fixtures_root if fixtures else HW3_ROOT
    out = {key: _abs(base, value) for key, value in rel.items() if key != "fixtures_dir"}
    out["fixtures_dir"] = fixtures_root
    return out


def require_build_done(build_meta_path: Path | str) -> dict[str, Any]:
    """確認 build_meta 檔案存在且 status == "done"，回傳 build_meta 內容。

    lexical、semantic、eval 啟動時必須呼叫（規格 2.6、3.3、3.5）。

    Args:
        build_meta_path: build_meta 檔案的路徑，呼叫端傳入 `paths(...)["build_meta"]`。

    Raises:
        BuildNotDoneError: build_meta 不存在、無法解析，或 status 不是 "done"。
    """
    meta_path = Path(build_meta_path)
    hint = "請先執行 `uv run python src/main.py build`（fixtures 用 `build --limit N`）"
    if not meta_path.is_file():
        raise BuildNotDoneError(f"找不到 {meta_path}：尚未建置。{hint}")
    try:
        with meta_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise BuildNotDoneError(f"無法讀取 {meta_path}（{e}）。{hint}") from e
    status = meta.get("status") if isinstance(meta, dict) else None
    if status == "in_progress":
        raise BuildNotDoneError(f"{meta_path}: 上次建置未完成（status = \"in_progress\"）。{hint}，從中斷處繼續")
    if status != "done":
        raise BuildNotDoneError(f"{meta_path}: status = {status!r}，不是 \"done\"。{hint}")
    return meta
