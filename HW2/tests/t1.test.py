"""t1.test.py — T1 核心：IndexReader.N / df() 與 Preprocessor.from_config()

執行：
  uv run python HW2/tests/t1.test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# 確保可以 import HW2/src 的模組
SRC = Path(__file__).resolve().parent.parent / "src"
INDEX = Path(__file__).resolve().parent.parent / "index"
sys.path.insert(0, str(SRC))

from tokenizer import Preprocessor
from writer import IndexReader

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


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


def raises_value_error(cfg, must_contain: tuple[str, ...] = ()):
    try:
        Preprocessor.from_config(cfg)
    except ValueError as e:
        msg = str(e)
        ok = all(s in msg for s in must_contain)
        return ok, f"ValueError: {msg}"
    return False, "未拋出 ValueError"


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def lexicon_first_last() -> tuple[str, str]:
    """直接讀 lexicon.tsv 取第一個與最後一個 term（不經 IndexReader）。"""
    with (INDEX / "lexicon.tsv").open("r", encoding="utf-8", newline="") as f:
        first = last = None
        for line in f:
            term = line.split("\t", 1)[0]
            if first is None:
                first = term
            last = term
    return first, last


reader = IndexReader(INDEX)
metadata = reader.get_metadata()
cfg = metadata["preprocessor"]
results: list[bool] = []

# ===========================================================================
section("IndexReader.N / df()")
# ===========================================================================
results.append(run("reader.N == 34786", lambda: (reader.N == 34786, f"N={reader.N}")))
results.append(run("df('linux') == 997", lambda: (reader.df("linux") == 997, f"df={reader.df('linux')}")))
results.append(run("df('sourc') == 4062", lambda: (reader.df("sourc") == 4062, f"df={reader.df('sourc')}")))
results.append(run("df('不存在的詞') == 0", lambda: (reader.df("不存在的詞") == 0, f"df={reader.df('不存在的詞')}")))

first, last = lexicon_first_last()
for t in ["linux", "sourc", "open", first, last]:
    def _df_matches(t=t):
        d, n = reader.df(t), len(reader.get_postings(t))
        return d == n and d > 0, f"df={d}, len(postings)={n}"
    results.append(run(f"df({t!r}) == len(get_postings({t!r}))", _df_matches))

# ===========================================================================
section("Preprocessor.from_config()")
# ===========================================================================
def _query_terms():
    pre = Preprocessor.from_config(cfg)
    terms = [t for _, t in pre.process("open source AND Linux")]
    return terms == ["open", "sourc", "linux"], f"terms={terms}"


def _flags_match():
    pre = Preprocessor.from_config(cfg)
    got = {k: getattr(pre, k) for k in ("casefold", "stopword", "stem", "lemma")}
    return got == cfg, f"got={got}, metadata={cfg}"


def _lemma_default():
    pre = Preprocessor.from_config({"casefold": True, "stopword": True, "stem": True})
    return pre.lemma is False, f"lemma={pre.lemma!r}"


results.append(run("'open source AND Linux' → ['open', 'sourc', 'linux']", _query_terms))
results.append(run("casefold/stopword/stem/lemma 與 metadata 完全一致", _flags_match))
results.append(run("缺 lemma 不報錯且 .lemma is False", _lemma_default))
results.append(run("from_config({}) 拋出 ValueError", lambda: raises_value_error({})))
results.append(run("from_config(None) 拋出 ValueError", lambda: raises_value_error(None)))
results.append(run(
    "from_config({'casefold': True}) 拋出 ValueError，訊息含 stopword、stem",
    lambda: raises_value_error({"casefold": True}, ("stopword", "stem")),
))

# ===========================================================================
section("process 重構（T4.md §6.8.1 第 3 步：抽出 normalize_token，行為不變）")
# ===========================================================================
# golden 值是在重構之前，用當時的 Preprocessor.process 對下列輸入產生的字面常數
# （§4.2、§6.7 表中的 query，以及 §6.8.1 列出的邊界輸入）。重構前後都必須通過。
from unittest import mock

from tokenizer import tokenize

PROCESS_GOLDEN_INPUTS = [
    'Microsoft',
    'United States government',
    'open source AND Linux',
    'software engineer OR project manager',
    'a AND b OR c',
    'linux AND kernel OR windows',
    'windows OR linux AND kernel',
    'e-mail',
    'new new york',
    'open and linux',
    'ANDROID linux',
    '',
    '   ',
    'the of',
    'AND',
    'AND linux',
    'linux OR',
    'linux AND OR kernel',
    'linux OR the AND kernel',
    'linux AND the AND kernel',
    'linux OR linux',
    '(linux OR windows) AND kernel',
    'linux AND NOT windows',
    'linux NOT windows',
    'NOT linux',
    '"open source" AND linux',
    '"lord of the rings"',
    'linux /5 kernel',
    'e-mail /5 server',
    'the /3 linux',
    '"open source" /3 the',
    'NOT (a OR b)',
    '((linux))',
    '"linux"',
    '(linux AND kernel) AND window',
    'Comput*',
    'lord of the rings',
    '10am',
    'ID',
    'cannot',
    "O'Brien's",
    'U.S.A.',
    'see https://www.example.com/path?q=1 now',
    "don't",
    'Running RUNS ran',
    'Café',
    'the of and a',
    'e-mail /5 server and 100kb 0.5mm h.o.o.q id im',
]
PROCESS_GOLDEN = {
    'hw2': [
        [(1, 'microsoft')],
        [(1, 'unit'), (2, 'state'), (3, 'govern')],
        [(1, 'open'), (2, 'sourc'), (4, 'linux')],
        [(1, 'softwar'), (2, 'engin'), (4, 'project'), (5, 'manag')],
        [(3, 'b'), (5, 'c')],
        [(1, 'linux'), (3, 'kernel'), (5, 'window')],
        [(1, 'window'), (3, 'linux'), (5, 'kernel')],
        [(1, 'e'), (2, 'mail')],
        [(1, 'new'), (2, 'new'), (3, 'york')],
        [(1, 'open'), (3, 'linux')],
        [(1, 'android'), (2, 'linux')],
        [],
        [],
        [],
        [],
        [(2, 'linux')],
        [(1, 'linux')],
        [(1, 'linux'), (4, 'kernel')],
        [(1, 'linux'), (5, 'kernel')],
        [(1, 'linux'), (5, 'kernel')],
        [(1, 'linux'), (3, 'linux')],
        [(1, 'linux'), (3, 'window'), (5, 'kernel')],
        [(1, 'linux'), (4, 'window')],
        [(1, 'linux'), (3, 'window')],
        [(2, 'linux')],
        [(1, 'open'), (2, 'sourc'), (4, 'linux')],
        [(1, 'lord'), (4, 'ring')],
        [(1, 'linux'), (2, '5'), (3, 'kernel')],
        [(1, 'e'), (2, 'mail'), (3, '5'), (4, 'server')],
        [(2, '3'), (3, 'linux')],
        [(1, 'open'), (2, 'sourc'), (3, '3')],
        [(4, 'b')],
        [(1, 'linux')],
        [(1, 'linux')],
        [(1, 'linux'), (3, 'kernel'), (5, 'window')],
        [(1, 'comput')],
        [(1, 'lord'), (4, 'ring')],
        [(1, '10')],
        [(1, 'id')],
        [],
        [(1, "o'brien")],
        [(1, 'usa')],
        [(1, 'see'), (2, 'https://www.example.com/path?q=1')],
        [],
        [(1, 'run'), (2, 'run'), (3, 'ran')],
        [(1, 'café')],
        [],
        [(1, 'e'), (2, 'mail'), (3, '5'), (4, 'server'), (6, '100'), (7, 'kb'), (8, '0.5'), (9, 'mm'), (10, 'hooq')],
    ],
    'hw1': [
        [(1, 'microsoft')],
        [(1, 'united'), (2, 'states'), (3, 'government')],
        [(1, 'open'), (2, 'source'), (3, 'and'), (4, 'linux')],
        [(1, 'software'), (2, 'engineer'), (3, 'or'), (4, 'project'), (5, 'manager')],
        [(1, 'a'), (2, 'and'), (3, 'b'), (4, 'or'), (5, 'c')],
        [(1, 'linux'), (2, 'and'), (3, 'kernel'), (4, 'or'), (5, 'windows')],
        [(1, 'windows'), (2, 'or'), (3, 'linux'), (4, 'and'), (5, 'kernel')],
        [(1, 'e'), (2, 'mail')],
        [(1, 'new'), (2, 'new'), (3, 'york')],
        [(1, 'open'), (2, 'and'), (3, 'linux')],
        [(1, 'android'), (2, 'linux')],
        [],
        [],
        [(1, 'the'), (2, 'of')],
        [(1, 'and')],
        [(1, 'and'), (2, 'linux')],
        [(1, 'linux'), (2, 'or')],
        [(1, 'linux'), (2, 'and'), (3, 'or'), (4, 'kernel')],
        [(1, 'linux'), (2, 'or'), (3, 'the'), (4, 'and'), (5, 'kernel')],
        [(1, 'linux'), (2, 'and'), (3, 'the'), (4, 'and'), (5, 'kernel')],
        [(1, 'linux'), (2, 'or'), (3, 'linux')],
        [(1, 'linux'), (2, 'or'), (3, 'windows'), (4, 'and'), (5, 'kernel')],
        [(1, 'linux'), (2, 'and'), (3, 'not'), (4, 'windows')],
        [(1, 'linux'), (2, 'not'), (3, 'windows')],
        [(1, 'not'), (2, 'linux')],
        [(1, 'open'), (2, 'source'), (3, 'and'), (4, 'linux')],
        [(1, 'lord'), (2, 'of'), (3, 'the'), (4, 'rings')],
        [(1, 'linux'), (2, '5'), (3, 'kernel')],
        [(1, 'e'), (2, 'mail'), (3, '5'), (4, 'server')],
        [(1, 'the'), (2, '3'), (3, 'linux')],
        [(1, 'open'), (2, 'source'), (3, '3'), (4, 'the')],
        [(1, 'not'), (2, 'a'), (3, 'or'), (4, 'b')],
        [(1, 'linux')],
        [(1, 'linux')],
        [(1, 'linux'), (2, 'and'), (3, 'kernel'), (4, 'and'), (5, 'window')],
        [(1, 'comput')],
        [(1, 'lord'), (2, 'of'), (3, 'the'), (4, 'rings')],
        [(1, '10'), (2, 'am')],
        [(1, 'id')],
        [(1, 'can'), (2, 'not')],
        [(1, "o'brien")],
        [(1, 'usa')],
        [(1, 'see'), (2, 'https://www.example.com/path?q=1'), (3, 'now')],
        [(1, "don't")],
        [(1, 'running'), (2, 'runs'), (3, 'ran')],
        [(1, 'café')],
        [(1, 'the'), (2, 'of'), (3, 'and'), (4, 'a')],
        [(1, 'e'), (2, 'mail'), (3, '5'), (4, 'server'), (5, 'and'), (6, '100'), (7, 'kb'), (8, '0.5'), (9, 'mm'), (10, 'hooq'), (11, 'i'), (12, 'd'), (13, 'i'), (14, 'm')],
    ],
    'nocase': [
        [(1, 'Microsoft')],
        [(1, 'Unite'), (2, 'State'), (3, 'govern')],
        [(1, 'open'), (2, 'sourc'), (4, 'Linux')],
        [(1, 'softwar'), (2, 'engin'), (4, 'project'), (5, 'manag')],
        [(3, 'b'), (5, 'c')],
        [(1, 'linux'), (3, 'kernel'), (5, 'window')],
        [(1, 'window'), (3, 'linux'), (5, 'kernel')],
        [(1, 'e'), (2, 'mail')],
        [(1, 'new'), (2, 'new'), (3, 'york')],
        [(1, 'open'), (3, 'linux')],
        [(1, 'ANDROID'), (2, 'linux')],
        [],
        [],
        [],
        [],
        [(2, 'linux')],
        [(1, 'linux')],
        [(1, 'linux'), (4, 'kernel')],
        [(1, 'linux'), (5, 'kernel')],
        [(1, 'linux'), (5, 'kernel')],
        [(1, 'linux'), (3, 'linux')],
        [(1, 'linux'), (3, 'window'), (5, 'kernel')],
        [(1, 'linux'), (4, 'window')],
        [(1, 'linux'), (3, 'window')],
        [(2, 'linux')],
        [(1, 'open'), (2, 'sourc'), (4, 'linux')],
        [(1, 'lord'), (4, 'ring')],
        [(1, 'linux'), (2, '5'), (3, 'kernel')],
        [(1, 'e'), (2, 'mail'), (3, '5'), (4, 'server')],
        [(2, '3'), (3, 'linux')],
        [(1, 'open'), (2, 'sourc'), (3, '3')],
        [(4, 'b')],
        [(1, 'linux')],
        [(1, 'linux')],
        [(1, 'linux'), (3, 'kernel'), (5, 'window')],
        [(1, 'Comput')],
        [(1, 'lord'), (4, 'ring')],
        [(1, '10')],
        [(1, 'ID')],
        [],
        [(1, "O'Brien")],
        [(1, 'USA')],
        [(1, 'see'), (2, 'https://www.example.com/path?q=1')],
        [],
        [(1, 'Run'), (2, 'RUNS'), (3, 'ran')],
        [(1, 'Café')],
        [],
        [(1, 'e'), (2, 'mail'), (3, '5'), (4, 'server'), (6, '100'), (7, 'kb'), (8, '0.5'), (9, 'mm'), (10, 'hooq')],
    ],
    'lemma': [
        [(1, 'microsoft')],
        [(1, 'united'), (2, 'state'), (3, 'government')],
        [(1, 'open'), (2, 'source'), (4, 'linux')],
        [(1, 'software'), (2, 'engineer'), (4, 'project'), (5, 'manager')],
        [(3, 'b'), (5, 'c')],
        [(1, 'linux'), (3, 'kernel'), (5, 'window')],
        [(1, 'window'), (3, 'linux'), (5, 'kernel')],
        [(1, 'e'), (2, 'mail')],
        [(1, 'new'), (2, 'new'), (3, 'york')],
        [(1, 'open'), (3, 'linux')],
        [(1, 'android'), (2, 'linux')],
        [],
        [],
        [],
        [],
        [(2, 'linux')],
        [(1, 'linux')],
        [(1, 'linux'), (4, 'kernel')],
        [(1, 'linux'), (5, 'kernel')],
        [(1, 'linux'), (5, 'kernel')],
        [(1, 'linux'), (3, 'linux')],
        [(1, 'linux'), (3, 'window'), (5, 'kernel')],
        [(1, 'linux'), (4, 'window')],
        [(1, 'linux'), (3, 'window')],
        [(2, 'linux')],
        [(1, 'open'), (2, 'source'), (4, 'linux')],
        [(1, 'lord'), (4, 'ring')],
        [(1, 'linux'), (2, '5'), (3, 'kernel')],
        [(1, 'e'), (2, 'mail'), (3, '5'), (4, 'server')],
        [(2, '3'), (3, 'linux')],
        [(1, 'open'), (2, 'source'), (3, '3')],
        [(4, 'b')],
        [(1, 'linux')],
        [(1, 'linux')],
        [(1, 'linux'), (3, 'kernel'), (5, 'window')],
        [(1, 'comput')],
        [(1, 'lord'), (4, 'ring')],
        [(1, '10')],
        [(1, 'id')],
        [],
        [(1, "o'brien")],
        [(1, 'usa')],
        [(1, 'see'), (2, 'https://www.example.com/path?q=1')],
        [],
        [(1, 'running'), (2, 'run'), (3, 'ran')],
        [(1, 'café')],
        [],
        [(1, 'e'), (2, 'mail'), (3, '5'), (4, 'server'), (6, '100'), (7, 'kb'), (8, '0.5'), (9, 'mm'), (10, 'hooq')],
    ],
}

PROCESS_CONFIGS = {
    "hw2": {"casefold": True, "stopword": True, "stem": True, "lemma": False},
    "hw1": {"casefold": True, "stopword": False, "stem": False, "lemma": False},
    "nocase": {"casefold": False, "stopword": True, "stem": True, "lemma": False},
    "lemma": {"casefold": True, "stopword": True, "stem": False, "lemma": True},
}


def _wordnet_available() -> bool:
    """只檢查本機是否已有 wordnet，不觸發下載。"""
    import nltk
    try:
        nltk.data.find("corpora/wordnet")
    except LookupError:
        try:
            nltk.data.find("corpora/wordnet.zip")
        except LookupError:
            return False
    return True


def _first_diff(got: list, want: list) -> str:
    for i, (g, w) in enumerate(zip(got, want)):
        if g != w:
            return f"第一個不同：{PROCESS_GOLDEN_INPUTS[i]!r} got {g!r}, want {w!r}"
    return f"長度不同：{len(got)} vs {len(want)}"


for name, pcfg in PROCESS_CONFIGS.items():
    if name == "lemma" and not _wordnet_available():
        print(f"  [SKIP] {name}：本機沒有 wordnet，略過 lemma 設定")
        continue
    ppre = Preprocessor(**pcfg)

    def _golden(ppre=ppre, name=name):
        got = [ppre.process(s) for s in PROCESS_GOLDEN_INPUTS]
        want = PROCESS_GOLDEN[name]
        return got == want, f"{len(want)} 個輸入" if got == want else _first_diff(got, want)

    def _compose(ppre=ppre):
        bad = []
        for s in PROCESS_GOLDEN_INPUTS:
            want = [(p, n) for p, t in enumerate(tokenize(s), 1)
                    if (n := ppre.normalize_token(t)) is not None]
            if ppre.process(s) != want:
                bad.append(s)
        return not bad, f"不一致 {len(bad)} 個" + (f"：{bad[:5]!r}" if bad else "")

    def _calls(ppre=ppre):
        bad = []
        with mock.patch.object(ppre, "normalize_token", wraps=ppre.normalize_token) as spy:
            for s in PROCESS_GOLDEN_INPUTS:
                spy.reset_mock()
                ppre.process(s)
                if spy.call_count != len(tokenize(s)):
                    bad.append((s, spy.call_count, len(tokenize(s))))
        return not bad, f"呼叫次數不符 {len(bad)} 個" + (f"：{bad[:3]!r}" if bad else "")

    results.append(run(f"[{name}] process 與重構前的 golden 值相同", _golden))
    results.append(run(f"[{name}] process == normalize_token 套在 tokenize 的每個 token 上", _compose))
    results.append(run(f"[{name}] process 對每個 token 呼叫 normalize_token 一次", _calls))

# ===========================================================================
section("Test Summary")
# ===========================================================================
all_passed = all(results)
print(f"\n  {sum(results)}/{len(results)} passed")
print(f"  Overall: {'ALL PASSED ✓' if all_passed else 'SOME FAILED ✗'}\n")
sys.exit(0 if all_passed else 1)
