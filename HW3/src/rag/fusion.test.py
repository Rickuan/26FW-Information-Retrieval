"""rag.fusion 的單元測試（規格 1.6-7；測試清單見 plans/.done.A5-lexical-fusion-retrieve.md 第 6 節）。

只用測試內自建的 Document，不依賴 fixtures 或全量產物。
執行（在 HW3/ 下）：uv run python src/rag/fusion.test.py
"""
import sys
import unittest
from pathlib import Path

# 直接執行時 sys.path[0] 是 HW3/src/rag/；改由 HW3/src 匯入，避免同一模組被載入兩份（規格 1.6-7）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.documents import Document  # noqa: E402
from langchain_core.retrievers import BaseRetriever  # noqa: E402

from rag.fusion import HybridRetriever, rrf_fuse  # noqa: E402

K = 60
KEYS = {"docid", "trec_id", "url", "pid", "score", "rank", "sources"}


def doc(docid, pid=None, score=0.5, source="lexical", rank=1, text=None):
    pid = docid * 10 if pid is None else pid
    return Document(page_content=text or f"{source} passage {pid}", metadata={
        "docid": docid, "trec_id": f"trec-{docid}", "url": f"http://x/{docid}",
        "pid": pid, "score": score, "rank": rank, "sources": [source]})


def lex(*docids):
    return [doc(d, source="lexical", rank=i) for i, d in enumerate(docids, 1)]


def sem(*items):
    """items 為 docid 或 (docid, score)；語意的 pid = docid * 10 + 1，與詞彙那一路不同。"""
    out = []
    for i, it in enumerate(items, 1):
        d, s = it if isinstance(it, tuple) else (it, 0.9)
        out.append(doc(d, pid=d * 10 + 1, score=s, source="semantic", rank=i))
    return out


def ids(docs):
    return [d.metadata["docid"] for d in docs]


class FakeRetriever(BaseRetriever):
    docs: list[Document]

    def _get_relevant_documents(self, query, *, run_manager=None):
        return list(self.docs)


class ScoreTest(unittest.TestCase):
    def test_rrf_score_both_and_single(self):
        out = {d.metadata["docid"]: d for d in rrf_fuse(lex(1, 2, 3), sem(9, 8, 1), rrf_k=K)}
        self.assertAlmostEqual(out[1].metadata["score"], 1 / 61 + 1 / 63, places=15)
        self.assertAlmostEqual(out[2].metadata["score"], 1 / 62, places=15)
        self.assertAlmostEqual(out[8].metadata["score"], 1 / 62, places=15)
        self.assertIsInstance(out[1].metadata["score"], float)

    def test_rank_comes_from_list_position(self):
        bad = lex(5, 6)
        bad[0].metadata["rank"], bad[1].metadata["rank"] = 99, 1   # 錯誤的上游 rank 不影響結果
        out = rrf_fuse(bad, [], rrf_k=K)
        self.assertEqual(ids(out), [5, 6])
        self.assertAlmostEqual(out[0].metadata["score"], 1 / 61, places=15)

    def test_sorted_by_score_and_ranks_renumbered(self):
        out = rrf_fuse(lex(1, 2, 3, 4), sem(4, 3), rrf_k=K)
        scores = [d.metadata["score"] for d in out]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual([d.metadata["rank"] for d in out], list(range(1, len(out) + 1)))
        self.assertEqual(ids(out)[:2], [4, 3])    # 兩路都有的分數較高


class TieRuleTest(unittest.TestCase):
    def test_lexical_only_before_semantic_only(self):
        # 學號題的情況：兩路同名次 → 分數兩兩相同；詞彙那一路的 docid 刻意比較大
        out = rrf_fuse(lex(100, 200, 300), sem(1, 2, 3), rrf_k=K)
        self.assertEqual(ids(out), [100, 1, 200, 2, 300, 3])

    def test_both_before_lexical_only_before_semantic_only(self):
        # rrf_k=0 構造三篇精確同分（皆 1/3）：
        #   docid 10 兩路都在第 6 名：1/6 + 1/6；docid 50 只在詞彙第 3 名；docid 5 只在語意第 3 名
        lexical = lex(91, 92, 50, 93, 94, 10)
        semantic = sem(81, 82, 5, 83, 84, 10)
        out = rrf_fuse(lexical, semantic, rrf_k=0)
        tied = [d for d in out if d.metadata["docid"] in (5, 10, 50)]
        self.assertEqual(ids(tied), [10, 50, 5])     # 類別優先於 docid（docid 順序會是 5, 10, 50）
        self.assertEqual(ids(out)[:2], [91, 81])     # 1/1 同分：只有詞彙 > 只有語意

    def test_docid_ascending_within_same_category(self):
        # 同一路的名次不會相同，所以同類別同分只會出現在「兩路都有」：兩篇皆 1/61 + 1/62
        out = rrf_fuse(lex(20, 10), sem(10, 20), rrf_k=K)
        self.assertEqual(ids(out), [10, 20])

    def test_close_scores_not_tied(self):
        # docid 1 = 1/62 + 1/61，docid 2 = 1/61 + 1/63：差距很小但不是同分，不可退回 docid 規則
        out = rrf_fuse(lex(2, 1), sem(1, 3, 2), rrf_k=K)
        self.assertEqual(ids(out)[:2], [1, 2])
        out = rrf_fuse(lex(1, 2), sem(2, 3, 1), rrf_k=K)
        self.assertEqual(ids(out)[:2], [2, 1])


class ThresholdTest(unittest.TestCase):
    def test_filters_only_semantic_only_below_threshold(self):
        out = rrf_fuse(lex(1), sem((2, 0.29), (3, 0.30), (4, 0.50)), rrf_k=K, semantic_min_score=0.30)
        self.assertEqual(set(ids(out)), {1, 3, 4})   # 0.29 被擋；等於門檻保留

    def test_both_sources_not_affected(self):
        out = rrf_fuse(lex(1, 2), sem((2, 0.01), (5, 0.01)), rrf_k=K, semantic_min_score=0.30)
        self.assertEqual(ids(out), [2, 1])
        self.assertEqual(out[0].metadata["sources"], ["lexical", "semantic"])

    def test_filtering_keeps_semantic_ranks(self):
        out = rrf_fuse([], sem((1, 0.1), (2, 0.9)), rrf_k=K, semantic_min_score=0.30)
        self.assertEqual(ids(out), [2])
        self.assertAlmostEqual(out[0].metadata["score"], 1 / 62, places=15)   # 仍是語意第 2 名
        self.assertEqual(out[0].metadata["rank"], 1)

    def test_none_disables_threshold(self):
        out = rrf_fuse([], sem((1, 0.0)), rrf_k=K, semantic_min_score=None)
        self.assertEqual(ids(out), [1])


class PassageAndSourcesTest(unittest.TestCase):
    def test_passage_prefers_semantic(self):
        out = {d.metadata["docid"]: d for d in rrf_fuse(lex(1, 2), sem(1, 3), rrf_k=K)}
        self.assertEqual(out[1].metadata["pid"], 11)
        self.assertEqual(out[1].page_content, "semantic passage 11")
        self.assertEqual(out[2].metadata["pid"], 20)
        self.assertEqual(out[2].page_content, "lexical passage 20")
        self.assertEqual(out[3].metadata["pid"], 31)

    def test_sources(self):
        out = {d.metadata["docid"]: d.metadata["sources"]
               for d in rrf_fuse(lex(1, 2), sem(3, 1), rrf_k=K)}
        self.assertEqual(out, {1: ["lexical", "semantic"], 2: ["lexical"], 3: ["semantic"]})

    def test_metadata_keys_exact(self):
        for d in rrf_fuse(lex(1, 2), sem(1, 3), rrf_k=K):
            self.assertEqual(set(d.metadata), KEYS)
            self.assertEqual(d.metadata["trec_id"], f"trec-{d.metadata['docid']}")


class EdgeTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(rrf_fuse([], [], rrf_k=K), [])

    def test_one_side_empty_keeps_order(self):
        self.assertEqual(ids(rrf_fuse(lex(5, 3, 9), [], rrf_k=K)), [5, 3, 9])
        self.assertEqual(ids(rrf_fuse([], sem(5, 3, 9), rrf_k=K)), [5, 3, 9])

    def test_duplicate_docid_raises(self):
        with self.assertRaises(ValueError):
            rrf_fuse(lex(1, 1), [], rrf_k=K)
        with self.assertRaises(ValueError):
            rrf_fuse([], sem(2, 2), rrf_k=K)

    def test_invalid_rrf_k(self):
        for bad in [-1, 1.5, True, "60"]:
            with self.assertRaises(ValueError):
                rrf_fuse([], [], rrf_k=bad)


class HybridRetrieverTest(unittest.TestCase):
    def test_invoke_equals_rrf_fuse(self):
        L, S = lex(1, 2, 3), sem((3, 0.9), (4, 0.1), (5, 0.8))
        r = HybridRetriever(lexical=FakeRetriever(docs=L), semantic=FakeRetriever(docs=S),
                            rrf_k=K, semantic_min_score=0.30)
        got = r.invoke("q")
        want = rrf_fuse(L, S, rrf_k=K, semantic_min_score=0.30)
        self.assertEqual([(d.page_content, d.metadata) for d in got],
                         [(d.page_content, d.metadata) for d in want])
        self.assertNotIn(4, ids(got))

    def test_from_config(self):
        cfg = {"retrieval": {"rrf_k": 60, "semantic_min_score": 0.3}}
        r = HybridRetriever.from_config(FakeRetriever(docs=[]), FakeRetriever(docs=[]), cfg)
        self.assertEqual((r.rrf_k, r.semantic_min_score), (60, 0.3))


if __name__ == "__main__":
    unittest.main()
