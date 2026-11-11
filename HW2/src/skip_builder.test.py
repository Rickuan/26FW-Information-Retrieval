"""skip_builder.test.py — HW2 skip_builder 單元測試。"""
from __future__ import annotations

import math
import unittest
from array import array

from skip_builder import (
    MIN_SKIP_LEN,
    PostingWithSkip,
    SkipPointer,
    build_skip_list,
    intersect_basic,
    intersect_postings,
    intersect_with_skips,
)


class TestSkipBuilder(unittest.TestCase):

    def test_build_skip_list_short(self):
        """P < 9 不建立任何 skip 指標。"""
        for p_len in [0, 1, 5, 8]:
            docs = [i * 3 for i in range(p_len)]
            res = build_skip_list(docs)
            self.assertEqual(len(res), p_len)
            self.assertTrue(all(p.skip is None for p in res))

    def test_build_skip_list_rule(self):
        """P = 9, 10, 25 驗證 skip 指向與間隔。"""
        # P = 9, L = 3 -> indices 0 -> 3, 3 -> 6
        docs = [i * 10 for i in range(9)]
        res = build_skip_list(docs)
        self.assertEqual(len(res), 9)
        self.assertIsNotNone(res[0].skip)
        self.assertEqual(res[0].skip.target_index, 3)
        self.assertEqual(res[0].skip.target_doc_num, 30)

        self.assertIsNotNone(res[3].skip)
        self.assertEqual(res[3].skip.target_index, 6)
        self.assertEqual(res[3].skip.target_doc_num, 60)

        self.assertIsNone(res[6].skip)
        self.assertTrue(all(res[i].skip is None for i in [1, 2, 4, 5, 7, 8]))

    def test_intersect_correctness(self):
        """驗證 intersect_basic 與 intersect_with_skips 結果一致，並在長短串列發揮跳躍優勢。"""
        # 長串列 vs 短串列（差距懸殊時 Skip 顯著減少比對次數）
        p1 = list(range(0, 2000, 2))  # 長度 1000
        p2 = [500, 1500]
        expected = [500, 1500]

        res_basic, n_basic = intersect_postings(p1, p2, use_skip=False)
        self.assertEqual(res_basic, expected)

        res_skip, n_skip = intersect_postings(p1, p2, use_skip=True)
        self.assertEqual(res_skip, expected)
        # 驗證在長短串列交集中，skip 比對次數遠小於線性比對次數
        self.assertLess(n_skip, n_basic * 0.3)

    def test_intersect_empty_and_disjoint(self):
        """空串列與無交集邊界測試。"""
        self.assertEqual(intersect_postings([], [1, 2, 3])[0], [])
        self.assertEqual(intersect_postings([1, 2, 3], [])[0], [])
        self.assertEqual(intersect_postings([1, 3, 5], [2, 4, 6])[0], [])


if __name__ == "__main__":
    unittest.main()
