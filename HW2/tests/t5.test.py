"""t5.test.py — T5 核心：Boolean 求值引擎 (evaluate) 與候選文件集合產出

執行：
  uv run python HW2/tests/t5.test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
INDEX = ROOT / "index"
sys.path.insert(0, str(SRC))

from boolean import evaluate, intersect_postings
from parser import And, Near, Not, Or, Phrase, Soundex, Term, Wildcard, expand, parse
from tokenizer import Preprocessor
from writer import IndexReader

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


def check(name: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))
    return condition


def run(name: str, fn) -> bool:
    """執行 fn() -> (condition, detail)；例外視為 FAIL，不中斷。"""
    try:
        cond, detail = fn()
    except Exception as e:  # noqa: BLE001
        return check(name, False, f"{type(e).__name__}: {e}")
    return check(name, cond, detail)


class MockPosting:
    def __init__(self, doc_num: int, positions: list[int] | None = None):
        self.doc_num = doc_num
        self.positions = positions if positions is not None else [1]


class MockIndexReader:
    """輕量 Mock IndexReader，用於測試布林求值各分支。"""
    def __init__(self, N: int, postings_map: dict[str, list[MockPosting]]):
        self.N = N
        self._map = postings_map

    def df(self, term: str) -> int:
        return len(self._map.get(term, []))

    def get_doc_tf(self, term: str) -> tuple[list[int], list[int]]:
        plist = self._map.get(term, [])
        return [p.doc_num for p in plist], [1] * len(plist)

    def get_postings(self, term: str) -> list[MockPosting]:
        return self._map.get(term, [])


def main():
    total_passed = 0
    total_tests = 0

    print("=" * 60)
    print("T5: 根節點與 None 邊界防呆")
    print("=" * 60)

    # 模擬 10 篇文件之索引
    mock_postings = {
        "apple": [MockPosting(0, [1]), MockPosting(2, [3]), MockPosting(5, [1])],
        "banana": [MockPosting(2, [4]), MockPosting(5, [2]), MockPosting(7, [1])],
        "cat": [MockPosting(1, [1]), MockPosting(2, [10]), MockPosting(8, [2])],
        "dog": [MockPosting(3, [1]), MockPosting(5, [10]), MockPosting(8, [1])],
    }
    reader = MockIndexReader(N=10, postings_map=mock_postings)

    # 1. None 回傳 None
    total_tests += 1
    if run("evaluate(None) == None", lambda: (evaluate(None, reader) is None, "")):
        total_passed += 1

    # 2. 根節點為 Term 時回傳 None（自由文字查詢，不過濾，交給 VSM）
    total_tests += 1
    if run("evaluate(Term(['apple'])) == None (自由文字查詢)", lambda: (
        evaluate(Term(["apple"]), reader) is None, ""
    )):
        total_passed += 1

    total_tests += 1
    if run("evaluate(Term(['apple', 'banana'])) == None (多詞自由文字)", lambda: (
        evaluate(Term(["apple", "banana"]), reader) is None, ""
    )):
        total_passed += 1

    print("\n" + "=" * 60)
    print("T5: 內部 Term 與 And / Or / Not 節點運算")
    print("=" * 60)

    # 3. And 節點包含單詞 Term
    # apple 出現於 {0, 2, 5}，banana 出現於 {2, 5, 7}
    # apple AND banana -> {2, 5}
    total_tests += 1
    if run("And(apple, banana) == {2, 5}", lambda: (
        evaluate(And([Term(["apple"]), Term(["banana"])]), reader) == {2, 5},
        f"got {evaluate(And([Term(['apple']), Term(['banana'])]), reader)}"
    )):
        total_passed += 1

    # 4. 內部 Term 多詞隱含 AND
    # Term(['apple', 'banana']) 位於 And 內部時求出 {2, 5}
    total_tests += 1
    if run("And(Term(['apple', 'banana']), cat) == {2}", lambda: (
        evaluate(And([Term(["apple", "banana"]), Term(["cat"])]), reader) == {2},
        f"got {evaluate(And([Term(['apple', 'banana']), Term(['cat'])]), reader)}"
    )):
        total_passed += 1

    # 5. Term 遇到不存在詞彙 (df == 0) short-circuit 回傳空集合
    total_tests += 1
    if run("And(apple, nonexistent) == set()", lambda: (
        evaluate(And([Term(["apple"]), Term(["nonexistent"])]), reader) == set(),
        f"got {evaluate(And([Term(['apple']), Term(['nonexistent'])]), reader)}"
    )):
        total_passed += 1

    # 6. Or 節點運算
    # apple ({0, 2, 5}) OR cat ({1, 2, 8}) -> {0, 1, 2, 5, 8}
    total_tests += 1
    if run("Or(apple, cat) == {0, 1, 2, 5, 8}", lambda: (
        evaluate(Or([Term(["apple"]), Term(["cat"])]), reader) == {0, 1, 2, 5, 8},
        f"got {evaluate(Or([Term(['apple']), Term(['cat'])]), reader)}"
    )):
        total_passed += 1

    # 7. Not 節點運算（補集）
    # Not(apple) -> 全集 {0..9} - {0, 2, 5} = {1, 3, 4, 6, 7, 8, 9}
    expected_not_apple = set(range(10)) - {0, 2, 5}
    total_tests += 1
    if run("Not(apple) == set(range(10)) - {0, 2, 5}", lambda: (
        evaluate(Not(Term(["apple"])), reader) == expected_not_apple,
        f"got {evaluate(Not(Term(['apple'])), reader)}"
    )):
        total_passed += 1

    # 8. 純 NOT 查詢與組合：cat AND NOT dog
    # cat: {1, 2, 8}, dog: {3, 5, 8} -> {1, 2}
    total_tests += 1
    if run("And(cat, Not(dog)) == {1, 2}", lambda: (
        evaluate(And([Term(["cat"]), Not(Term(["dog"]))]), reader) == {1, 2},
        f"got {evaluate(And([Term(['cat']), Not(Term(['dog']))]), reader)}"
    )):
        total_passed += 1

    print("\n" + "=" * 60)
    print("T5: 複雜巢狀運算與 Phrase / Near 整合")
    print("=" * 60)

    # 9. 複雜巢狀：(apple OR banana) AND (cat OR dog)
    # apple OR banana = {0, 2, 5, 7}
    # cat OR dog = {1, 2, 3, 5, 8}
    # 交集 = {2, 5}
    nested_query = And([
        Or([Term(["apple"]), Term(["banana"])]),
        Or([Term(["cat"]), Term(["dog"])])
    ])
    total_tests += 1
    if run("(apple OR banana) AND (cat OR dog) == {2, 5}", lambda: (
        evaluate(nested_query, reader) == {2, 5},
        f"got {evaluate(nested_query, reader)}"
    )):
        total_passed += 1

    # 10. Phrase 比對
    # apple 位置：doc 0 [1], doc 2 [3], doc 5 [1]
    # banana 位置：doc 2 [4], doc 5 [2], doc 7 [1]
    # Phrase("apple banana", positions=[0, 1]) 在 doc 2: apple at 3, banana at 4 (符合！)
    # 在 doc 5: apple at 1, banana at 2 (符合！)
    phrase_node = Phrase(tokens=["apple", "banana"], positions=[0, 1])
    total_tests += 1
    if run("Phrase('apple banana') == {2, 5}", lambda: (
        evaluate(Or([phrase_node]), reader) == {2, 5},
        f"got {evaluate(Or([phrase_node]), reader)}"
    )):
        total_passed += 1

    # 11. 未 expand 的 Wildcard / Soundex 拋出 ValueError
    def test_wildcard_err():
        try:
            evaluate(And([Wildcard("app*")]), reader)
            return False, "did not raise ValueError"
        except ValueError as e:
            return True, str(e)

    total_tests += 1
    if run("Wildcard 未 expand 拋出 ValueError", test_wildcard_err):
        total_passed += 1

    def test_soundex_err():
        try:
            evaluate(And([Soundex("apple")]), reader)
            return False, "did not raise ValueError"
        except ValueError as e:
            return True, str(e)

    total_tests += 1
    if run("Soundex 未 expand 拋出 ValueError", test_soundex_err):
        total_passed += 1

    print("\n" + "=" * 60)
    print("T5: Skip Pointer 效率驗證 (加分項)")
    print("=" * 60)

    # 12. 長短串列交集比對次數：skip < basic
    p_long = list(range(0, 5000, 2))  # 長度 2500
    p_short = [100, 1500, 3200, 4800]
    res_b, n_b = intersect_postings(p_long, p_short, use_skip=False)
    res_s, n_s = intersect_postings(p_long, p_short, use_skip=True)

    total_tests += 1
    if run("intersect_postings: skip 比對次數小於線性比對次數", lambda: (
        res_b == res_s == [100, 1500, 3200, 4800] and n_s < n_b * 0.3,
        f"skip={n_s}, basic={n_b} (減少 {(1 - n_s / n_b)*100:.1f}%)"
    )):
        total_passed += 1

    print("\n" + "=" * 60)
    print("T5: 真實索引 (HW2 Index) 整合驗證")
    print("=" * 60)

    if INDEX.exists() and (INDEX / "metadata.json").exists():
        real_reader = IndexReader(INDEX)
        prep = Preprocessor.from_config(real_reader.get_metadata()["preprocessor"])

        # 自由文字查詢 -> None
        q_free = parse("Microsoft", prep)
        total_tests += 1
        if run("真實索引: 'Microsoft' (自由文字) -> None", lambda: (
            evaluate(q_free, real_reader) is None, ""
        )):
            total_passed += 1

        # 布林 AND 查詢
        q_and = expand(parse("open source AND Linux", prep), real_reader)
        docs_and = evaluate(q_and, real_reader)
        total_tests += 1
        if run("真實索引: 'open source AND Linux' -> set[int]", lambda: (
            isinstance(docs_and, set) and len(docs_and) > 0 and all(0 <= d < real_reader.N for d in docs_and),
            f"命中 {len(docs_and)} 篇文件"
        )):
            total_passed += 1

        # 布林 OR 查詢
        q_or = expand(parse("software engineer OR project manager", prep), real_reader)
        docs_or = evaluate(q_or, real_reader)
        total_tests += 1
        if run("真實索引: 'software engineer OR project manager' -> set[int]", lambda: (
            isinstance(docs_or, set) and len(docs_or) > 0,
            f"命中 {len(docs_or)} 篇文件"
        )):
            total_passed += 1

        # 純 NOT 查詢
        q_not = expand(parse("NOT linux", prep), real_reader)
        docs_not = evaluate(q_not, real_reader)
        total_tests += 1
        if run("真實索引: 'NOT linux' -> N - df(linux)", lambda: (
            isinstance(docs_not, set) and len(docs_not) == real_reader.N - real_reader.df("linux"),
            f"命中 {len(docs_not)} 篇文件 (N={real_reader.N}, df={real_reader.df('linux')})"
        )):
            total_passed += 1

    print("\n" + "=" * 60)
    print(f"Test Summary: {total_passed}/{total_tests} passed")
    print("=" * 60)
    if total_passed == total_tests:
        print("\n\033[32m✔ ALL T5 TESTS PASSED!\033[0m\n")
    else:
        print(f"\n\033[31m✘ SOME TESTS FAILED: {total_tests - total_passed} failed\033[0m\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
