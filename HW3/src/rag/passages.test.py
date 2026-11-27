"""rag.passages 的單元測試（規格 1.6-7；測試清單見 plans/A2-docstore-passages.md 第 5 節）。

執行（在 HW3/ 下）：uv run python src/rag/passages.test.py
"""
import sys
import unittest
from pathlib import Path

# 直接執行時 sys.path[0] 是 HW3/src/rag/；改由 HW3/src 匯入，避免同一模組被載入兩份（規格 1.6-7）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag.passages import MIN_SPLIT_WORDS, number_passages, split_passages  # noqa: E402


def make_text(n: int) -> str:
    return " ".join(f"w{i}" for i in range(n))


def spans(text: str, w: int, s: int) -> list[tuple[int, int]]:
    return [(a, b) for a, b, _ in split_passages(text, w, s)]


class SplitBasicsTest(unittest.TestCase):
    def test_empty_and_whitespace_only(self):
        for text in ["", " ", "\n\t  \n", "\xa0"]:
            self.assertEqual(split_passages(text, 300, 250), [], repr(text))

    def test_single_passage_when_short(self):
        self.assertEqual(spans(make_text(1), 300, 250), [(0, 1)])
        self.assertEqual(spans(make_text(299), 300, 250), [(0, 299)])
        self.assertEqual(spans(make_text(300), 300, 250), [(0, 300)])

    def test_under_min_split_words_is_one_passage_even_if_longer_than_w(self):
        self.assertEqual(MIN_SPLIT_WORDS, 30)
        self.assertEqual(spans(make_text(25), 10, 8), [(0, 25)])
        self.assertEqual(spans(make_text(29), 10, 8), [(0, 29)])
        # 達到 30 字就照一般規則切
        self.assertEqual(spans(make_text(30), 10, 8)[0], (0, 10))

    def test_spec_examples(self):
        self.assertEqual(spans(make_text(301), 300, 250), [(0, 300), (250, 301)])
        self.assertEqual(spans(make_text(550), 300, 250), [(0, 300), (250, 550)])
        self.assertEqual(spans(make_text(551), 300, 250), [(0, 300), (250, 550), (500, 551)])

    def test_invalid_params(self):
        for w, s in [(300, 0), (300, 301), (0, 0), (0, 1), (10, -1)]:
            with self.assertRaises(ValueError, msg=(w, s)):
                split_passages("a b c", w, s)


class SplitPropertiesTest(unittest.TestCase):
    PARAMS = [(300, 250), (10, 8), (10, 10), (10, 1), (40, 25), (50, 50), (1, 1)]

    def test_coverage_and_shape(self):
        for w, s in self.PARAMS:
            for n in range(0, 1200 if w >= 40 else 200):
                with self.subTest(w=w, s=s, n=n):
                    sp = spans(make_text(n), w, s)
                    if n == 0:
                        self.assertEqual(sp, [])
                        continue
                    self.assertEqual(sp[0][0], 0)
                    self.assertEqual(sp[-1][1], n)
                    for (a0, b0), (a1, b1) in zip(sp, sp[1:]):
                        self.assertLessEqual(a1, b0)       # 無空隙
                        self.assertLess(a0, a1)            # 起點嚴格遞增
                        self.assertLess(b0, b1)
                    if len(sp) == 1:
                        continue
                    for a, b in sp:
                        self.assertEqual(a % s, 0)
                        self.assertLessEqual(b - a, w)
                    self.assertGreaterEqual(sp[-1][1] - sp[-1][0], w - s + 1)

    def test_short_span_always_inside_one_passage(self):
        for w, s in [(300, 250), (10, 8), (40, 25)]:
            span_len = w - s
            for n in range(span_len, 700 if w == 300 else 150):
                sp = spans(make_text(n), w, s)
                for a in range(0, n - span_len + 1):
                    b = a + span_len
                    with self.subTest(w=w, s=s, n=n, a=a):
                        self.assertTrue(any(pa <= a and b <= pb for pa, pb in sp))

    def test_passage_count_formula(self):
        w, s = 300, 250
        for n in range(w + 1, 3000):
            self.assertEqual(len(spans(make_text(n), w, s)), 1 + -(-(n - w) // s))


class TextNormalizationTest(unittest.TestCase):
    def test_whitespace_is_normalized_and_text_matches_words(self):
        raw = "  alpha\tbeta\n\ngamma  delta\xa0epsilon\r\n" + "\n".join(f"x{i}" for i in range(60))
        words = raw.split()
        out = split_passages(raw, 20, 15)
        self.assertGreater(len(out), 1)
        for a, b, text in out:
            self.assertEqual(text, " ".join(words[a:b]))
            self.assertNotIn("\n", text)
            self.assertNotIn("\t", text)
            self.assertNotIn("\xa0", text)
            self.assertNotIn("  ", text)
        self.assertTrue(out[0][2].startswith("alpha beta gamma delta epsilon x0"))


class NumberPassagesTest(unittest.TestCase):
    def test_pid_is_global_and_contiguous_and_skips_empty_docs(self):
        docs = [(0, make_text(5)), (1, ""), (2, make_text(25)), (3, "   "), (5, make_text(3))]
        rows = list(number_passages(docs, 10, 8))
        self.assertEqual([r[0] for r in rows], list(range(len(rows))))
        self.assertEqual([(r[1], r[2], r[3]) for r in rows],
                         [(0, 0, 5), (2, 0, 25), (5, 0, 3)])

    def test_multi_passage_docs_ordering(self):
        docs = [(7, make_text(551)), (8, make_text(301))]
        rows = list(number_passages(docs, 300, 250))
        self.assertEqual([(r[0], r[1], r[2], r[3]) for r in rows], [
            (0, 7, 0, 300), (1, 7, 250, 550), (2, 7, 500, 551),
            (3, 8, 0, 300), (4, 8, 250, 301),
        ])
        self.assertEqual(rows[2][4], "w500 " + " ".join(f"w{i}" for i in range(501, 551)))

    def test_empty_input_and_invalid_params(self):
        self.assertEqual(list(number_passages([], 300, 250)), [])
        with self.assertRaises(ValueError):
            list(number_passages([(0, "a")], 300, 0))


if __name__ == "__main__":
    unittest.main()
