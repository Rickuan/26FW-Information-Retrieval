"""t4_surface.test.py — T4c 資料層：surface_vocab.*（build_surface_vocab.py）與 surface.py 的讀取、meta 核對

執行（先建置一次）：
  uv run python HW2/src/build_surface_vocab.py
  uv run python HW2/tests/t4_surface.test.py

對應 T4.md §6.8.8 第 7 節「原字詞彙層與一致性」，另加 load_surface 的基本行為與計時。
一致性檢查在測試內直接讀 tsv 重新計算，不信任 meta 記錄的數字，也不經過 load_surface。
meta 竄改只在 tempfile 目錄進行（symlink 指向 HW2/index），不修改 HW2/index 本身。
"""
from __future__ import annotations

import csv
import json
import random
import statistics
import sys
import tempfile
import time
import tracemalloc
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
INDEX = ROOT / "index"
HW1_OUTPUT = ROOT.parent / "HW1" / "output"
sys.path.insert(0, str(SRC))

import surface
from build_surface_vocab import build_surface_vocab
from surface import load_surface, surface_stem
from tokenizer import Preprocessor, tokenize
from writer import IndexReader, _fingerprint

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

COUNT = 644_523
STOPWORDS = 189
SHOW = 10


def check(name: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))
    return condition


def run(name: str, fn) -> bool:
    """執行 fn() -> (condition, detail)；例外視為 FAIL，不中斷後續測試。"""
    try:
        cond, detail = fn()
    except Exception as e:  # noqa: BLE001
        return check(name, False, f"{type(e).__name__}: {e}")
    return check(name, cond, detail)


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def exceptions(items: list) -> tuple[bool, str]:
    return not items, f"例外 {len(items)} 個" + (f"，前 {SHOW} 個：{items[:SHOW]!r}" if items else "")


def raises(exc_type, fn, must_contain: tuple[str, ...] = ()) -> tuple[bool, str]:
    try:
        fn()
    except exc_type as e:
        msg = str(e)
        return all(s in msg for s in must_contain), f"{exc_type.__name__}: {msg}"
    except Exception as e:  # noqa: BLE001
        return False, f"拋出的是 {type(e).__name__}: {e}"
    return False, f"未拋出 {exc_type.__name__}"


reader = IndexReader(INDEX)
pre = Preprocessor.from_config(reader.get_metadata()["preprocessor"])
lexicon = reader._load_lexicon()
results: list[bool] = []
timings: list[str] = []

# 直接讀 tsv（不經過 load_surface）
with (INDEX / "surface_vocab.tsv").open("r", encoding="utf-8", newline="") as f:
    rows = list(csv.reader(f, delimiter="\t"))
header, body = rows[0], rows[1:]
words = [r[0] for r in body]
dfs = [int(r[1]) for r in body]
stems = [r[2] for r in body]
with (INDEX / "surface_vocab.meta.json").open("r", encoding="utf-8") as f:
    meta = json.load(f)

# ===========================================================================
section("1. surface_vocab.tsv 與 meta（§6.8.8 第 7 節）")
# ===========================================================================
results.append(run(f"表頭 + {COUNT} 列資料，每列 3 欄", lambda: (
    header == ["word", "df", "stem"] and len(body) == COUNT and all(len(r) == 3 for r in body),
    f"header={header}, rows={len(body)}")))
results.append(run("原字已排序且不重複", lambda: exceptions(
    [(words[i - 1], words[i]) for i in range(1, len(words)) if not words[i - 1] < words[i]])))
results.append(run(f"stem 是空字串的有 {STOPWORDS} 列", lambda: (
    stems.count("") == STOPWORDS, f"{stems.count('')} 列")))
results.append(run("stem 都不含空白或 tab", lambda: exceptions(
    [(w, s) for w, s in zip(words, stems) if any(c in s for c in " \t\r\n")])))


def _meta_fields():
    want = {"format": 1, "count": COUNT, "stopword_count": STOPWORDS, "N": reader.N,
            "preprocessor": reader.get_metadata()["preprocessor"],
            "stem_rule": "per-token: casefold → stopword → stem if isalpha (no tokenize)"}
    bad = {k: (meta.get(k), v) for k, v in want.items() if meta.get(k) != v}
    return not bad, f"不符：{bad}" if bad else "format、count、stopword_count、N、preprocessor、stem_rule 都正確"


def _meta_sources():
    got = meta.get("sources", {})
    want = {name: _fingerprint(INDEX / name) for name in ("lexicon.tsv", "metadata.json")}
    return got == want, f"lexicon.tsv {want['lexicon.tsv']['size']} bytes、sha256 {want['lexicon.tsv']['sha256'][:8]}…"


def _meta_consistency():
    c = meta.get("consistency", {})
    keys = ("stem_not_in_index", "index_term_without_word", "df_bound_violations")
    return all(c.get(k) == 0 for k in keys), f"consistency={c}"


results.append(run("meta 的 format／count／N／preprocessor 等欄位正確", _meta_fields))
results.append(run("meta 的 sources 與目前 HW2/index 的 fingerprint 相同", _meta_sources))
results.append(run("meta 記錄的一致性例外都是 0", _meta_consistency))


def _matches_hw1():
    """原字與 df 和 HW1/output/lexicon.tsv 的前兩欄完全相同（只讀）。"""
    with (HW1_OUTPUT / "lexicon.tsv").open("r", encoding="utf-8", newline="") as f:
        src = [(r[0], int(r[1])) for r in csv.reader(f, delimiter="\t")]
    return src == list(zip(words, dfs)), f"HW1 lexicon {len(src)} 列"


if (HW1_OUTPUT / "lexicon.tsv").exists():
    results.append(run("原字、df 與 HW1/output/lexicon.tsv 完全相同", _matches_hw1))
else:
    print("  [SKIP] 沒有 HW1/output/lexicon.tsv")

# ===========================================================================
section("2. 一致性（測試內重新算，不信任 meta）")
# ===========================================================================
by_stem: dict[str, list[int]] = defaultdict(list)
for d, s in zip(dfs, stems):
    if s:
        by_stem[s].append(d)

results.append(run("每個 stem 不是空字串的原字，stem 都 in reader", lambda: exceptions(
    [(w, s) for w, s in zip(words, stems) if s and s not in reader])))
results.append(run(f"reader.vocabulary() 的每個 term 都至少對應到一個原字（共 {len(lexicon)}）",
                   lambda: exceptions([t for t in reader.vocabulary() if t not in by_stem])))
results.append(run("max(原字 df) ≤ reader.df(stem) ≤ Σ 原字 df", lambda: exceptions(
    [(s, max(v), reader.df(s), sum(v)) for s, v in by_stem.items()
     if not max(v) <= reader.df(s) <= sum(v)])))


def _pre_agrees():
    """抽 5,000 個原字 + 全部 stopword；tokenize(w) == [w] 時，process 的結果要等於 stem 欄位。"""
    rng = random.Random(42)
    idx = set(rng.sample(range(len(words)), 5000)) | {i for i, s in enumerate(stems) if not s}
    bad, skipped = [], 0
    for i in sorted(idx):
        w, s = words[i], stems[i]
        if tokenize(w) != [w]:
            skipped += 1
            continue
        if [t for _, t in pre.process(w)] != ([s] if s else []):
            bad.append((w, s, pre.process(w)))
    ok, detail = exceptions(bad)
    return ok, f"檢查 {len(idx)} 個，tokenize 會改動而跳過 {skipped} 個；{detail}"


results.append(run("與 Preprocessor 一致（Random(42) 抽 5,000 個 + 189 個 stopword）", _pre_agrees))
results.append(run("surface_stem(pre, w) == (pre.normalize_token(w) or '')，含 stopword 與非字母", lambda: (
    all(surface_stem(pre, w) == (pre.normalize_token(w) or "")
        for w in ["the", "Retrieval", "computing", "e-mail", "10am", "café", "ID"]),
    f"the→{surface_stem(pre, 'the')!r}, Retrieval→{surface_stem(pre, 'Retrieval')!r}")))

# ===========================================================================
section("3. load_surface：讀取與查詢")
# ===========================================================================
sv = load_surface(reader)
results.append(run(f"len == {COUNT}，words／dfs／stems 與 tsv 相同", lambda: (
    len(sv) == COUNT and sv.words == words and list(sv.dfs) == dfs and sv.stems == stems,
    f"len={len(sv)}, dfs typecode={sv.dfs.typecode}")))
results.append(run("同一個 reader 第二次呼叫回傳同一個物件（快取）", lambda: (
    load_surface(reader) is sv, "")))
results.append(run("stem('retrieval') == 'retriev'，而且 'retriev' in reader", lambda: (
    sv.stem("retrieval") == "retriev" and "retriev" in reader, f"stem={sv.stem('retrieval')!r}")))
results.append(run("df('retrieval') == 81、df('retreival') == 1", lambda: (
    sv.df("retrieval") == 81 and sv.df("retreival") == 1,
    f"{sv.df('retrieval')}, {sv.df('retreival')}")))
results.append(run("stopword 的 stem 是 ''；不存在的原字 stem → None、df → 0", lambda: (
    sv.stem("the") == "" and sv.stem("zzqqxx-not-a-word") is None and sv.df("zzqqxx-not-a-word") == 0,
    f"stem('the')={sv.stem('the')!r}")))
results.append(run("stem_of_any：在詞彙中查表，不在時用 normalize_token 現算", lambda: (
    sv.stem_of_any("retrieval") == "retriev" and "computr" not in sv
    and sv.stem_of_any("computr") == pre.normalize_token("computr")
    and sv.stem_of_any("zzqqxx") == "zzqqxx",
    f"computr→{sv.stem_of_any('computr')!r}")))


def _interned():
    lex_keys = {id(t) for t in reader.vocabulary()}
    sample = random.Random(7).sample(range(len(sv.stems)), 2000)
    bad = [sv.stems[i] for i in sample if sv.stems[i] and id(sv.stems[i]) not in lex_keys]
    return not bad, f"抽 2,000 個，{len(bad)} 個沒有共用 lexicon 的字串物件"


results.append(run("stem 字串與 lexicon 的 key 是同一個物件（intern）", _interned))

# ===========================================================================
section("4. meta 核對（tempfile + symlink，不修改 HW2/index）")
# ===========================================================================
LINKED = ("lexicon.tsv", "metadata.json", "surface_vocab.tsv")


def tampered(edit=None, drop_meta: bool = False, drop_tsv: bool = False):
    """在 tempdir 建一份 index：symlink 指向 HW2/index，另放一份（改過的）meta，然後 load_surface。"""
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        for name in LINKED:
            if not (drop_tsv and name == "surface_vocab.tsv"):
                (d / name).symlink_to(INDEX / name)
        if not drop_meta:
            m = json.loads(json.dumps(meta))
            if edit:
                edit(m)
            (d / "surface_vocab.meta.json").write_text(json.dumps(m), encoding="utf-8")
        return load_surface(IndexReader(d))


def _set(path: tuple, value):
    def edit(m):
        cur = m
        for k in path[:-1]:
            cur = cur[k]
        cur[path[-1]] = value
    return edit


results.append(run("未竄改的 meta 可以載入（對照組）", lambda: (len(tampered()) == COUNT, "")))
results.append(run("sources.lexicon.tsv.sha256 改錯 → ValueError（訊息含 sha256）", lambda: raises(
    ValueError, lambda: tampered(_set(("sources", "lexicon.tsv", "sha256"), "0" * 64)),
    ("lexicon.tsv", "sha256"))))
results.append(run("sources.metadata.json.size 改錯 → ValueError", lambda: raises(
    ValueError, lambda: tampered(_set(("sources", "metadata.json", "size"), 1)), ("metadata.json", "size"))))
results.append(run("N 改錯 → ValueError（訊息含 N）", lambda: raises(
    ValueError, lambda: tampered(_set(("N",), 100)), ("N",))))
results.append(run("format 改成 2 → ValueError", lambda: raises(
    ValueError, lambda: tampered(_set(("format",), 2)), ("format",))))
results.append(run("preprocessor.stem 改成 False → ValueError", lambda: raises(
    ValueError, lambda: tampered(_set(("preprocessor", "stem"), False)), ("preprocessor",))))
results.append(run("count 改錯 → ValueError", lambda: raises(
    ValueError, lambda: tampered(_set(("count",), COUNT - 1)), ("count",))))
results.append(run("stopword_count 改錯 → ValueError", lambda: raises(
    ValueError, lambda: tampered(_set(("stopword_count",), 0)), ("stopword_count",))))
results.append(run("sources 缺 lexicon.tsv → ValueError", lambda: raises(
    ValueError, lambda: tampered(lambda m: m["sources"].pop("lexicon.tsv")), ("lexicon.tsv",))))
results.append(run("刪掉 meta → FileNotFoundError（訊息含 build_surface_vocab.py）", lambda: raises(
    FileNotFoundError, lambda: tampered(drop_meta=True), ("build_surface_vocab.py",))))
results.append(run("刪掉 tsv → FileNotFoundError", lambda: raises(
    FileNotFoundError, lambda: tampered(drop_tsv=True), ("surface_vocab.tsv",))))
results.append(run("竄改測試後，真正 index 的 load_surface 仍可用", lambda: (
    len(load_surface(IndexReader(INDEX))) == COUNT, "")))

# ===========================================================================
section("5. 建置腳本的來源檢查與重現性（輸出到 tempdir）")
# ===========================================================================


def _out_dir(d: Path) -> None:
    for name in ("lexicon.tsv", "metadata.json"):
        (d / name).symlink_to(INDEX / name)


def _wrong_source():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        _out_dir(d)
        before = sorted(p.name for p in d.iterdir())
        ok, detail = raises(ValueError, lambda: build_surface_vocab(INDEX, d), ("stem",))
        after = sorted(p.name for p in d.iterdir())
        return ok and before == after, f"{detail}；輸出目錄 {before} → {after}"


results.append(run("--hw1-dir 指向 HW2/index（stem=True）→ ValueError，不產生任何檔案", _wrong_source))


def _rebuild_same():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        _out_dir(d)
        build_surface_vocab(HW1_OUTPUT, d)
        same = _fingerprint(d / "surface_vocab.tsv") == _fingerprint(INDEX / "surface_vocab.tsv")
        names = sorted(p.name for p in d.iterdir())
        return same and not any(n.endswith(".tmp") for n in names), f"tempdir 內容 {names}"


if (HW1_OUTPUT / "lexicon.tsv").exists():
    results.append(run("重新建置到 tempdir：tsv 與 HW2/index 的 byte 相同，沒有殘留 .tmp", _rebuild_same))
else:
    print("  [SKIP] 沒有 HW1/output，略過重新建置")

# ===========================================================================
section("6. 計時（不設門檻）")
# ===========================================================================


def _load_fresh():
    r = IndexReader(INDEX)
    r.vocabulary()  # lexicon 的讀取不算在 load_surface 內
    t0 = time.perf_counter()
    load_surface(r)
    return time.perf_counter() - t0


ts = [_load_fresh() for _ in range(3)]
timings.append(f"load_surface（新的 reader；讀 tsv、核對 sha256、建 word→id）：{statistics.median(ts):.2f} s"
               f"（3 次中位數，各次 {', '.join(f'{t:.2f}' for t in ts)} s）")

r = IndexReader(INDEX)
r.vocabulary()
tracemalloc.start()
base = tracemalloc.get_traced_memory()[0]
sv2 = load_surface(r)
cur, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()
timings.append(f"load_surface 記憶體（tracemalloc，不含 lexicon）：建置後 {(cur - base) / 2**20:.1f} MiB，"
               f"峰值 {(peak - base) / 2**20:.1f} MiB")

t0 = time.perf_counter()
for w in words:
    pre.normalize_token(w)
timings.append(f"normalize_token × {len(words)}：{time.perf_counter() - t0:.2f} s")
timings.append(f"surface_vocab.tsv {(INDEX / 'surface_vocab.tsv').stat().st_size} bytes、"
               f"surface_vocab.meta.json {(INDEX / 'surface_vocab.meta.json').stat().st_size} bytes")
for line in timings:
    print(f"  {line}")

# ===========================================================================
section("Test Summary")
# ===========================================================================
all_passed = all(results)
print(f"\n  {sum(results)}/{len(results)} passed")
print(f"  Overall: {'ALL PASSED ✓' if all_passed else 'SOME FAILED ✗'}\n")
sys.exit(0 if all_passed else 1)
