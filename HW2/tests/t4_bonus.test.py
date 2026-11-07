"""t4_bonus.test.py — T4 加分（T4b、T4c）：NOT、括號、Phrase、Near、Wildcard／expand、
position_match、suggest、soundex／suggest_soundex；T4c（§6.8）的原字拼字、任意位置的 wildcard、SOUNDEX()

執行（先建置一次 surface_vocab.*）：
  uv run python HW2/src/build_surface_vocab.py
  uv run python HW2/tests/t4_bonus.test.py

position_match 的預期值一律由本檔內的暴力掃描算出（直接讀 get_postings 的 positions，
不 import positional.py 的 helper，也不拿 position_match 的結果當預期值）。
§6.8 的預期值也一律由本檔內的暴力做法算出：直接讀 surface_vocab.tsv（不經過 load_surface），
wildcard 用 fnmatchcase 全掃、拼字自己算 Jaccard 與 OSA、Soundex 自己分組。
原字詞彙層的資料結構（tsv、meta、k-gram index、Soundex 分組）在 t4_surface.test.py。
計時只列出數字，不設門檻（T4.md §6.7、§6.8.8）。
"""
from __future__ import annotations

import csv
import fnmatch
import json
import statistics
import subprocess
import sys
import time
import tracemalloc
import warnings
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
INDEX = ROOT / "index"
sys.path.insert(0, str(SRC))

from parser import And, Near, Not, Or, Phrase, Term, Wildcard, _lex, expand, parse, query_terms
from tokenizer import Preprocessor
from writer import IndexReader
import parser as parser_mod
import positional
import spelling
import surface

# T4c 新增的名稱：尚未實作時用替身，讓整個檔案照樣跑完並記為 FAIL
try:
    from parser import Soundex
except ImportError:
    @dataclass
    class Soundex:  # type: ignore[no-redef]
        word: str
query_words = getattr(parser_mod, "query_words", None)
did_you_mean = getattr(spelling, "did_you_mean", None)

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


def check(name: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))
    return condition


def run(name: str, fn) -> bool:
    """執行 fn() -> (condition, detail)；例外（含 NotImplementedError）視為 FAIL，不中斷。"""
    try:
        cond, detail = fn()
    except Exception as e:  # noqa: BLE001
        return check(name, False, f"{type(e).__name__}: {e}")
    return check(name, cond, detail)


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def counting(fn, *args, **kwargs):
    """回傳 (fn 的結果, 警告訊息 list)。必須 simplefilter("always")，否則同位置同訊息會被合併。"""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        out = fn(*args, **kwargs)
    return out, [str(x.message) for x in w]


def ms(fn, repeat: int = 5) -> float:
    """暖身一次後 repeat 次的中位數（ms）。"""
    fn()
    ts = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t0) * 1000)
    return statistics.median(ts)


def timing(label: str, fn, digits: int = 1) -> None:
    """記錄一筆計時；stub 狀態的例外只記下來，不中斷。"""
    try:
        timings.append(f"{label}：{ms(fn):.{digits}f} ms（暖身後 5 次中位數）")
    except Exception as e:  # noqa: BLE001
        timings.append(f"{label}：{type(e).__name__}")


T = Term
P = Phrase
reader = IndexReader(INDEX)
pre = Preprocessor.from_config(reader.get_metadata()["preprocessor"])
results: list[bool] = []
timings: list[str] = []

# 原字詞彙：直接讀 tsv（不經過 load_surface），作為 §6.8 暴力做法的資料來源
with (INDEX / "surface_vocab.tsv").open("r", encoding="utf-8", newline="") as _f:
    _rows = list(csv.reader(_f, delimiter="\t"))[1:]
S_WORDS = [r[0] for r in _rows]
S_DF = {r[0]: int(r[1]) for r in _rows}
S_STEM = {r[0]: r[2] for r in _rows}
del _rows


def sdf(w: str) -> int:
    """原字 df（測試內直接讀 tsv）；不存在回傳 0。"""
    return S_DF.get(w, 0)


def stems_of(ws) -> set[str]:
    """原字 → stem，略過 stopword（空字串），去重。"""
    return {S_STEM[w] for w in ws if S_STEM[w]}


def by_df(ts) -> list[str]:
    return sorted(ts, key=lambda t: (-reader.df(t), t))


def words_with_prefix(p: str) -> list[str]:
    i = bisect_left(S_WORDS, p)
    out = []
    while i < len(S_WORDS) and S_WORDS[i].startswith(p):
        out.append(S_WORDS[i])
        i += 1
    return out


def terms_of(node) -> list[str]:
    """expand 的結果（Term 或 Or 的 Term）→ term list，順序不變。"""
    if node is None:
        return []
    if isinstance(node, Term):
        return list(node.tokens)
    return [c.tokens[0] for c in node.children]

# ===========================================================================
section("1. 語法：AST、query_terms、警告次數（T4.md §6.7 表，expand 之前）")
# ===========================================================================
# (query, 預期 AST, 預期 query_terms；None 代表應拋 ValueError, 預期警告次數)
CASES = [
    ("(linux OR windows) AND kernel", And([Or([T(["linux"]), T(["window"])]), T(["kernel"])]),
     Counter(linux=1, window=1, kernel=1), 0),
    ("linux AND NOT windows", And([T(["linux"]), Not(T(["window"]))]), Counter(linux=1), 0),
    ("linux NOT windows", And([T(["linux"]), Not(T(["window"]))]), Counter(linux=1), 0),
    ("NOT linux", Not(T(["linux"])), Counter(), 0),
    ('"open source" AND linux', And([P(["open", "sourc"], [1, 2]), T(["linux"])]),
     Counter(open=1, sourc=1, linux=1), 0),
    ('"lord of the rings"', P(["lord", "ring"], [1, 4]), Counter(lord=1, ring=1), 0),
    ("linux /5 kernel", Near(P(["linux"], [1]), P(["kernel"], [1]), 5), Counter(linux=1, kernel=1), 0),
    ("e-mail /5 server", Near(P(["e", "mail"], [1, 2]), P(["server"], [1]), 5),
     Counter(e=1, mail=1, server=1), 0),
    ("the /3 linux", T(["linux"]), Counter(linux=1), 1),
    ('"open source" /3 the', P(["open", "sourc"], [1, 2]), Counter(open=1, sourc=1), 1),
    ("NOT (a OR b)", Not(T(["b"])), Counter(), 1),
    ("((linux))", T(["linux"]), Counter(linux=1), 0),
    ('"linux"', T(["linux"]), Counter(linux=1), 0),
    ("(linux AND kernel) AND window", And([T(["linux"]), T(["kernel"]), T(["window"])]),
     Counter(linux=1, kernel=1, window=1), 0),
    ("Comput*", Wildcard("comput*"), None, 0),
]
# 計畫表以外的補充（缺少運算元、Near 退化的其他形狀）
EXTRA = [
    ("NOT", None, None, 1),                     # Not(∅) → 移除；空 Term 警告 1 次
    ("()", None, None, 1),
    ("linux /5", T(["linux"]), Counter(linux=1), 1),
    ("the /3 of", None, None, 2),               # 兩側都空：每個空的一側各警告一次
    ('"the"', None, None, 1),                   # 空的 Phrase
    ('"open source" /2 "linux kernel"',
     Near(P(["open", "sourc"], [1, 2]), P(["linux", "kernel"], [1, 2]), 2),
     Counter(open=1, sourc=1, linux=1, kernel=1), 0),
    ("linux (kernel OR driver)", And([T(["linux"]), Or([T(["kernel"]), T(["driver"])])]),
     Counter(linux=1, kernel=1, driver=1), 0),   # 括號前的隱含 AND
    ("NOT NOT linux", Not(Not(T(["linux"]))), Counter(), 0),
    ("comput* OR linux", Or([Wildcard("comput*"), T(["linux"])]), None, 0),
]

for q, exp_ast, exp_qtf, exp_w in CASES + EXTRA:
    def _case(q=q, exp_ast=exp_ast, exp_w=exp_w):
        node, w = counting(parse, q, pre)
        return node == exp_ast and len(w) == exp_w, f"got {node!r}, {len(w)} 警告"

    results.append(run(f"parse({q!r})", _case))
    if exp_ast is None:
        continue

    def _qtf(q=q, exp_qtf=exp_qtf):
        node, _ = counting(parse, q, pre)
        if exp_qtf is None:
            try:
                query_terms(node)
            except ValueError as e:
                return True, f"ValueError: {e}"
            return False, "沒有拋 ValueError"
        got = query_terms(node)
        return got == exp_qtf, f"got {dict(got)}"

    results.append(run(f"query_terms({q!r})" + (" 拋 ValueError" if exp_qtf is None else ""), _qtf))


def _tokens_in_dict():
    toks = set()
    for _q, ast, qtf, _w in CASES + EXTRA:
        if qtf:
            toks |= set(qtf)
    missing = sorted(t for t in toks if t not in reader)
    return not missing, f"不在 dictionary：{missing}"


results.append(run("表中 query_terms 的 token 都在 dictionary", _tokens_in_dict))

# ===========================================================================
section("2. 語法錯誤：ValueError 與字元位置")
# ===========================================================================
ERRORS = [
    ('"open source AND linux', 0),
    ("(linux OR windows", 0),
    ("linux)", 5),
    ("linux AND (kernel", 10),
    ("*", 0),
    ("linux /0 kernel", 6),
    ('linux "open', 6),
    ("((linux)", 0),
    ("linux OR **", 9),
]
for q, pos in ERRORS:
    def _err(q=q, pos=pos):
        try:
            node, _ = counting(parse, q, pre)
        except ValueError as e:
            return f"position {pos}" in str(e), f"{e}"
        return False, f"沒有拋 ValueError，得到 {node!r}"

    results.append(run(f"parse({q!r}) 拋 ValueError（位置 {pos}）", _err))


def _no_error():
    node, _ = counting(parse, "e-mail /5 server", pre)
    return isinstance(node, Near), f"got {node!r}"


results.append(run("e-mail /5 server 不拋錯", _no_error))

# ===========================================================================
section("3. expand（Wildcard）")
# ===========================================================================


def _comput():
    node = parse("comput*", pre)
    before = repr(node)
    out, w = counting(expand, node, reader)
    terms = out.children if isinstance(out, Or) else []
    ok = (isinstance(out, Or) and len(terms) == 64 and all(isinstance(t, Term) and len(t.tokens) == 1
                                                           and t.tokens[0].startswith("comput") for t in terms)
          and terms[0] == T(["comput"]) and not w and repr(node) == before and node == Wildcard("comput*"))
    return ok, f"{len(terms)} 個 Term，第一個 {terms[:1]}，{len(w)} 警告，原樹 {node!r}"


results.append(run("comput* → Or 64 個 Term，第一個 comput，無警告，原樹不變", _comput))


def _comput_order():
    out = expand(parse("comput*", pre), reader)
    got = [t.tokens[0] for t in out.children]
    # 預期順序獨立算（§6.8.8）：原字詞彙中以 comput 開頭的原字 → stem 去重 → 依 (-df, term) 排序
    df = reader.df
    exp = by_df(stems_of(w for w in S_WORDS if w.startswith("comput")))
    top_got = [(t, df(t)) for t in got[:5]]
    top_exp = [(t, df(t)) for t in exp[:5]]
    ok = got == exp
    detail = f"{len(got)} vs 預期 {len(exp)} 個；前 5 個實際 {top_got}；預期 {top_exp}"
    if not ok:
        diff = next((i for i, (a, b) in enumerate(zip(got, exp)) if a != b), min(len(got), len(exp)))
        detail += f"；第一個不同在索引 {diff}"
    return ok, detail


results.append(run("comput* 的順序是 (-df, term)", _comput_order))


def _a_star():
    out, w = counting(expand, parse("a*", pre), reader)
    n = len(out.children) if isinstance(out, Or) else -1
    return (n == 100 and out.children[0] == T(["also"]) and len(w) == 1 and "31236" in w[0]), \
        f"{n} 個，第一個 {out.children[:1] if n > 0 else None}，警告 {w}"


results.append(run("a* → 100 個 Term，第一個 also，警告 1 次含 31236", _a_star))


def _a_limit():
    out, w = counting(expand, parse("a*", pre), reader, limit=3)
    # 預期值：原字詞彙中以 a 開頭的原字 → stem 去重 → (-df, term) 的前 3 個
    exp = [T([t]) for t in by_df(stems_of(words_with_prefix("a")))[:3]]
    return isinstance(out, Or) and out.children == exp and len(w) == 1, f"got {out!r}"


results.append(run("expand(a*, limit=3) 取前 3 個", _a_limit))


def _computing():
    # §6.8.4：computing* 在原字上比對，對到 computing → stem comput
    out, w = counting(expand, parse("computing*", pre), reader)
    out2, w2 = counting(expand, parse("linux OR computing*", pre), reader)
    return (out == T(["comput"]) and not w and out2 == Or([T(["linux"]), T(["comput"])]) and not w2), \
        f"{out!r}/{len(w)} 警告；{out2!r}/{len(w2)} 警告"


results.append(run("computing* → T(['comput'])；linux OR computing* → Or([linux, comput])，無警告", _computing))


def _email_star():
    out, w = counting(expand, parse("e-mail*", pre), reader)
    out2, w2 = counting(expand, parse("linux OR e-mail*", pre), reader)
    return (out is None and len(w) == 1 and out2 == T(["linux"]) and len(w2) == 1), \
        f"{out!r}/{w}；{out2!r}/{len(w2)} 警告"


results.append(run("e-mail* → None（警告 1 次）；linux OR e-mail* → T(['linux'])", _email_star))


def _single():
    # 原字詞彙中「以 p 開頭的原字只對到 1 個 stem」時，結果是 Term 而不是 Or（暴力挑 p）
    p = next(w for w in S_WORDS[1000:] if w.isalpha() and len(w) >= 6
             and len(stems_of(words_with_prefix(w))) == 1)
    (stem,) = stems_of(words_with_prefix(p))
    out = expand(Wildcard(p + "*"), reader)
    return out == T([stem]), f"pattern {p + '*'!r}（{len(words_with_prefix(p))} 個原字）→ {out!r}"


results.append(run("只展開成 1 個時是 Term", _single))


def _nested():
    node = parse("linux AND NOT (comput* OR window)", pre)
    before = repr(node)
    out, w = counting(expand, node, reader)
    ok = (isinstance(out, And) and out.children[0] == T(["linux"]) and isinstance(out.children[1], Not)
          and isinstance(out.children[1].child, Or) and len(out.children[1].child.children) == 65
          and out.children[1].child.children[-1] == T(["window"]) and repr(node) == before and not w)
    return ok, f"got {repr(out)[:120]}…"


results.append(run("巢狀 Wildcard 展開後同類型 Or 合併，原樹不變", _nested))


def _expand_copy():
    # 回傳的樹與輸入不共用可變的節點：改動結果不影響原樹
    node = parse('"open source" AND comput*', pre)
    before = repr(node)
    out = expand(node, reader)
    out.children[0].tokens.append("x")   # 改結果中的 Phrase
    out.children.append(T(["y"]))        # 改結果中的 And 的 children
    mutated = out.children[0].tokens[-1] == "x" and out.children[-1] == T(["y"])
    unchanged = repr(node) == before
    return mutated and unchanged, \
        f"結果已改動 {mutated}；原樹{'不變' if unchanged else '被改動'}：{node!r}"


results.append(run("expand 的結果與原樹不共用節點", _expand_copy))


def _qtf_after():
    out = expand(parse("comput*", pre), reader)
    q = query_terms(out)
    return len(q) == 64 and q["comput"] == 1, f"{len(q)} 個 term"


results.append(run("expand 之後 query_terms 可以正常計算", _qtf_after))
timing("expand(comput*)（原字 k-gram，64 個）", lambda: expand(Wildcard("comput*"), reader), 3)
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    timing("expand(a*)（原字 k-gram，31,236 個 stem 取前 100）", lambda: expand(Wildcard("a*"), reader), 3)

# ===========================================================================
section("4. position_match：與暴力掃描對照")
# ===========================================================================
_post_cache: dict[str, dict[int, list[int]]] = {}


def postings_map(term: str) -> dict[int, list[int]]:
    if term not in _post_cache:
        _post_cache[term] = {p.doc_num: list(p.positions) for p in reader.get_postings(term)}
    return _post_cache[term]


def brute_intervals(ph: Phrase) -> dict[int, list[tuple[int, int]]]:
    """暴力：對每篇含全部 token 的文件建「位置 → term 集合」，掃過每個可能的起點。"""
    maps = [postings_map(t) for t in ph.tokens]
    docs = set(maps[0])
    for m in maps[1:]:
        docs &= set(m)
    span = ph.positions[-1] - ph.positions[0]
    out: dict[int, list[tuple[int, int]]] = {}
    for d in docs:
        at: dict[int, set[str]] = {}
        for t, m in zip(ph.tokens, maps):
            for p in m[d]:
                at.setdefault(p, set()).add(t)
        hits = []
        for start in range(1, max(at) + 1):
            if all(t in at.get(start + off - ph.positions[0], ()) for t, off in zip(ph.tokens, ph.positions)):
                hits.append((start, start + span))
        if hits:
            out[d] = hits
    return out


def brute_near(nd: Near, direction: str = "both") -> set[int]:
    """暴力：兩邊各自的區間做兩層迴圈；direction 為 fwd（右在後）／rev（左在後）／both。"""
    L, R = brute_intervals(nd.left), brute_intervals(nd.right)
    hit = set()
    for d in set(L) & set(R):
        for ls, le in L[d]:
            for rs, re_ in R[d]:
                fwd = 1 <= rs - le <= nd.k
                rev = 1 <= ls - re_ <= nd.k
                if (direction == "fwd" and fwd) or (direction == "rev" and rev) or \
                        (direction == "both" and (fwd or rev)):
                    hit.add(d)
    return hit


def brute(node) -> set[int]:
    return set(brute_intervals(node)) if isinstance(node, Phrase) else brute_near(node)


_pm_cache: dict[str, set[int]] = {}


def pm(q: str) -> set[int]:
    if q not in _pm_cache:
        _pm_cache[q] = positional.position_match(parse(q, pre), reader)
    return _pm_cache[q]


for q in ['"lord of the rings"', '"open source"', "e-mail /5 server", "linux /5 kernel",
          '"bye bye"', '"step by step"', '"the new york times"',
          '"open source" /3 "linux kernel"', "linux /1 kernel", '"step by step" /4 linux']:
    def _bf(q=q):
        got, exp = pm(q), brute(parse(q, pre))
        return got == exp, f"{len(got)} 篇 vs 暴力 {len(exp)} 篇；多 {sorted(got - exp)[:5]} 少 {sorted(exp - got)[:5]}"

    results.append(run(f"position_match({q!r}) == 暴力掃描", _bf))


def _email_27():
    exp = brute(parse("e-mail /5 server", pre))
    return len(exp) == 27, f"暴力 {len(exp)} 篇（預先量測 27，只用來檢查測試本身）"


results.append(run("e-mail /5 server 的暴力結果是 27 篇（檢查測試本身）", _email_27))


def _doc1400():
    nd = parse("e-mail /5 server", pre)
    only_rev = 1400 in brute_near(nd, "rev") and 1400 not in brute_near(nd, "fwd")
    return only_rev and 1400 in pm("e-mail /5 server"), f"只靠反方向 {only_rev}，在結果中 {1400 in pm('e-mail /5 server')}"


results.append(run("doc 1400 只靠 server 在 e mail 前面命中，且在結果中", _doc1400))


def _linux_rev():
    nd = parse("linux /5 kernel", pre)
    rev_only = brute_near(nd, "rev") - brute_near(nd, "fwd")
    return bool(rev_only) and rev_only <= pm("linux /5 kernel"), f"只靠反方向的 {len(rev_only)} 篇"


results.append(run("linux /5 kernel 包含只靠反方向命中的文件", _linux_rev))


def _phrase_subset():
    a, b = pm('"open source"'), pm("open /1 source")
    return a <= b, f"phrase {len(a)} 篇，open /1 source {len(b)} 篇"


results.append(run('"open source" ⊆ open /1 source', _phrase_subset))


def _symmetric():
    a, b = pm("linux /5 kernel"), pm("kernel /5 linux")
    return a == b, f"{len(a)} vs {len(b)}"


results.append(run("linux /5 kernel == kernel /5 linux", _symmetric))


def _huge_k():
    got = pm("linux /1000000 kernel")
    both = set(postings_map("linux")) & set(postings_map("kernel"))
    return got == both, f"{len(got)} vs 同時含兩詞 {len(both)}"


results.append(run("linux /1000000 kernel == 同時含 linux 與 kernel 的文件", _huge_k))


def _overlap():
    # 兩側區間重疊不算：linux /5 linux 只在某篇有兩個 linux、間隔 1..5 時命中
    got = positional.position_match(Near(P(["linux"], [1]), P(["linux"], [1]), 5), reader)
    exp = set()
    for d, ps in postings_map("linux").items():
        if any(1 <= abs(a - b) <= 5 for a in ps for b in ps):
            exp.add(d)
    return got == exp, f"{len(got)} vs {len(exp)}（只出現一次的文件不算）"


results.append(run("linux /5 linux：同一位置（重疊）不算命中", _overlap))


def _missing_term():
    got = positional.position_match(P(["linux", "zzzzqqqx"], [1, 2]), reader)
    return got == set(), f"{got}"


results.append(run("Phrase 中有不在 dictionary 的 term → 空集合", _missing_term))


def _one_call_per_token():
    calls: Counter[str] = Counter()
    orig = reader.get_postings

    def spy(term):
        calls[term] += 1
        return orig(term)

    reader.get_postings = spy
    try:
        positional.position_match(parse('"new new york"', pre), reader)
        positional.position_match(Near(P(["linux", "kernel"], [1, 2]), P(["linux"], [1]), 3), reader)
    finally:
        del reader.get_postings
    return all(v <= 2 for v in calls.values()) and calls["new"] == 1 and calls["linux"] == 1, f"{dict(calls)}"


results.append(run("每個 token 只呼叫一次 get_postings（new new york、Near 兩側共用 linux）", _one_call_per_token))

for _q in ['"open source"', "linux /5 kernel", '"lord of the rings"', "e-mail /5 server"]:
    timing(f"position_match({_q})", lambda _q=_q: positional.position_match(parse(_q, pre), reader))
timing("對照：get_postings('open') + get_postings('sourc')",
       lambda: (reader.get_postings("open"), reader.get_postings("sourc")))
timing("對照：get_postings('linux') + get_postings('kernel')",
       lambda: (reader.get_postings("linux"), reader.get_postings("kernel")))

# ===========================================================================
section("5. 拼字建議 suggest（§6.8.3：輸入與回傳都是原字；含 §6.8.8 第 8 節）")
# ===========================================================================
vocab = reader.vocabulary()
vocab_len, vocab_head = len(vocab), list(vocab[:20])
sv = surface.load_surface(reader)  # 讀 tsv 的成本不算在 k-gram 內（見 t4_surface 與最後的新 process 量測）
sv_words, sv_words_len, sv_words_head = sv.words, len(sv.words), list(sv.words[:20])


def _kgram_build(trace: bool) -> None:
    label = "開啟 tracemalloc" if trace else "不開 tracemalloc"
    try:
        sv._kgram = None  # 清除 surface.py 的 k-gram 快取（只清這一份，原字詞彙本身不重讀）
        if trace:
            tracemalloc.start()
        t0 = time.perf_counter()
        sv.kgram()
        dt = time.perf_counter() - t0
        extra = ""
        if trace:
            cur, peak = tracemalloc.get_traced_memory()
            extra = f"，建置後仍占用 {cur / 2**20:.1f} MiB／峰值 {peak / 2**20:.1f} MiB"
        timings.append(f"原字 k-gram index 建置（{len(sv.words):,} 個原字，{label}）：{dt:.2f} s{extra}")
    except Exception as e:  # noqa: BLE001
        timings.append(f"原字 k-gram index 建置（{label}）：{type(e).__name__}: {e}")
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()


_kgram_build(True)
_kgram_build(False)


def own_bigrams(w: str) -> set[str]:
    s = "$" + w + "$"
    return {s[i:i + 2] for i in range(len(s) - 1)}


def osa(a: str, b: str) -> int:
    """測試內自己寫的 OSA（完整 DP 表），與 spelling._osa 的寫法不同。"""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            c = a[i - 1] != b[j - 1]
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + c)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


_brute_sug: dict[str, tuple[list[str], list[str]]] = {}


def brute_suggest(word: str) -> tuple[list[str], list[str]]:
    """暴力：全掃原字算 bigram Jaccard ≥ 0.3 → 排除輸入本身、stopword、同 stem →
    依 (OSA, -原字 df, 原字) 排序（去重前）→ 依 stem 去重（每個 stem 保留第一個）。"""
    if word not in _brute_sug:
        a = own_bigrams(word)
        in_stem = S_STEM[word] if word in S_STEM else (pre.normalize_token(word) or "")
        ranked = []
        for w in S_WORDS:
            b = own_bigrams(w)
            inter = len(a & b)
            if inter and inter / (len(a) + len(b) - inter) >= 0.3:
                st = S_STEM[w]
                if w != word and st and st != in_stem:
                    ranked.append(w)
        ranked.sort(key=lambda w: (osa(word, w), -sdf(w), w))
        seen: set[str] = set()
        dedup = []
        for w in ranked:
            if S_STEM[w] not in seen:
                seen.add(S_STEM[w])
                dedup.append(w)
        _brute_sug[word] = (ranked, dedup)
    return _brute_sug[word]


def _retreival():
    s = spelling.suggest("retreival", reader)
    return (bool(s) and s[0] == "retrieval" and "retrieved" not in s and "retrieve" not in s), \
        f"{[(w, sdf(w), S_STEM.get(w)) for w in s]}"


results.append(run("suggest('retreival')[0] == 'retrieval'；不含 retrieved、retrieve（同 stem 只留 OSA 最小的）",
                   _retreival))


def _brute_equal():
    bad = []
    for w in ["retreival", "kernal", "computr"]:
        _ranked, dedup = brute_suggest(w)
        full = spelling.suggest(w, reader, limit=10**9)
        top = spelling.suggest(w, reader)
        if full != dedup or top != dedup[:5]:
            bad.append((w, top, dedup[:5], len(full), len(dedup)))
    return not bad, f"不符 {bad}" if bad else "retreival、kernal、computr：完整結果與前 5 名都與暴力相同"


results.append(run("suggest 與暴力（全掃 Jaccard → 排除 → OSA 排序 → stem 去重）完全相同", _brute_equal))


def _dedup_rule():
    ranked, _ = brute_suggest("retreival")
    s = spelling.suggest("retreival", reader)
    first = {}
    for w in ranked:
        first.setdefault(S_STEM[w], w)
    bad = [(w, first.get(S_STEM.get(w))) for w in s if first.get(S_STEM.get(w)) != w]
    rv = [(w, osa("retreival", w), sdf(w)) for w in ranked if S_STEM[w] == "retriev"]
    return not bad, f"不符 {bad}；stem retriev 在去重前的順序 {rv}"


results.append(run("去重：s 中每個原字都是該 stem 在去重前排序中的第一個", _dedup_rule))


def _same_stem_excluded():
    full = spelling.suggest("retreival", reader, limit=10**9)
    same = [w for w in ("retreived", "retreives", "retreiver") if w in S_WORDS]
    leaked = [w for w in full if S_STEM.get(w) == "retreiv"]
    return len(same) == 3 and not leaked, f"同 stem 的原字 {same} 都存在；結果中 stem 為 retreiv 的 {leaked}"


results.append(run("與輸入同 stem 的原字（retreived、retreives、retreiver）都被排除", _same_stem_excluded))


def _shape():
    bad = []
    for w in ["retreival", "retreiv", "linux", "kernal", "comput", "zzzzqqqx"]:
        s = spelling.suggest(w, reader)
        st = [S_STEM.get(x) for x in s]
        if w in s or len(s) > 5 or len(s) != len(set(s)) or len(st) != len(set(st)) or not all(st):
            bad.append((w, s, st))
    s3 = spelling.suggest("linux", reader, limit=3)
    return not bad and len(s3) <= 3, f"{bad} / limit=3 → {s3}"


results.append(run("結果不含輸入本身、長度 ≤ limit、沒有重複、沒有重複的 stem、沒有 stopword", _shape))


def _sorted():
    # 去重只會刪掉元素，所以結果仍依 (OSA, -原字 df, 原字) 排序
    bad = {}
    for w in ["retreival", "computr", "linux"]:
        keys = [(osa(w, t), -sdf(t), t) for t in spelling.suggest(w, reader, limit=20)]
        if keys != sorted(keys):
            bad[w] = keys
    return not bad, f"{bad}" if bad else "retreival、computr、linux（limit=20）都已排序"


results.append(run("suggest 依 (OSA 距離, -原字 df, 原字) 排序", _sorted))


def _vocab_untouched():
    v = reader.vocabulary()
    ok1 = len(v) == vocab_len and v[:20] == vocab_head and v is vocab
    sw = surface.load_surface(reader).words
    ok2 = sw is sv_words and len(sw) == sv_words_len and sw[:20] == sv_words_head
    return ok1 and ok2, f"vocabulary {len(v)} vs {vocab_len}；原字 {len(sw)} vs {sv_words_len}"


results.append(run("suggest 前後 reader.vocabulary() 與原字 list 都沒有被修改", _vocab_untouched))

TRIGGER = {"retreival": ("retrieval", True), "linux": ("linus", False),
           "kernal": ("kernel", True), "computr": ("computer", True)}


def _trigger():
    out, bad = [], []
    for w, (best, fire) in TRIGGER.items():
        s = spelling.suggest(w, reader)
        fires = bool(s) and (sdf(w) == 0 or sdf(s[0]) >= sdf(w) * 10)
        dym = did_you_mean(w, reader)
        out.append(f"{w}({sdf(w)})→{s[:1]}({sdf(s[0]) if s else '-'}) 觸發 {fires}，did_you_mean {dym}")
        if not s or s[0] != best or fires != fire or dym != (s[:3] if fires else []):
            bad.append(w)
    dfs_ok = (sdf("retreival"), sdf("retrieval"), sdf("linux"), sdf("linus"), sdf("computr")) == (1, 81, 997, 28, 0)
    return not bad and dfs_ok, f"不符 {bad}；" + "；".join(out)


results.append(run("觸發條件（原字 df）：retreival、kernal、computr 觸發，linux 不觸發；did_you_mean 一致",
                   _trigger))


def _dym_show():
    return (did_you_mean("retreival", reader, show=1) == ["retrieval"]
            and did_you_mean("linux", reader, show=5) == []), \
        f"show=1 → {did_you_mean('retreival', reader, show=1)}"


results.append(run("did_you_mean(show=1) 只回傳 1 個；不觸發時回傳 []", _dym_show))
results.append(run("load_surface(reader).stem('retrieval') == 'retriev'，而且 'retriev' in reader", lambda: (
    surface.load_surface(reader).stem("retrieval") == "retriev" and "retriev" in reader, "")))

QW = [
    ('Retreival AND "the Kernal" OR comput* SOUNDEX(robert) linux /5 e-mail', ["retreival", "kernal", "linux", "e", "mail"]),
    ("linux linux LINUX", ["linux"]),
    ("the of AND", []),
    ("NOT (Recieve OR goverment)", ["recieve", "goverment"]),
    ('SOUNDEX (robert) "lord of the rings"', ["soundex", "robert", "lord", "rings"]),
]
for _q, _exp in QW:
    results.append(run(f"query_words({_q!r}) == {_exp}", lambda _q=_q, _exp=_exp: (
        query_words(_q, pre) == _exp, f"got {query_words(_q, pre)}")))

for _w in ["retreival", "linux", "a", "computer"]:
    timing(f"suggest({_w!r})（原字，k-gram 已建好）", lambda _w=_w: spelling.suggest(_w, reader))

# ===========================================================================
section("6. Soundex（soundex() 不改；suggest_soundex 改用原字詞彙，§6.8.5 G6）")
# ===========================================================================
SOUNDEX = {"Robert": "R163", "Rupert": "R163", "Ashcraft": "A261", "Tymczak": "T522",
           "Pfister": "P236", "Honeyman": "H555", "Lee": "L000", "Tymczak".lower(): "T522"}
for w, code in SOUNDEX.items():
    results.append(run(f"soundex({w!r}) == {code!r}", lambda w=w, code=code: (spelling.soundex(w) == code,
                                                                           f"got {spelling.soundex(w)!r}")))

try:
    sv._soundex = None  # 清除 surface.py 的 Soundex 分組快取
    t0 = time.perf_counter()
    spelling.suggest_soundex("linux", reader)
    timings.append(f"原字 Soundex 對照表建置（含第一次 suggest_soundex）：{time.perf_counter() - t0:.2f} s")
except Exception as e:  # noqa: BLE001
    timings.append(f"原字 Soundex 對照表建置：{type(e).__name__}")


def _sx_suggest():
    s = spelling.suggest_soundex("retreival", reader)
    return ("retrieved" in s and "retreival" not in s and "retrieval" not in s and len(s) <= 5), f"{s}"


results.append(run("suggest_soundex('retreival') 含 retrieved，不含 retreival、retrieval（同 stem 去重）",
                   _sx_suggest))


def _sx_sorted():
    s = spelling.suggest_soundex("retreival", reader, limit=20)
    keys = [(-sdf(t), t) for t in s]
    st = [S_STEM.get(t) for t in s]
    # 暴力：R361 的純 ASCII 字母原字，依 (-原字 df, 原字) 排序 → 排除 → 依 stem 去重 → 前 20 個
    exp, seen = [], set()
    for w in sorted((w for w in S_WORDS if w.isascii() and w.isalpha() and spelling.soundex(w) == "R361"),
                    key=lambda w: (-sdf(w), w)):
        if w == "retreival" or not S_STEM[w] or S_STEM[w] == "retreiv" or S_STEM[w] in seen:
            continue
        seen.add(S_STEM[w])
        exp.append(w)
    ok = (keys == sorted(keys) and all(spelling.soundex(t) == "R361" and t.isascii() and t.isalpha() for t in s)
          and len(st) == len(set(st)) and all(st) and "retreiv" not in st and s == exp[:20])
    return ok, f"{s}"


results.append(run("suggest_soundex：(-原字 df, 原字) 排序、碼都是 R361、純 ASCII 字母、stem 兩兩不同、"
                   "沒有 stopword、沒有同 stem；與暴力相同", _sx_sorted))
timing("suggest_soundex('retreival')（快取後）", lambda: spelling.suggest_soundex("retreival", reader), 3)

# ===========================================================================
section("9. Wildcard（§6.8.4：原字 k-gram、任意位置的 *）")
# ===========================================================================
for _q in ["*mon", "co*tion", "*tion*", "a*b*c", "/5*"]:
    results.append(run(f"_lex({_q!r}) 是單一 WILDCARD", lambda _q=_q: (
        [k for k, _t, _p in _lex(_q)] == ["WILDCARD"], f"{_lex(_q)}")))

for _q, _pos in [("*", 0), ("**", 0), ("linux OR **", 9)]:
    def _werr(q=_q, pos=_pos):
        try:
            node = parse(q, pre)
        except ValueError as e:
            return f"position {pos}" in str(e) and "without any fixed text" in str(e), f"{e}"
        return False, f"沒有拋 ValueError，得到 {node!r}"

    results.append(run(f"parse({_q!r}) 拋 ValueError（位置 {_pos}，wildcard without any fixed text）", _werr))

results.append(run("parse('Co*TION') == Wildcard('co*tion')；parse('co**tion') == Wildcard('co*tion')", lambda: (
    parse("Co*TION", pre) == Wildcard("co*tion") and parse("co**tion", pre) == Wildcard("co*tion"),
    f"{parse('Co*TION', pre)!r}, {parse('co**tion', pre)!r}")))

_brute_wild: dict[str, set[str]] = {}


def brute_wild(p: str) -> set[str]:
    """暴力：fnmatchcase 全掃原字（pattern 不含 ? 或 [），取 stem 不是空字串的部分去重。"""
    if p not in _brute_wild:
        _brute_wild[p] = stems_of(w for w in S_WORDS if fnmatch.fnmatchcase(w, p))
    return _brute_wild[p]


for _p in ["*mon", "co*tion", "*tion*", "ab*ba", "*x*"]:
    def _wset(p=_p):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            got = terms_of(expand(Wildcard(p), reader, limit=10**9))
        exp = brute_wild(p)
        return set(got) == exp and len(got) == len(exp), \
            f"{len(got)} 個 vs 暴力 {len(exp)} 個；多 {sorted(set(got) - exp)[:5]} 少 {sorted(exp - set(got))[:5]}"

    def _wtop(p=_p):
        out, w = counting(expand, Wildcard(p), reader)
        exp = by_df(brute_wild(p))
        n = len(exp)
        warn_ok = (len(w) == 1 and str(n) in w[0]) if n > 100 else not w
        return terms_of(out) == exp[:100] and warn_ok, f"前 5 個 {terms_of(out)[:5]}；共 {n} 個 stem；警告 {w}"

    results.append(run(f"expand({_p}, limit=10**9) 的 term 集合 == 暴力 fnmatchcase", _wset))
    results.append(run(f"expand({_p}) 預設 limit：順序 == 暴力的 (-df, term) 前 100；超過 100 時警告含總數", _wtop))


def _postfilter():
    cands = [sv.words[i] for i in sv.wildcard_candidates("ab*ba")]
    matched = [sv.words[i] for i in sv.match_wildcard("ab*ba")]
    exp = sorted(w for w in S_WORDS if fnmatch.fnmatchcase(w, "ab*ba"))
    ok = (sorted(matched) == exp and all(len(w) >= 4 for w in matched) and "aba" not in matched
          and len(cands) > len(matched) and set(matched) <= set(cands))
    return ok, (f"k-gram 候選 {len(cands)} 個，post-filter 後 {len(matched)} 個 {sorted(matched)}；"
                f"aba 在詞彙中 {'aba' in S_DF}、在候選中 {'aba' in cands}")


results.append(run("post-filter：ab*ba 的候選中被 regex 刷掉的原字（aba）不會出現", _postfilter))


def _computers():
    out, w = counting(expand, parse("computers*", pre), reader)
    got = terms_of(out)
    return (isinstance(out, Or) and got[:1] == ["comput"] and len(got) == 6 and not w
            and set(got) == brute_wild("computers*")), f"{got}；{len(w)} 警告"


results.append(run("computers* → 6 個，第一個 T(['comput'])，無警告", _computers))


def _no_load():
    calls = []
    orig = surface.load_surface

    def spy(r):
        calls.append(r)
        return orig(r)

    surface.load_surface = spy
    try:
        n1 = parse('linux AND (kernel OR "open source") NOT window /3 driver', pre)
        out1, out0 = expand(n1, reader), expand(None, reader)
        none_before = not calls
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # SOUNDEX(robert) 超過 100 個的警告與這項測試無關
            expand(parse("comput*", pre), reader)
            expand(parse("SOUNDEX(robert)", pre), reader)
        called = len(calls)
    finally:
        surface.load_surface = orig
    return out1 is n1 and out0 is None and none_before and called == 2, \
        f"沒有 Wildcard／Soundex 時呼叫 {0 if none_before else '≥1'} 次；有 Wildcard、Soundex 時 {called} 次"


results.append(run("樹中沒有 Wildcard／Soundex 時 expand 不呼叫 load_surface（spy）", _no_load))

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    for _p in ["*mon", "co*tion", "*tion*", "*x*"]:
        timing(f"expand({_p})" + ("（沒有 bigram，全掃）" if _p == "*x*" else ""),
               lambda _p=_p: expand(Wildcard(_p), reader))

# ===========================================================================
section("10. SOUNDEX(x) 運算子（§6.8.5）")
# ===========================================================================


def plain(s: str) -> list[str]:
    return [t for _, t in pre.process(s)]


SX_CASES = [
    ("SOUNDEX(Robert)", Soundex("robert"), 0),
    ("SOUNDEX(robert)", Soundex("robert"), 0),
    ("linux SOUNDEX(robert)", And([T(["linux"]), Soundex("robert")]), 0),
    ("SOUNDEX (robert)", And([T(plain("SOUNDEX")), T(["robert"])]), 0),
    ("soundex(robert)", And([T(plain("soundex")), T(["robert"])]), 0),
    ("Soundex(robert)", And([T(plain("Soundex")), T(["robert"])]), 0),
    ("SOUNDEX robert", T(plain("SOUNDEX robert")), 0),
    ("SOUNDEX", T(plain("SOUNDEX")), 0),
    ("SOUNDEXES(x)", And([T(plain("SOUNDEXES")), T(["x"])]), 0),
    ("SOUNDEX(robert) /5 kernel", And([Soundex("robert"), T(["kernel"])]), 1),
    ("SOUNDEX(O'Brien)", Soundex("o'brien"), 0),
    ("NOT SOUNDEX(robert) linux", And([Not(Soundex("robert")), T(["linux"])]), 0),
    ("SOUNDEX(smith) OR SOUNDEX(smyth)", Or([Soundex("smith"), Soundex("smyth")]), 0),
]
for _q, _exp, _w in SX_CASES:
    def _sx(q=_q, exp=_exp, nw=_w):
        node, w = counting(parse, q, pre)
        return node == exp and len(w) == nw, f"got {node!r}, {len(w)} 警告"

    results.append(run(f"parse({_q!r})", _sx))

results.append(run("_lex：SOUNDEX 緊接 ( 才是 SOUNDEX；中間有空白是 WORD", lambda: (
    _lex("SOUNDEX(robert)") == [("SOUNDEX", "SOUNDEX", 0), ("(", "(", 7), ("WORD", "robert", 8), (")", ")", 14)]
    and _lex("SOUNDEX (robert)")[0][0] == "WORD" and _lex("SOUNDEX")[0][0] == "WORD",
    f"{_lex('SOUNDEX(robert)')}")))

SX_ERRORS = [
    ("SOUNDEX(robert", 7, "unmatched '('"),
    ("SOUNDEX(", 7, "unmatched '('"),
    ("SOUNDEX()", 0, "exactly one word"),
    ("SOUNDEX(robert smith)", 0, "exactly one word"),
    ("SOUNDEX(rob*)", 0, "exactly one word"),
    ('SOUNDEX("robert")', 0, "exactly one word"),
    ("SOUNDEX(NOT x)", 0, "exactly one word"),
    ("SOUNDEX(SOUNDEX(x))", 0, "exactly one word"),
    ("SOUNDEX(123)", 0, "ASCII letters"),
    ("linux SOUNDEX(李)", 6, "ASCII letters"),
]
for _q, _pos, _msg in SX_ERRORS:
    def _sxe(q=_q, pos=_pos, msg=_msg):
        try:
            node = parse(q, pre)
        except ValueError as e:
            return f"position {pos}" in str(e) and msg in str(e), f"{e}"
        return False, f"沒有拋 ValueError，得到 {node!r}"

    results.append(run(f"parse({_q!r}) 拋 ValueError（位置 {_pos}）", _sxe))


def _sx_qtf():
    try:
        query_terms(And([T(["linux"]), Soundex("robert")]))
    except ValueError as e:
        return True, f"ValueError: {e}"
    return False, "沒有拋 ValueError"


results.append(run("query_terms 遇到 Soundex 拋 ValueError", _sx_qtf))


def brute_sx(word: str) -> set[str]:
    code = spelling.soundex(word)
    return stems_of(w for w in S_WORDS if w.isascii() and w.isalpha() and spelling.soundex(w) == code)


def _sx_full():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        got = terms_of(expand(parse("SOUNDEX(robert)", pre), reader, limit=10**9))
    exp = brute_sx("robert")
    ok = set(got) == exp and len(got) == len(exp) and {"robert", S_STEM["rupert"]} <= set(got)
    return ok, f"{len(got)} 個 vs 暴力 {len(exp)} 個；前 5 個 {got[:5]}"


results.append(run("expand(SOUNDEX(robert), limit=10**9) == 暴力（R163 的原字 → stem 去重），含 robert、rupert",
                   _sx_full))


def _sx_top():
    out, w = counting(expand, parse("SOUNDEX(robert)", pre), reader)
    got = terms_of(out)
    exp = by_df(brute_sx("robert"))
    n = len(exp)
    ok = (got == exp[:100] and len(got) == 100 and len(w) == 1 and str(n) in w[0] and "SOUNDEX(robert)" in w[0]
          and "robert" in got and S_STEM["rupert"] in got)
    return ok, f"{len(got)} 個；robert 第 {got.index('robert') + 1 if 'robert' in got else '-'}、" \
               f"rupert 第 {got.index(S_STEM['rupert']) + 1 if S_STEM['rupert'] in got else '-'}；警告 {w}"


results.append(run("expand(SOUNDEX(robert)) 預設 limit：100 個、警告 1 次含總數、robert 與 rupert 都在", _sx_top))

for _a, _b in [("smith", "smyth"), ("stephen", "steven")]:
    def _pair(a=_a, b=_b):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ea = set(terms_of(expand(Soundex(a), reader, limit=10**9)))
            eb = set(terms_of(expand(Soundex(b), reader, limit=10**9)))
        ok = a in S_DF and b in S_DF and S_STEM[b] in ea and S_STEM[a] in eb
        return ok, f"{a}({sdf(a)}, {spelling.soundex(a)})／{b}({sdf(b)}, {spelling.soundex(b)})；{len(ea)}、{len(eb)} 個 stem"

    results.append(run(f"SOUNDEX({_a}) 與 SOUNDEX({_b}) 互相包含對方的 stem", _pair))


def _one_table():
    s1 = surface.load_surface(reader).soundex_groups()
    spelling.suggest_soundex("robert", reader)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        expand(Soundex("robert"), reader)
    s2 = surface.load_surface(reader).soundex_groups()
    leftover = [n for n in ("_soundex_table", "_soundex_cache") if hasattr(spelling, n)]
    return s1 is s2 and not leftover, f"同一個物件 {s1 is s2}；spelling 殘留 {leftover}"


results.append(run("SOUNDEX() 與 suggest_soundex 共用同一個對照表；spelling 沒有 _soundex_table／_soundex_cache",
                   _one_table))

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    timing("expand(SOUNDEX(robert))（214 個 stem 取前 100）", lambda: expand(Soundex("robert"), reader), 2)

# ===========================================================================
section("11. did_you_mean 第一次呼叫的成本（全新的 process）")
# ===========================================================================
# 子 process：先 import（spaCy 的載入不算），再量。total 模式量「lexicon 已載入時的第一次 did_you_mean」，
# 也就是 load_surface + 建 k-gram + 查詢；breakdown 模式把三段分開量。
CHILD = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
from writer import IndexReader
import spelling, surface
r = IndexReader(sys.argv[2])
out = {}
t0 = time.perf_counter(); r.vocabulary(); out["lexicon"] = time.perf_counter() - t0
if sys.argv[3] == "total":
    t0 = time.perf_counter(); out["result"] = spelling.did_you_mean("retreival", r)
    out["first"] = time.perf_counter() - t0
    t0 = time.perf_counter(); spelling.did_you_mean("kernal", r); out["second"] = time.perf_counter() - t0
else:
    t0 = time.perf_counter(); sv = surface.load_surface(r); out["load_surface"] = time.perf_counter() - t0
    t0 = time.perf_counter(); sv.kgram(); out["kgram"] = time.perf_counter() - t0
    t0 = time.perf_counter(); spelling.did_you_mean("retreival", r); out["query"] = time.perf_counter() - t0
import resource
out["maxrss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
print(json.dumps(out))
'''


def child(mode: str) -> dict:
    p = subprocess.run([sys.executable, "-c", CHILD, str(SRC), str(INDEX), mode],
                       capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip().splitlines()[-1] if p.stderr.strip() else f"exit {p.returncode}")
    return json.loads(p.stdout.strip().splitlines()[-1])


try:
    runs = [child("total") for _ in range(3)]
    firsts = [r_["first"] for r_ in runs]
    timings.append(f"did_you_mean('retreival') 第一次呼叫（新 process，lexicon 已載入）：{statistics.median(firsts):.2f} s"
                   f"（3 次中位數，各次 {', '.join(f'{x:.2f}' for x in firsts)} s）；"
                   f"同一 process 的第二次呼叫 {statistics.median(r_['second'] for r_ in runs) * 1000:.0f} ms；"
                   f"讀 lexicon（不算在內）{statistics.median(r_['lexicon'] for r_ in runs):.2f} s；"
                   f"結果 {runs[0]['result']}；峰值 RSS {statistics.median(r_['maxrss_mb'] for r_ in runs):.0f} MB")
    br = [child("breakdown") for _ in range(3)]
    timings.append("　拆開量（新 process，3 次中位數）："
                   + "、".join(f"{k} {statistics.median(b[k] for b in br) * (1000 if k == 'query' else 1):.2f}"
                               f"{' ms' if k == 'query' else ' s'}" for k in ("load_surface", "kgram", "query")))
    results.append(check("新 process 中 did_you_mean('retreival') == ['retrieval', …]",
                         bool(runs[0]["result"]) and runs[0]["result"][0] == "retrieval", f"{runs[0]['result']}"))
except Exception as e:  # noqa: BLE001
    timings.append(f"did_you_mean 第一次呼叫（新 process）：{type(e).__name__}: {e}")
    results.append(check("新 process 中 did_you_mean('retreival') == ['retrieval', …]", False, f"{e}"))

# ===========================================================================
section("計時（不設門檻）")
# ===========================================================================
for line in timings:
    print(f"  {line}")

# ===========================================================================
section("Test Summary")
# ===========================================================================
all_passed = all(results)
print(f"\n  {sum(results)}/{len(results)} passed")
print(f"  Overall: {'ALL PASSED ✓' if all_passed else 'SOME FAILED ✗'}\n")
sys.exit(0 if all_passed else 1)
