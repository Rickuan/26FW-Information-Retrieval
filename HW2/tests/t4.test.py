"""t4.test.py — T4 核心（T4a）：parse、_prune、query_terms、expand（原樣回傳）

執行：
  uv run python HW2/tests/t4.test.py

T4b 合併後本檔必須照樣全部通過，所以這裡只測 T4a 的行為，
不測加分語法暫時拋出的 NotImplementedError。
"""
from __future__ import annotations

import sys
import warnings
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
INDEX = ROOT / "index"
sys.path.insert(0, str(SRC))

from parser import And, Near, Not, Or, Phrase, Term, Wildcard, expand, parse, query_terms

try:
    from parser import _lex
except ImportError:  # stub 狀態還沒有 _lex：記為 FAIL，不中斷
    def _lex(query):
        raise NotImplementedError("_lex")
from tokenizer import Preprocessor
from writer import IndexReader

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


def parse_counting(query: str):
    """回傳 (AST, 警告次數)。必須 simplefilter("always")，否則同位置同訊息的警告會被合併。"""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        node = parse(query, pre)
    return node, len(w)


T = Term
reader = IndexReader(INDEX)
pre = Preprocessor.from_config(reader.get_metadata()["preprocessor"])

results: list[bool] = []

# (query, 預期 AST, 預期 query_terms（AST 為 None 時是 None）, 預期警告次數)
CASES = [
    ("Microsoft", T(["microsoft"]), Counter(microsoft=1), 0),
    ("United States government", T(["unit", "state", "govern"]), Counter(unit=1, state=1, govern=1), 0),
    ("open source AND Linux", And([T(["open", "sourc"]), T(["linux"])]), Counter(open=1, sourc=1, linux=1), 0),
    ("software engineer OR project manager",
     Or([T(["softwar", "engin"]), T(["project", "manag"])]),
     Counter(softwar=1, engin=1, project=1, manag=1), 0),
    ("a AND b OR c", Or([T(["b"]), T(["c"])]), Counter(b=1, c=1), 1),
    ("linux AND kernel OR windows",
     Or([And([T(["linux"]), T(["kernel"])]), T(["window"])]), Counter(linux=1, kernel=1, window=1), 0),
    ("windows OR linux AND kernel",
     Or([T(["window"]), And([T(["linux"]), T(["kernel"])])]), Counter(linux=1, kernel=1, window=1), 0),
    ("e-mail", T(["e", "mail"]), Counter(e=1, mail=1), 0),
    ("new new york", T(["new", "new", "york"]), Counter(new=2, york=1), 0),
    ("open and linux", T(["open", "linux"]), Counter(open=1, linux=1), 0),
    ("ANDROID linux", T(["android", "linux"]), Counter(android=1, linux=1), 0),
    ("", None, None, 0),
    ("   ", None, None, 0),
    ("the of", None, None, 1),
    ("AND", None, None, 2),
    ("AND linux", T(["linux"]), Counter(linux=1), 1),
    ("linux OR", T(["linux"]), Counter(linux=1), 1),
    ("linux AND OR kernel", Or([T(["linux"]), T(["kernel"])]), Counter(linux=1, kernel=1), 1),
    ("linux OR the AND kernel", Or([T(["linux"]), T(["kernel"])]), Counter(linux=1, kernel=1), 1),
    ("linux AND the AND kernel", And([T(["linux"]), T(["kernel"])]), Counter(linux=1, kernel=1), 1),
    ("linux OR linux", Or([T(["linux"]), T(["linux"])]), Counter(linux=2), 0),
]


def tokens_of(node) -> list[str]:
    """測試用：收集樹中所有 token（只處理核心會出現的 Term／And／Or）。"""
    if node is None:
        return []
    if isinstance(node, Term):
        return list(node.tokens)
    return [t for c in node.children for t in tokens_of(c)]


# ===========================================================================
section("parse：AST 與警告次數（§4.2 表）")
# ===========================================================================
parsed: dict[str, object] = {}

for q, exp_ast, _qtf, exp_warn in CASES:
    def _go(q=q, exp_ast=exp_ast, exp_warn=exp_warn):
        node, n = parse_counting(q)
        parsed[q] = node
        ok = node == exp_ast and n == exp_warn
        return ok, f"got {node!r}, warnings={n}"
    results.append(run(f"parse({q!r}) == {exp_ast!r}，警告 {exp_warn} 次", _go))


# ===========================================================================
section("query_terms（§4.2 表）")
# ===========================================================================
for q, exp_ast, exp_qtf, _w in CASES:
    if exp_ast is None:
        continue

    def _go(q=q, exp_qtf=exp_qtf):
        node, _ = parse_counting(q)
        got = query_terms(node)
        return got == exp_qtf, f"got {dict(got)}"
    results.append(run(f"query_terms(parse({q!r})) == {dict(exp_qtf)}", _go))


# ===========================================================================
section("dictionary、expand")
# ===========================================================================
def _in_dict():
    toks = sorted({t for _q, ast, _c, _w in CASES for t in tokens_of(ast)})
    missing = [t for t in toks if t not in reader]
    return not missing, f"{len(toks)} 個 token，缺少 {missing}"


results.append(run("表中所有 token 都在 dictionary（t in reader）", _in_dict))


def _expand_identity():
    bad = []
    for q, _ast, _c, _w in CASES:
        node, _ = parse_counting(q)
        if expand(node, reader) != node:
            bad.append(q)
    return not bad, f"不符 {bad}"


results.append(run("expand(node, reader) == node（表中每一列）", _expand_identity))
results.append(run("expand(None, reader) is None", lambda: (expand(None, reader) is None, "")))


def _expand_no_mutation():
    node, _ = parse_counting("linux AND kernel OR windows")
    snapshot = Or([And([T(["linux"]), T(["kernel"])]), T(["window"])])
    expand(node, reader)
    return node == snapshot, f"{node!r}"


results.append(run("expand 不修改傳入的樹", _expand_no_mutation))


# ===========================================================================
section("query_terms：手建節點的其他分支")
# ===========================================================================
results.append(run("query_terms(Not(T(['linux']))) == Counter()",
                   lambda: ((g := query_terms(Not(T(["linux"])))) == Counter(), f"got {dict(g)}")))


def _mixed():
    node = And([
        Phrase(["open", "sourc"], [1, 2]),
        Near(Phrase(["linux"], [1]), Phrase(["kernel"], [1]), 5),
        Not(T(["window"])),
    ])
    got = query_terms(node)
    return got == Counter(open=1, sourc=1, linux=1, kernel=1), f"got {dict(got)}"


results.append(run("And[Phrase, Near, Not] → open、sourc、linux、kernel 各 1", _mixed))


def _near_multi():
    got = query_terms(Near(Phrase(["e", "mail"], [1, 2]), Phrase(["server"], [1]), 5))
    return got == Counter(e=1, mail=1, server=1), f"got {dict(got)}"


results.append(run("Near(Phrase(e mail), Phrase(server)) → e、mail、server 各 1", _near_multi))


def _wildcard_raises():
    try:
        query_terms(Wildcard("comput"))
    except ValueError as e:
        return True, f"ValueError: {e}"
    return False, "沒有拋 ValueError"


results.append(run("query_terms(Wildcard('comput')) 拋 ValueError", _wildcard_raises))


# ===========================================================================
section("parse 不讀 index、lexer")
# ===========================================================================
def _no_index():
    # 只用 Preprocessor（不經 reader）建出的實例就能跑完整張表
    p2 = Preprocessor(casefold=True, stopword=True, stem=True)
    bad = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for q, exp_ast, _c, _w in CASES:
            if parse(q, p2) != exp_ast:
                bad.append(q)
    return not bad, f"不符 {bad}"


results.append(run("parse 只用 Preprocessor 就能跑完上表", _no_index))


def _lex_kinds():
    q = 'linux AND (kernel OR "open source") NOT win* /5 ANDROID and Or'
    got = [(k, t, p) for k, t, p in _lex(q)]
    exp = [
        ("WORD", "linux", 0), ("AND", "AND", 6), ("(", "(", 10), ("WORD", "kernel", 11),
        ("OR", "OR", 18), ("PHRASE", '"open source"', 21), (")", ")", 34), ("NOT", "NOT", 36),
        ("WILDCARD", "win*", 40), ("NEAR", "/5", 45), ("WORD", "ANDROID", 48),
        ("WORD", "and", 56), ("WORD", "Or", 60),
    ]
    return got == exp, f"got {got}"


results.append(run("_lex 辨識全部 token 類型與字元位置", _lex_kinds))

# ===========================================================================
section("Test Summary")
# ===========================================================================
all_passed = all(results)
print(f"\n  {sum(results)}/{len(results)} passed")
print(f"  Overall: {'ALL PASSED ✓' if all_passed else 'SOME FAILED ✗'}\n")
sys.exit(0 if all_passed else 1)
