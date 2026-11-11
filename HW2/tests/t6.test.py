"""t6.test.py — T6 核心：VSM 排序引擎 (rank) 與餘弦相似度計算

執行：
  uv run python HW2/tests/t6.test.py
"""
from __future__ import annotations

import json
import math
import sys
from array import array
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
INDEX = ROOT / "index"
sys.path.insert(0, str(SRC))

from parser import expand, parse, query_terms
from rank import _parse_scheme, rank
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


class MockIndexReader:
    """輕量 Mock IndexReader，用於測試 VSM 排序、權重與同分破除。"""
    def __init__(
        self,
        N: int,
        postings: dict[str, tuple[list[int], list[int]]],
        norms: dict[str, array] | None = None,
        champions: dict[tuple[str, int], tuple[list[int], list[int]]] | None = None,
    ):
        self.N = N
        self._postings = postings  # term -> (docs, tfs)
        self._norms = norms or {}
        self._champions = champions or {}

    def df(self, term: str) -> int:
        return len(self._postings.get(term, ([], []))[0])

    def get_doc_tf(self, term: str) -> tuple[list[int], list[int]]:
        return self._postings.get(term, ([], []))

    def get_norms(self, scheme: str = "ltc") -> array:
        if scheme[2] == "n":
            return array("d", [1.0]) * self.N
        if scheme in self._norms:
            return self._norms[scheme]
        # 預設回傳 1.0 避免報錯
        return array("d", [1.0]) * self.N

    def get_champions(self, term: str, r: int = 50) -> tuple[list[int], list[int]]:
        key = (term, r)
        if key in self._champions:
            return self._champions[key]
        docs, tfs = self.get_doc_tf(term)
        return docs[:r], tfs[:r]


def main() -> None:
    total_tests = 0
    total_passed = 0

    print("=" * 60)
    print("T6 VSM Ranking Engine Tests")
    print("=" * 60)

    # -------------------------------------------------------------
    # 1. Scheme 解析與格式防呆 (方案 A)
    # -------------------------------------------------------------
    print("\n--- 1. Scheme 解析與格式防呆 ---")

    def test_scheme_parse_valid():
        d, q = _parse_scheme("ltc.ltc")
        return d == "ltc" and q == "ltc", "ltc.ltc -> ('ltc', 'ltc')"

    total_tests += 1
    if run("合法 Scheme: 'ltc.ltc'", test_scheme_parse_valid):
        total_passed += 1

    def test_scheme_parse_invalid_format():
        cases = ["ltc", "ltc.ltc.ltc", "ltc.", ".ltc", "ltc.lt", "ltcltc", 123]
        for c in cases:
            try:
                _parse_scheme(c)  # type: ignore
                return False, f"未捕獲非法格式: {c!r}"
            except ValueError:
                pass
        return True, "非法點數或長度皆拋出 ValueError"

    total_tests += 1
    if run("非法 Scheme 格式 (缺少小數點/多餘小數點/長度錯誤)", test_scheme_parse_invalid_format):
        total_passed += 1

    def test_scheme_parse_invalid_letters():
        cases = ["xyz.ltc", "ltc.xyz", "atc.ltc", "lxc.ltc", "lta.ltc"]
        for c in cases:
            try:
                _parse_scheme(c)
                return False, f"未捕獲非法字母: {c!r}"
            except ValueError:
                pass
        return True, "非法字母皆拋出 ValueError"

    total_tests += 1
    if run("非法 Scheme 字母 (非合法 SMART 方案)", test_scheme_parse_invalid_letters):
        total_passed += 1

    # -------------------------------------------------------------
    # 2. 手算小語料 Mock 測試 (精確對照 Cosine 分數)
    # -------------------------------------------------------------
    print("\n--- 2. 手算小語料 Mock 測試 ---")
    # 構造 3 篇文件微型語料：
    # doc 0: "cat":1, "dog":1
    # doc 1: "cat":2
    # doc 2: "dog":1
    # N = 3, df("cat")=2, df("dog")=2
    # idf = log10(3/2) = 0.17609125905568124
    # w(cat, 0) = 1 * idf, w(dog, 0) = 1 * idf -> norm[0] = sqrt(2) * idf
    # w(cat, 1) = (1 + log10(2)) * idf -> norm[1] = (1 + log10(2)) * idf
    # w(dog, 2) = 1 * idf -> norm[2] = 1 * idf
    idf_val = math.log10(3 / 2)
    norm0 = math.sqrt(2) * idf_val
    norm1 = (1 + math.log10(2)) * idf_val
    norm2 = idf_val

    mock_norms_ltc = array("d", [norm0, norm1, norm2])
    mock_reader = MockIndexReader(
        N=3,
        postings={
            "cat": ([0, 1], [1, 2]),
            "dog": ([0, 2], [1, 1]),
        },
        norms={"ltc": mock_norms_ltc},
    )

    def test_manual_calc_single_term():
        # Query: "cat" -> qtf = {"cat": 1}
        # w_q(cat) = 1 * idf
        # doc 0: score = (w_d * w_q) / (norm0 * norm_q) = (idf * idf) / (sqrt(2)*idf * idf) = 1 / sqrt(2) ≈ 0.70710678
        # doc 1: score = (norm1 * idf) / (norm1 * idf) = 1.0
        # 排序：doc 1 (1.0), doc 0 (~0.707107)
        hits = rank(Counter({"cat": 1}), None, mock_reader, scheme="ltc.ltc")
        if len(hits) != 2:
            return False, f"預期 2 筆命中，得到 {len(hits)}"
        d1, s1 = hits[0]
        d0, s0 = hits[1]
        exp_s1 = 1.0
        exp_s0 = 1.0 / math.sqrt(2)
        cond = d1 == 1 and abs(s1 - exp_s1) < 1e-6 and d0 == 0 and abs(s0 - exp_s0) < 1e-6
        return cond, f"doc1={s1:.6f} (exp {exp_s1:.6f}), doc0={s0:.6f} (exp {exp_s0:.6f})"

    total_tests += 1
    if run("單詞查詢手算對照: 'cat'", test_manual_calc_single_term):
        total_passed += 1

    def test_manual_calc_multi_term():
        # Query: "cat dog" -> qtf = {"cat": 1, "dog": 1}
        # w_q(cat) = idf, w_q(dog) = idf -> |q| = sqrt(2) * idf
        # doc 0: acc = idf*idf + idf*idf = 2 * idf^2
        #        score = 2*idf^2 / (sqrt(2)*idf * sqrt(2)*idf) = 2 / 2 = 1.0
        # doc 1: acc = (1+log10(2))*idf * idf
        #        score = (norm1 * idf) / (norm1 * sqrt(2)*idf) = 1 / sqrt(2) ≈ 0.707107
        # doc 2: acc = idf * idf
        #        score = idf^2 / (idf * sqrt(2)*idf) = 1 / sqrt(2) ≈ 0.707107
        # doc 1 與 doc 2 同分 (1/sqrt(2))，tie-breaking 依 doc_num 升冪 (1 在前，2 在後)
        hits = rank(Counter({"cat": 1, "dog": 1}), None, mock_reader, scheme="ltc.ltc")
        if len(hits) != 3:
            return False, f"預期 3 筆命中，得到 {len(hits)}"
        d0, s0 = hits[0]
        d1, s1 = hits[1]
        d2, s2 = hits[2]
        exp_half = 1.0 / math.sqrt(2)
        cond = (d0 == 0 and abs(s0 - 1.0) < 1e-6 and
                d1 == 1 and abs(s1 - exp_half) < 1e-6 and
                d2 == 2 and abs(s2 - exp_half) < 1e-6)
        return cond, f"順序: doc{d0}={s0:.6f}, doc{d1}={s1:.6f}, doc{d2}={s2:.6f}"

    total_tests += 1
    if run("多詞查詢手算對照與同分破除: 'cat dog'", test_manual_calc_multi_term):
        total_passed += 1

    # -------------------------------------------------------------
    # 3. 排序與同分 Tie-breaking 嚴格驗證
    # -------------------------------------------------------------
    print("\n--- 3. 排序與同分 Tie-breaking 驗證 ---")

    def test_tie_breaking_order():
        # 構造 4 篇文件得分完全相同，doc_num 故意以倒序走訪
        # doc 9, doc 5, doc 3, doc 1 權重與 norm 完全相同
        tie_reader = MockIndexReader(
            N=10,
            postings={"apple": ([9, 5, 3, 1], [1, 1, 1, 1])},
            norms={"ltc": array("d", [1.0] * 10)},
        )
        hits = rank(Counter({"apple": 1}), None, tie_reader, scheme="ltc.ltc")
        doc_order = [d for d, _ in hits]
        return doc_order == [1, 3, 5, 9], f"預期 [1, 3, 5, 9]，得到 {doc_order}"

    total_tests += 1
    if run("同分文件嚴格依 doc_num 升冪排序", test_tie_breaking_order):
        total_passed += 1

    # -------------------------------------------------------------
    # 4. 候選過濾（T5 整合）驗證
    # -------------------------------------------------------------
    print("\n--- 4. 候選過濾（T5 整合）驗證 ---")

    def test_candidates_filter():
        # 使用第 2 節之 mock_reader，cat 命中 doc 1 (1.0) 與 doc 0 (0.707)
        # 若 candidates={0}，doc 1 必須被過濾
        hits = rank(Counter({"cat": 1}), {0}, mock_reader, scheme="ltc.ltc")
        return len(hits) == 1 and hits[0][0] == 0, f"命中: {hits}"

    total_tests += 1
    if run("候選集合限制 (candidates={0})", test_candidates_filter):
        total_passed += 1

    def test_empty_candidates():
        # candidates 為空集合直接 short-circuit
        hits = rank(Counter({"cat": 1}), set(), mock_reader, scheme="ltc.ltc")
        return hits == [], f"回傳 {hits}"

    total_tests += 1
    if run("空候選集合提早返回 (candidates=set())", test_empty_candidates):
        total_passed += 1

    # -------------------------------------------------------------
    # 5. 防呆與邊界條件
    # -------------------------------------------------------------
    print("\n--- 5. 防呆與邊界條件 ---")

    def test_empty_qtf():
        # 純 NOT 查詢或空 query 導致 qtf 為空
        hits = rank(Counter(), None, mock_reader)
        return hits == [], "qtf 為空直接回傳 []"

    total_tests += 1
    if run("純 NOT 查詢或空 query (qtf=Counter()) -> []", test_empty_qtf):
        total_passed += 1

    def test_nonexistent_terms():
        # 詞項完全不在詞典中 (df=0)
        hits = rank(Counter({"not_exist_word": 2}), None, mock_reader)
        return hits == [], "所有詞 df=0 回傳 []"

    total_tests += 1
    if run("不存在之詞項 (df=0) -> []", test_nonexistent_terms):
        total_passed += 1

    def test_no_candidate_intersection():
        # query 詞有 postings，但與 candidates 交集為空 (acc 累加為空)
        hits = rank(Counter({"cat": 1}), {2}, mock_reader)
        return hits == [], "無交集回傳 []"

    total_tests += 1
    if run("候選集合與命中無交集 (acc 為空短路) -> []", test_no_candidate_intersection):
        total_passed += 1

    def test_invalid_champion_r():
        try:
            rank(Counter({"cat": 1}), None, mock_reader, champion_r=0)
            return False, "未拋出 ValueError"
        except ValueError:
            return True, "champion_r < 1 拋出 ValueError"

    total_tests += 1
    if run("champion_r < 1 防呆拋錯", test_invalid_champion_r):
        total_passed += 1

    # -------------------------------------------------------------
    # 6. 加分項驗證：SMART 方案與 Champion List
    # -------------------------------------------------------------
    print("\n--- 6. 加分項驗證 ---")

    def test_smart_bnn_scheme():
        # bnn.bnn: boolean tf, no idf, no normalization
        # doc 0 has cat and dog (tf=1) -> acc[0] = 1*1 + 1*1 = 2.0
        # doc 1 has cat (tf=2 -> b=1) -> acc[1] = 1*1 = 1.0
        # doc 2 has dog (tf=1) -> acc[2] = 1*1 = 1.0
        # normalization is 'n' -> |d|=1.0, |q|=1.0
        # 分數分別為 2.0, 1.0, 1.0 (> 1.0 為非正規化內積之預期行為)
        hits = rank(Counter({"cat": 1, "dog": 1}), None, mock_reader, scheme="bnn.bnn")
        if len(hits) != 3:
            return False, f"預期 3 筆，得到 {len(hits)}"
        d0, s0 = hits[0]
        d1, s1 = hits[1]
        d2, s2 = hits[2]
        cond = d0 == 0 and s0 == 2.0 and d1 == 1 and s1 == 1.0 and d2 == 2 and s2 == 1.0
        return cond, f"bnn 分數: doc{d0}={s0}, doc{d1}={s1}, doc{d2}={s2}"

    total_tests += 1
    if run("SMART 方案 'bnn.bnn' (純內積非正規化)", test_smart_bnn_scheme):
        total_passed += 1

    def test_champion_r_param():
        # mock_reader 支援 champion_r=1
        # cat 的 champion(r=1) 只取 doc 0 (tf=1)；doc 1 (tf=2) 被截斷
        champ_reader = MockIndexReader(
            N=3,
            postings={"cat": ([0, 1], [1, 2])},
            champions={("cat", 1): ([1], [2])},  # 假設預存 tf 最高前 1 名是 doc 1
            norms={"ltc": mock_norms_ltc},
        )
        hits = rank(Counter({"cat": 1}), None, champ_reader, champion_r=1)
        return len(hits) == 1 and hits[0][0] == 1, f"Champion list 取前 1 名: {hits}"

    total_tests += 1
    if run("Champion List 加分項 (champion_r=1)", test_champion_r_param):
        total_passed += 1

    # -------------------------------------------------------------
    # 7. 真實 HW2 索引端到端測試
    # -------------------------------------------------------------
    print("\n--- 7. 真實 HW2 索引端到端測試 ---")
    if not (INDEX / "postings.bin").exists() or not (INDEX / "doc_norms.bin").exists():
        print("  [SKIP] 缺少 HW2/index 檔案，跳過真實索引測試")
    else:
        real_reader = IndexReader(INDEX)
        with (INDEX / "metadata.json").open("r", encoding="utf-8") as f:
            meta = json.load(f)
        prep = Preprocessor.from_config(meta["preprocessor"])

        def test_real_single_word():
            # 查詢 "Microsoft"
            node = expand(parse("Microsoft", prep), real_reader)
            qtf = query_terms(node)
            hits = rank(qtf, None, real_reader, scheme="ltc.ltc")
            if not hits:
                return False, "無任何命中"
            scores = [s for _, s in hits]
            all_valid = all(0.0 < s <= 1.0000001 for s in scores)
            is_sorted = all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))
            return all_valid and is_sorted, f"命中 {len(hits)} 篇，top-1 doc={hits[0][0]}, score={hits[0][1]:.6f}"

        total_tests += 1
        if run("真實索引: 'Microsoft' 排序與分數健全性", test_real_single_word):
            total_passed += 1

        def test_real_and_query():
            # 查詢 "open source AND Linux"
            from boolean import evaluate
            node = expand(parse("open source AND Linux", prep), real_reader)
            cands = evaluate(node, real_reader)
            qtf = query_terms(node)
            hits = rank(qtf, cands, real_reader, scheme="ltc.ltc")
            if not hits:
                return False, "無命中"
            # 驗證所有命中文件必在 cands 中
            all_in_cands = all(d in cands for d, _ in hits)
            scores = [s for _, s in hits]
            is_sorted = all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))
            return all_in_cands and is_sorted, f"候選 {len(cands)} 篇，評分命中 {len(hits)} 篇，top-1 score={hits[0][1]:.6f}"

        total_tests += 1
        if run("真實索引: 'open source AND Linux' 候選過濾與排序", test_real_and_query):
            total_passed += 1

        def test_real_champion_r():
            # 驗證真實 champion_r=50
            node = expand(parse("Linux", prep), real_reader)
            qtf = query_terms(node)
            hits = rank(qtf, None, real_reader, scheme="ltc.ltc", champion_r=50)
            return len(hits) > 0 and len(hits) <= 50, f"命中 {len(hits)} 篇 (預期 <= 50)"

        total_tests += 1
        if run("真實索引: 'Linux' Champion List (r=50)", test_real_champion_r):
            total_passed += 1

        def test_real_pure_not():
            from boolean import evaluate
            node = expand(parse("NOT linux", prep), real_reader)
            cands = evaluate(node, real_reader)
            qtf = query_terms(node)  # Counter()
            hits = rank(qtf, cands, real_reader)
            return hits == [], f"純 NOT 查詢回傳長度 {len(hits)}"

        total_tests += 1
        if run("真實索引: 'NOT linux' 純 NOT 查詢短路回傳 []", test_real_pure_not):
            total_passed += 1

    print("\n" + "=" * 60)
    print(f"Test Summary: {total_passed}/{total_tests} passed")
    print("=" * 60)
    if total_passed == total_tests:
        print("\n\033[32m✔ ALL T6 TESTS PASSED!\033[0m\n")
    else:
        print(f"\n\033[31m✘ SOME TESTS FAILED: {total_tests - total_passed} failed\033[0m\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
