"""t2_bonus.test.py — T2 加分：SMART 權重方案與 champion list

執行（需先跑過核心的 build_norms.py 與 build_champions.py）：
  uv run python HW2/src/build_norms.py --index-dir HW2/index
  uv run python HW2/src/build_champions.py --index-dir HW2/index --r 50
  uv run python HW2/tests/t2_bonus.test.py

SMART 的 lnc／ltc 建置在暫存目錄（symlink 指向真實 index 來源檔）進行，不會在 HW2/index 新增檔案。
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

# 確保可以 import HW2/src 的模組
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
INDEX = ROOT / "index"
sys.path.insert(0, str(SRC))

from build_norms import build_norms
from weighting import FORMULA, formula, weight
from writer import IndexReader

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

N = 34786
EMPTY_DOC = 24621


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


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def raises(exc, fn):
    try:
        fn()
    except exc as e:
        return True, f"{exc.__name__}: {e}"
    return False, f"未拋出 {exc.__name__}"


def make_tmp_index() -> Path:
    """暫存目錄：symlink 指向真實 index 的來源檔。"""
    tmp = Path(tempfile.mkdtemp(prefix="t2b_idx_"))
    for name in ("lexicon.tsv", "postings.bin", "metadata.json", "postings.txt"):
        (tmp / name).symlink_to((INDEX / name).resolve())
    return tmp


results: list[bool] = []

# ===========================================================================
section("SMART weight() 手算值（df = 997, tf = 10）")
# ===========================================================================
def _close(got: float, want: float, tol: float = 1e-12):
    return abs(got - want) < tol, f"got={got!r}, want={want!r}"


results.append(run("ltc → 3.0854186686", lambda: _close(weight(10, 997, N, "ltc"), 3.0854186686, 1e-9)))
results.append(run("lnc → 2.0", lambda: _close(weight(10, 997, N, "lnc"), 2.0)))
results.append(run("ntc → 15.427093343", lambda: _close(weight(10, 997, N, "ntc"), 15.427093343, 1e-8)))
results.append(run("bnn → 1.0", lambda: _close(weight(10, 997, N, "bnn"), 1.0)))
results.append(run("weight(0, 997, N, 'bnn') == 0.0", lambda: _close(weight(0, 997, N, "bnn"), 0.0)))
results.append(run("weight(1, 0, N, 'lnc') == 0.0", lambda: _close(weight(1, 0, N, "lnc"), 0.0)))

CORE_CASES = [(1, 997), (10, 997), (0, 997), (1, 0), (1, N)]
results.append(run(
    "核心 5 組：weight(..., 'ltc') == weight(...)（預設）",
    lambda: (all(weight(tf, df, N, "ltc") == weight(tf, df, N) for tf, df in CORE_CASES), ""),
))

for s in ("xyz", "lt", "ltx", "lnc.ltc", "ltcc", ""):
    results.append(run(f"weight(1, 997, N, {s!r}) 拋出 ValueError",
                       lambda s=s: raises(ValueError, lambda: weight(1, 997, N, s))))
results.append(run("weight(0, 997, N, 'xyz') 拋出 ValueError",
                   lambda: raises(ValueError, lambda: weight(0, 997, N, "xyz"))))

# ===========================================================================
section("formula()")
# ===========================================================================
results.append(run("formula('ltc') == FORMULA", lambda: (formula("ltc") == FORMULA, formula("ltc"))))
results.append(run("formula('lnc') == '(1+log10 tf)*1'",
                   lambda: (formula("lnc") == "(1+log10 tf)*1", formula("lnc"))))
results.append(run("formula('bnn') == '1*1'", lambda: (formula("bnn") == "1*1", formula("bnn"))))

# ===========================================================================
section("build_norms：預設 vs --scheme ltc vs 核心檔案")
# ===========================================================================
core_sha = sha256_of(INDEX / "doc_norms.bin")


def _build_equivalence():
    tmp = make_tmp_index()
    try:
        build_norms(tmp, "ltc")
        sha_default = sha256_of(tmp / "doc_norms.bin")
        (tmp / "doc_norms.bin").unlink()
        subprocess.run([sys.executable, str(SRC / "build_norms.py"), "--index-dir", str(tmp),
                        "--scheme", "ltc"], check=True, capture_output=True)
        sha_cli = sha256_of(tmp / "doc_norms.bin")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ok = sha_default == sha_cli == core_sha
    return ok, f"api={sha_default[:12]} cli={sha_cli[:12]} core={core_sha[:12]}"


results.append(run("API 預設、CLI --scheme ltc、核心檔案的 sha256 相同", _build_equivalence))

# ===========================================================================
section("get_norms('lnc')：獨立路徑對照與 meta 核對")
# ===========================================================================
sample = random.Random(42).sample(range(N), 20)


def independent_lnc_norms(docs: list[int]) -> dict[int, float]:
    """自行解析 postings.txt，累加 (1 + log10 tf)² （lnc：無 idf）。"""
    want = set(docs)
    norm2 = dict.fromkeys(docs, 0.0)
    with (INDEX / "postings.txt").open("r", encoding="utf-8", newline="") as f:
        for line in f:
            line = line.rstrip("\r\n")
            _term, rest = line.split(", ", 1)
            _df, rest = rest.split(": <", 1)
            body = rest[:-1]
            if not body:
                continue
            for item in body.split("; "):
                doc_s, tf_s = item.split(": <", 1)[0].split(", ")
                doc = int(doc_s)
                if doc in want:
                    w = 1 + math.log10(int(tf_s))
                    norm2[doc] += w * w
    return {d: math.sqrt(v) for d, v in norm2.items()}


lnc_dir = make_tmp_index()
build_norms(lnc_dir, "lnc")
lnc_reader = IndexReader(lnc_dir)


def _lnc_independent():
    norms = lnc_reader.get_norms("lnc")
    ref = independent_lnc_norms(sample)
    worst = max(abs(norms[d] - ref[d]) for d in sample)
    return worst < 1e-9, f"20 篇最大誤差={worst:.3e}"


results.append(run("get_norms('lnc') 與獨立解析一致（< 1e-9）", _lnc_independent))
results.append(run("get_norms('lnc')[24621] == 0.0",
                   lambda: (lnc_reader.get_norms("lnc")[EMPTY_DOC] == 0.0, "")))
results.append(run("lnc 檔名為 doc_norms.lnc.bin / .meta.json 且不影響核心檔",
                   lambda: ((lnc_dir / "doc_norms.lnc.bin").exists()
                            and (lnc_dir / "doc_norms.lnc.meta.json").exists()
                            and not (lnc_dir / "doc_norms.bin").exists(), "")))


def _lnc_meta_scheme_tampered():
    meta_path = lnc_dir / "doc_norms.lnc.meta.json"
    original = meta_path.read_text(encoding="utf-8")
    meta = json.loads(original)
    meta["scheme"] = "ltc"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    try:
        return raises(ValueError, lambda: IndexReader(lnc_dir).get_norms("lnc"))
    finally:
        meta_path.write_text(original, encoding="utf-8")


results.append(run("lnc meta 的 scheme 改成 'ltc' → ValueError", _lnc_meta_scheme_tampered))


def _lnc_meta_formula_tampered():
    meta_path = lnc_dir / "doc_norms.lnc.meta.json"
    original = meta_path.read_text(encoding="utf-8")
    meta = json.loads(original)
    meta["formula"] = FORMULA
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    try:
        return raises(ValueError, lambda: IndexReader(lnc_dir).get_norms("lnc"))
    finally:
        meta_path.write_text(original, encoding="utf-8")


results.append(run("lnc meta 的 formula 改成 ltc 公式 → ValueError", _lnc_meta_formula_tampered))
results.append(run("尚未建置 ntc → get_norms('ntc') 拋出 FileNotFoundError",
                   lambda: raises(FileNotFoundError, lambda: lnc_reader.get_norms("ntc"))))
shutil.rmtree(lnc_dir, ignore_errors=True)

# ===========================================================================
section("normalization = n：全 1.0，不讀檔")
# ===========================================================================
def _ones(scheme: str):
    def _go():
        norms = IndexReader(INDEX).get_norms(scheme)
        ok = len(norms) == N and norms.typecode == "d" and all(v == 1.0 for v in norms)
        return ok, f"len={len(norms)}"
    return _go


results.append(run("get_norms('bnn') 長度 34786 且全為 1.0", _ones("bnn")))
results.append(run("get_norms('ltn') 長度 34786 且全為 1.0", _ones("ltn")))
results.append(run("index 目錄沒有 doc_norms.bnn.* / doc_norms.ltn.*",
                   lambda: (not list(INDEX.glob("doc_norms.bnn.*")) and not list(INDEX.glob("doc_norms.ltn.*")), "")))


def _build_n_raises():
    tmp = make_tmp_index()
    try:
        ok, detail = raises(ValueError, lambda: build_norms(tmp, "bnn"))
        leftover = [p.name for p in tmp.glob("doc_norms*")]
        return ok and not leftover, f"{detail}; 殘留檔案={leftover}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


results.append(run("build_norms(index, 'bnn') 拋出 ValueError 且不寫檔", _build_n_raises))
results.append(run("get_norms('xyz') 拋出 ValueError",
                   lambda: raises(ValueError, lambda: IndexReader(INDEX).get_norms("xyz"))))

# ===========================================================================
section("Champion list（r = 50）")
# ===========================================================================
R = 50


def read_vbyte(data: bytes, offset: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        b = data[offset]
        offset += 1
        value |= (b & 0x7F) << shift
        if not b & 0x80:
            return value, offset
        shift += 7


def load_champion_tsv() -> dict[str, tuple[int, int, int]]:
    out = {}
    with (INDEX / f"champions.r{R}.tsv").open("r", encoding="utf-8", newline="") as f:
        for row in csv.reader(f, delimiter="\t"):
            out[row[0]] = (int(row[1]), int(row[2]), int(row[3]))
    return out


def decode_champion_block(term: str, tsv: dict) -> tuple[list[tuple[int, int]], int, int, int]:
    n_tsv, offset, length = tsv[term]
    with (INDEX / f"champions.r{R}.bin").open("rb") as f:
        f.seek(offset)
        data = f.read(length)
    n = struct.unpack_from(">I", data, 0)[0]
    pos, doc, rows = 4, 0, []
    for _ in range(n):
        d, pos = read_vbyte(data, pos)
        tf, pos = read_vbyte(data, pos)
        doc += d
        rows.append((doc, tf))
    return rows, n, n_tsv, pos


idx_reader = IndexReader(INDEX)
champ_tsv = load_champion_tsv()


def _champion_term(term: str):
    def _go():
        rows, n, n_tsv, used = decode_champion_block(term, champ_tsv)
        length = champ_tsv[term][2]
        top = sorted(((p.doc_num, p.tf) for p in idx_reader.get_postings(term)),
                     key=lambda x: (-x[1], x[0]))[:R]
        docs = [d for d, _ in rows]
        checks = {
            "筆數=50": n == R == len(rows),
            "tsv n=50": n_tsv == R,
            "length=解碼 byte 數": length == used,
            "doc 集合=前 50 名": set(docs) == {d for d, _ in top},
            "doc 嚴格遞增": all(a < b for a, b in zip(docs, docs[1:])),
            "tf 與 postings 相同": dict(rows) == dict(top),
        }
        bad = [k for k, v in checks.items() if not v]
        return not bad, "失敗項目=" + ",".join(bad) if bad else f"n={n}, bytes={length}"
    return _go


for t in ("home", "new", "linux", "kernel"):
    results.append(run(f"champion '{t}'：筆數／集合／遞增／tf", _champion_term(t)))


def _row_count():
    expected = sum(1 for _t, (df, _o, _l) in idx_reader._load_lexicon().items() if df > R)
    meta = json.loads((INDEX / f"champions.r{R}.meta.json").read_text(encoding="utf-8"))
    ok = len(champ_tsv) == expected == meta["count"] == 15755
    return ok, f"tsv={len(champ_tsv)}, df>50={expected}, meta.count={meta['count']}"


results.append(run("tsv 行數 == df > 50 的 term 數 == meta.count == 15755", _row_count))
results.append(run("'retreiv'（df 11）與 ',ltd.is'（df 1）不在 tsv",
                   lambda: ("retreiv" not in champ_tsv and ",ltd.is" not in champ_tsv, "")))


def _champion_order_and_meta():
    terms = list(champ_tsv)
    lex_order = [t for t in idx_reader._load_lexicon() if t in champ_tsv]
    meta = json.loads((INDEX / f"champions.r{R}.meta.json").read_text(encoding="utf-8"))
    ok = (terms == lex_order and meta["r"] == R and meta["rule"] == "(-tf, doc)"
          and meta["N"] == N and set(meta["sources"]) == {"lexicon.tsv", "postings.bin"})
    return ok, f"rule={meta['rule']!r}"


results.append(run("tsv 順序同 lexicon；meta 的 r／rule／N／sources 正確", _champion_order_and_meta))


def _bad_r():
    from build_champions import build_champions
    tmp = make_tmp_index()
    try:
        return raises(ValueError, lambda: build_champions(tmp, 0))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


results.append(run("build_champions(index, 0) 拋出 ValueError", _bad_r))

# ===========================================================================
section("Test Summary")
# ===========================================================================
all_passed = all(results)
print(f"\n  {sum(results)}/{len(results)} passed")
print(f"  Overall: {'ALL PASSED ✓' if all_passed else 'SOME FAILED ✗'}\n")
sys.exit(0 if all_passed else 1)
