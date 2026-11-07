"""T4c：建置原字詞彙層 surface_vocab.tsv 與 surface_vocab.meta.json（T4.md §6.8.1）。

執行：uv run python HW2/src/build_surface_vocab.py [--hw1-dir DIR] [--index-dir DIR] [--allow-mismatch]
  預設 --hw1-dir 是 HW1/output（未 stem 的 index，只讀），--index-dir 是 HW2/index。
  只會在 index-dir 新增 surface_vocab.tsv 與 surface_vocab.meta.json，不修改其他檔案；
  絕對不把 HW1/output 的檔案複製進 HW2/index（兩邊檔名相同）。

步驟：
  1. 檢查來源（N、preprocessor、vocab_size、lexicon 已排序），不符就拋 ValueError，不寫任何檔案
  2. 讀 HW1 lexicon.tsv 的原字與 df
  3. 用 surface.surface_stem（= Preprocessor.normalize_token）逐字算 stem，不經過 tokenize
  4. 一致性檢查；有例外時預設拋 ValueError（--allow-mismatch 才照樣輸出）
  5. 先寫 *.tmp，再 os.replace：先 tsv、最後 meta，所以 meta 存在就代表 tsv 完整
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import resource
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from surface import FORMAT, HEADER, META_NAME, SOURCES, STEM_RULE, TSV_NAME, surface_stem
from tokenizer import Preprocessor
from writer import IndexReader, _fingerprint

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HW1_DIR = ROOT / "HW1" / "output"
DEFAULT_INDEX_DIR = ROOT / "HW2" / "index"
SHOW = 20


def _display(path: Path) -> str:
    """meta 中記錄的路徑：在 repo 內就寫相對路徑。"""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _read_lexicon(path: Path) -> tuple[list[str], list[int]]:
    """讀 lexicon.tsv 的前兩欄（原字、df）。"""
    words: list[str] = []
    dfs: list[int] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.reader(f, delimiter="\t"):
            if len(row) != 4:
                raise ValueError(f"{path}: line {len(words) + 1} has {len(row)} columns, expected 4")
            words.append(row[0])
            dfs.append(int(row[1]))
    return words, dfs


def check_sources(hw1_meta: dict, index_meta: dict, words: list[str]) -> None:
    """來源檢查（§6.8.1 第 1 步）。任何一項不符就拋 ValueError。"""
    errors = []
    if hw1_meta.get("N") != index_meta.get("N"):
        errors.append(f"N is {hw1_meta.get('N')!r}, index N is {index_meta.get('N')!r}")
    hp = hw1_meta.get("preprocessor") or {}
    ip = index_meta.get("preprocessor") or {}
    if hp.get("casefold") != ip.get("casefold"):
        errors.append(f"preprocessor.casefold is {hp.get('casefold')!r}, index has {ip.get('casefold')!r}")
    for key in ("stopword", "stem"):
        if hp.get(key) is not False:
            errors.append(f"preprocessor.{key} is {hp.get(key)!r}, expected False")
    if hp.get("lemma", False) is not False:
        errors.append(f"preprocessor.lemma is {hp.get('lemma')!r}, expected absent or False")
    if hw1_meta.get("vocab_size") != len(words):
        errors.append(f"vocab_size is {hw1_meta.get('vocab_size')!r}, lexicon has {len(words)} rows")
    unsorted = next((i for i in range(1, len(words)) if not words[i - 1] < words[i]), None)
    if unsorted is not None:
        errors.append(f"lexicon.tsv is not sorted at line {unsorted + 1}: "
                      f"{words[unsorted - 1]!r} >= {words[unsorted]!r}")
    if errors:
        raise ValueError("hw1-dir is not the unstemmed HW1 index: " + "; ".join(errors))


def consistency(words: list[str], dfs: list[int], stems: list[str],
                lexicon: dict[str, tuple[int, int, int]], pre: Preprocessor) -> dict[str, list]:
    """一致性檢查（§6.8.1 第 4 步）。回傳每一項的例外 list（空 list 代表 0 個）。"""
    max_df: dict[str, int] = {}
    sum_df: dict[str, int] = defaultdict(int)
    stem_not_in_index = []
    for w, d, s in zip(words, dfs, stems):
        if not s:
            continue
        if s not in lexicon:
            stem_not_in_index.append((w, s))
        if d > max_df.get(s, 0):
            max_df[s] = d
        sum_df[s] += d
    index_term_without_word = [t for t in lexicon if t not in max_df]
    df_bound_violations = [
        (s, max_df[s], lexicon[s][0], sum_df[s])
        for s in max_df if s in lexicon and not (max_df[s] <= lexicon[s][0] <= sum_df[s])
    ]
    # 補充：stopword 列（stem 為空）用 process 也應該得到 []
    stopword_process_mismatch = [w for w, s in zip(words, stems) if not s and pre.process(w)]
    return {
        "stem_not_in_index": stem_not_in_index,
        "index_term_without_word": index_term_without_word,
        "df_bound_violations": df_bound_violations,
        "stopword_process_mismatch": stopword_process_mismatch,
    }


def _write_tmp_tsv(path: Path, words: list[str], dfs: list[int], stems: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(HEADER)
        w.writerows(zip(words, dfs, stems))


def build_surface_vocab(hw1_dir: str | Path = DEFAULT_HW1_DIR, index_dir: str | Path = DEFAULT_INDEX_DIR,
                        allow_mismatch: bool = False) -> dict:
    """建置 surface_vocab.*，回傳寫出的 meta。失敗時不寫任何檔案。"""
    hw1_dir, index_dir = Path(hw1_dir), Path(index_dir)
    t0 = time.perf_counter()

    # 1. 來源檢查（任何檔案寫出之前）
    hw1_meta = _read_json(hw1_dir / "metadata.json")
    reader = IndexReader(index_dir)
    index_meta = reader.get_metadata()
    words, dfs = _read_lexicon(hw1_dir / "lexicon.tsv")
    check_sources(hw1_meta, index_meta, words)
    t_read = time.perf_counter() - t0

    # 3. 逐 token 規則算 stem（只呼叫 Preprocessor 自己的程式）
    pre = Preprocessor.from_config(index_meta["preprocessor"])
    t1 = time.perf_counter()
    stems = [surface_stem(pre, w) for w in words]
    t_stem = time.perf_counter() - t1
    bad = [(w, s) for w, s in zip(words, stems) if any(c in s for c in " \t\r\n")]
    if bad:
        raise ValueError(f"{len(bad)} stems contain whitespace, e.g. {bad[:SHOW]!r}")

    # 4. 一致性檢查
    t2 = time.perf_counter()
    lexicon = reader._load_lexicon()
    found = consistency(words, dfs, stems, lexicon, pre)
    t_check = time.perf_counter() - t2
    counts = {k: len(v) for k, v in found.items()}
    if any(counts.values()):
        for k, v in found.items():
            if v:
                print(f"{k}: {len(v)}; first {SHOW}: {v[:SHOW]!r}", file=sys.stderr)
        if not allow_mismatch:
            raise ValueError(f"consistency check failed: {counts} (use --allow-mismatch to write anyway)")

    # 5. 輸出：先 *.tmp，再 os.replace（先 tsv，最後 meta）
    tsv_path, meta_path = index_dir / TSV_NAME, index_dir / META_NAME
    tsv_tmp, meta_tmp = tsv_path.with_name(TSV_NAME + ".tmp"), meta_path.with_name(META_NAME + ".tmp")
    meta = {
        "format": FORMAT,
        "count": len(words),
        "stopword_count": stems.count(""),
        "N": index_meta["N"],
        "preprocessor": index_meta["preprocessor"],
        "stem_rule": STEM_RULE,
        "origin": {
            "dir": _display(hw1_dir),
            "N": hw1_meta["N"],
            "vocab_size": hw1_meta["vocab_size"],
            "preprocessor": hw1_meta["preprocessor"],
            "lexicon.tsv": _fingerprint(hw1_dir / "lexicon.tsv"),
            "metadata.json": _fingerprint(hw1_dir / "metadata.json"),
        },
        "sources": {name: _fingerprint(index_dir / name) for name in SOURCES},
        "consistency": counts,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _write_tmp_tsv(tsv_tmp, words, dfs, stems)
        with meta_tmp.open("w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
            f.write("\n")
        # 舊的 meta 先移除，避免換 tsv 與換 meta 之間出現「新 tsv + 舊 meta」
        meta_path.unlink(missing_ok=True)
        os.replace(tsv_tmp, tsv_path)
        os.replace(meta_tmp, meta_path)
    finally:
        tsv_tmp.unlink(missing_ok=True)
        meta_tmp.unlink(missing_ok=True)

    elapsed = time.perf_counter() - t0
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Linux: KB
    print(f"build_surface_vocab: {elapsed:.2f} s total (read+check sources {t_read:.2f} s, "
          f"normalize_token × {len(words)} {t_stem:.2f} s, consistency {t_check:.2f} s), "
          f"peak RSS {peak_mb:.1f} MB")
    print(f"  {TSV_NAME}: {tsv_path.stat().st_size} bytes, {meta['count']} words, "
          f"{meta['stopword_count']} stopwords; consistency {counts}")
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build the surface (unstemmed) vocabulary layer.")
    ap.add_argument("--hw1-dir", default=str(DEFAULT_HW1_DIR), help="unstemmed HW1 index (read only)")
    ap.add_argument("--index-dir", default=str(DEFAULT_INDEX_DIR), help="HW2 index (output)")
    ap.add_argument("--allow-mismatch", action="store_true",
                    help="write output even if the consistency check finds exceptions")
    args = ap.parse_args()
    build_surface_vocab(args.hw1_dir, args.index_dir, args.allow_mismatch)
