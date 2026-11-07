"""t4_bonus.test.py — T4 加分（T4b）：NOT、括號、Phrase、Near、Wildcard／expand、
position_match、suggest、soundex／suggest_soundex

執行：
  uv run python HW2/tests/t4_bonus.test.py

position_match 的預期值一律由本檔內的暴力掃描算出（直接讀 get_postings 的 positions，
不 import positional.py 的 helper，也不拿 position_match 的結果當預期值）。
計時只列出數字，不設門檻（T4.md §6.7）。
"""
from __future__ import annotations

import statistics
import sys
import time
import tracemalloc
import warnings
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
INDEX = ROOT / "index"
sys.path.insert(0, str(SRC))

from parser import And, Near, Not, Or, Phrase, Term, Wildcard, expand, parse, query_terms
from tokenizer import Preprocessor
from writer import IndexReader
import positional
import spelling

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
    ("Comput*", Wildcard("comput"), None, 0),
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
    ("comput* OR linux", Or([Wildcard("comput"), T(["linux"])]), None, 0),
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
          and terms[0] == T(["comput"]) and not w and repr(node) == before and node == Wildcard("comput"))
    return ok, f"{len(terms)} 個 Term，第一個 {terms[:1]}，{len(w)} 警告，原樹 {node!r}"


results.append(run("comput* → Or 64 個 Term，第一個 comput，無警告，原樹不變", _comput))


def _comput_order():
    out = expand(parse("comput*", pre), reader)
    got = [t.tokens[0] for t in out.children]
    # 預期順序獨立算：直接掃 vocabulary() 找 prefix（不經過 prefix_terms），再依 (-df, term) 排序
    df = reader.df
    exp = sorted((t for t in reader.vocabulary() if t.startswith("comput")), key=lambda t: (-df(t), t))
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
    exp = [T([t]) for t in sorted(reader.prefix_terms("a"), key=lambda t: (-reader.df(t), t))[:3]]
    return isinstance(out, Or) and out.children == exp and len(w) == 1, f"got {out!r}"


results.append(run("expand(a*, limit=3) 取前 3 個", _a_limit))


def _computing():
    out, w = counting(expand, parse("computing*", pre), reader)
    out2, w2 = counting(expand, parse("linux OR computing*", pre), reader)
    return (out is None and len(w) == 1 and out2 == T(["linux"]) and len(w2) == 1), \
        f"{out!r}/{len(w)} 警告；{out2!r}/{len(w2)} 警告"


results.append(run("computing* → None（警告 1 次）；linux OR computing* → T(['linux'])", _computing))


def _single():
    # dictionary 中只有一個以此開頭的 term 時，結果是 Term 而不是 Or
    vocab = reader.vocabulary()
    prefix = next(t for t in vocab[1000:] if t.isalpha() and len(t) >= 6 and len(reader.prefix_terms(t)) == 1)
    out = expand(Wildcard(prefix), reader)
    return out == T([prefix]), f"prefix {prefix!r} → {out!r}"


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
timing("expand(comput*)（64 個）", lambda: expand(Wildcard("comput"), reader), 3)
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    timing("expand(a*)（31,236 個取前 100）", lambda: expand(Wildcard("a"), reader), 3)

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
section("5. 拼字建議 suggest")
# ===========================================================================
vocab = reader.vocabulary()
vocab_len, vocab_head = len(vocab), list(vocab[:20])

t0 = time.perf_counter()
tracemalloc.start()
try:
    first = spelling.suggest("retreival", reader)
    _cur, _peak = tracemalloc.get_traced_memory()
except Exception as e:  # noqa: BLE001
    first, _cur, _peak = e, 0, 0
tracemalloc.stop()
build_s = time.perf_counter() - t0
timings.append(f"k-gram index 建置（含第一次 suggest，tracemalloc 開啟）：{build_s:.2f} s，"
               f"建置後仍占用 {_cur / 2**20:.1f} MiB／峰值 {_peak / 2**20:.1f} MiB")
try:  # 不開 tracemalloc 重建一次，量純時間
    spelling._kgram_cache.clear()
    t0 = time.perf_counter()
    spelling.suggest("retreival", reader)
    timings.append(f"k-gram index 建置（含第一次 suggest，不開 tracemalloc）：{time.perf_counter() - t0:.2f} s")
except Exception as e:  # noqa: BLE001
    timings.append(f"k-gram index 建置（不開 tracemalloc）：{type(e).__name__}")


def _retreival():
    s = spelling.suggest("retreival", reader)
    return "retriev" in s[:3], f"{s}"


results.append(run("retriev 在 suggest('retreival') 前 3 名", _retreival))


def _retreiv():
    s = spelling.suggest("retreiv", reader)
    return bool(s) and s[0] == "retriev", f"{s}"


results.append(run("suggest('retreiv')[0] == 'retriev'", _retreiv))


def _shape():
    bad = []
    for w in ["retreival", "retreiv", "linux", "kernal", "comput", "zzzzqqqx"]:
        s = spelling.suggest(w, reader)
        if w in s or len(s) > 5 or len(s) != len(set(s)):
            bad.append((w, s))
    s3 = spelling.suggest("linux", reader, limit=3)
    return not bad and len(s3) <= 3, f"{bad} / limit=3 → {s3}"


results.append(run("結果不含輸入本身、長度 ≤ limit、沒有重複", _shape))


def _sorted():
    # 結果依 (OSA 距離, -df, term) 排序；距離另外用 Levenshtein + 相鄰對調的簡單版重算
    def osa(a, b):
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

    s = spelling.suggest("retreival", reader)
    keys = [(osa("retreival", t), -reader.df(t), t) for t in s]
    return keys == sorted(keys), f"{keys}"


results.append(run("suggest 依 (OSA 距離, -df, term) 排序", _sorted))


def _vocab_untouched():
    v = reader.vocabulary()
    return len(v) == vocab_len and v[:20] == vocab_head and v is vocab, f"{len(v)} vs {vocab_len}"


results.append(run("suggest 前後 reader.vocabulary() 沒有被修改", _vocab_untouched))


def _trigger():
    df_tok, df_s = reader.df("retreiv"), reader.df("retriev")
    df_lx, df_lu = reader.df("linux"), reader.df("linu")
    s1, s2 = spelling.suggest("retreiv", reader), spelling.suggest("linux", reader)

    def fires(tok, s):
        return bool(s) and (reader.df(tok) == 0 or reader.df(s[0]) >= reader.df(tok) * 10)

    ok = ((df_tok, df_s, df_lx, df_lu) == (11, 409, 997, 28) and s1[0] == "retriev" and fires("retreiv", s1)
          and s2[0] == "linu" and not fires("linux", s2))
    return ok, f"df {df_tok}/{df_s}/{df_lx}/{df_lu}；retreiv→{s1[:1]} 觸發 {fires('retreiv', s1)}；linux→{s2[:1]} 觸發 {fires('linux', s2)}"


results.append(run("觸發條件：retreiv 觸發、linux 不觸發", _trigger))
for _w in ["retreival", "linux", "a", "comput"]:
    timing(f"suggest({_w!r})（快取後）", lambda _w=_w: spelling.suggest(_w, reader))

# ===========================================================================
section("6. Soundex")
# ===========================================================================
SOUNDEX = {"Robert": "R163", "Rupert": "R163", "Ashcraft": "A261", "Tymczak": "T522",
           "Pfister": "P236", "Honeyman": "H555", "Lee": "L000", "Tymczak".lower(): "T522"}
for w, code in SOUNDEX.items():
    results.append(run(f"soundex({w!r}) == {code!r}", lambda w=w, code=code: (spelling.soundex(w) == code,
                                                                           f"got {spelling.soundex(w)!r}")))

t0 = time.perf_counter()
try:
    spelling.suggest_soundex("linux", reader)
    timings.append(f"Soundex 對照表建置（含第一次 suggest_soundex）：{time.perf_counter() - t0:.2f} s")
except Exception as e:  # noqa: BLE001
    timings.append(f"Soundex 對照表建置：{type(e).__name__}")


def _sx_suggest():
    s = spelling.suggest_soundex("retreiv", reader)
    return "retriev" in s and "retreiv" not in s and len(s) <= 5, f"{s}"


results.append(run("'retriev' in suggest_soundex('retreiv')，不含本身", _sx_suggest))


def _sx_sorted():
    s = spelling.suggest_soundex("retreiv", reader, limit=20)
    keys = [(-reader.df(t), t) for t in s]
    return keys == sorted(keys) and all(spelling.soundex(t) == "R361" and t.isalpha() for t in s), f"{s}"


results.append(run("suggest_soundex 依 (-df, term) 排序、碼都相同、只有純字母", _sx_sorted))
timing("suggest_soundex('retreiv')（快取後）", lambda: spelling.suggest_soundex("retreiv", reader))

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
