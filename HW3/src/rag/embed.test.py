"""rag.embed 的單元測試（規格 1.6-7）：前綴、拒絕重複前綴、normalize、模式；不連 Ollama。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # HW3/src（1.6-7 唯一允許的 sys.path 操作）

import numpy as np
from langchain_core.embeddings import Embeddings

from rag.embed import PrefixedOllamaEmbeddings, l2_normalize

QP = "task: search result | query: "
DP = "title: none | text: "
CFG = {"embed": {"model": "fake-embed", "query_prefix": QP, "doc_prefix": DP, "dim": 4, "batch_size": 2}}


class FakeInner(Embeddings):
    """記錄收到的文字；向量由文字長度決定（未 normalize）。"""

    def __init__(self, zero: bool = False) -> None:
        self.doc_calls: list[list[str]] = []
        self.query_calls: list[str] = []
        self.zero = zero

    def _vec(self, t: str) -> list[float]:
        return [0.0] * 4 if self.zero else [float(len(t)), 1.0, 2.0, -3.0]

    def embed_documents(self, texts):
        self.doc_calls.append(list(texts))
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        self.query_calls.append(text)
        return self._vec(text)


def make(inner=None, mode="build"):
    inner = inner or FakeInner()
    return PrefixedOllamaEmbeddings.from_config(mode, CFG, inner=inner), inner


class PrefixTest(unittest.TestCase):
    def test_doc_prefix_added_exactly_once_in_order(self):
        emb, inner = make()
        emb.embed_documents(["alpha", "beta gamma", " lead space"])
        self.assertEqual(inner.doc_calls, [[DP + "alpha", DP + "beta gamma", DP + " lead space"]])
        self.assertEqual(inner.query_calls, [])

    def test_query_prefix_added_exactly_once(self):
        emb, inner = make()
        emb.embed_query("115598067")
        self.assertEqual(inner.query_calls, [QP + "115598067"])
        self.assertEqual(inner.doc_calls, [])

    def test_prefix_whitespace_preserved(self):
        emb, inner = make()
        emb.embed_query("x")
        emb.embed_documents(["y"])
        self.assertEqual(inner.query_calls[0], "task: search result | query: x")
        self.assertEqual(inner.doc_calls[0][0], "title: none | text: y")

    def test_already_prefixed_raises(self):
        emb, inner = make()
        with self.assertRaises(ValueError):
            emb.embed_query(QP + "abc")
        with self.assertRaises(ValueError):
            emb.embed_documents(["ok", DP + "abc"])
        self.assertEqual(inner.query_calls, [])   # 檢查在送出前完成，不呼叫 inner
        self.assertEqual(inner.doc_calls, [])

    def test_other_prefix_is_plain_text(self):
        # query 開頭是 doc 前綴（或反之）不算違規，照樣加上自己的前綴
        emb, inner = make()
        emb.embed_query(DP + "q")
        emb.embed_documents([QP + "d"])
        self.assertEqual(inner.query_calls, [QP + DP + "q"])
        self.assertEqual(inner.doc_calls, [[DP + QP + "d"]])

    def test_prefix_only_at_start_counts(self):
        emb, inner = make()
        emb.embed_documents(["see " + DP])
        self.assertEqual(inner.doc_calls, [[DP + "see " + DP]])

    def test_single_inner_call_per_batch_and_empty(self):
        emb, inner = make()
        self.assertEqual(emb.embed_documents([]), [])
        self.assertEqual(inner.doc_calls, [])
        emb.embed_documents([str(i) for i in range(10)])
        self.assertEqual(len(inner.doc_calls), 1)

    def test_non_str_raises(self):
        emb, _ = make()
        with self.assertRaises(TypeError):
            emb.embed_documents([None])


class NormalizeTest(unittest.TestCase):
    def test_outputs_unit_norm_same_direction(self):
        emb, _ = make()
        docs = emb.embed_documents(["a", "bb", "ccc"])
        q = emb.embed_query("hello")
        for raw_len, v in [(len(DP) + 1, docs[0]), (len(DP) + 3, docs[2]), (len(QP) + 5, q)]:
            v = np.array(v)
            self.assertAlmostEqual(float(np.linalg.norm(v)), 1.0, places=6)
            raw = np.array([raw_len, 1.0, 2.0, -3.0])
            self.assertAlmostEqual(float(v @ raw / np.linalg.norm(raw)), 1.0, places=6)
        self.assertIsInstance(q, list)
        self.assertIsInstance(q[0], float)

    def test_zero_vector_raises(self):
        emb, _ = make(FakeInner(zero=True))
        with self.assertRaises(ValueError):
            emb.embed_query("x")
        with self.assertRaises(ValueError):
            emb.embed_documents(["x"])

    def test_l2_normalize_shape_check(self):
        with self.assertRaises(ValueError):
            l2_normalize([1.0, 2.0])
        out = l2_normalize([[3.0, 4.0]])
        self.assertEqual(out.dtype, np.float32)
        np.testing.assert_allclose(out, [[0.6, 0.8]], rtol=1e-6)

    def test_count_mismatch_raises(self):
        class Short(FakeInner):
            def embed_documents(self, texts):
                return super().embed_documents(texts)[:-1]
        emb, _ = make(Short())
        with self.assertRaises(ValueError):
            emb.embed_documents(["a", "b"])


class ModeTest(unittest.TestCase):
    def test_modes_and_config_fields(self):
        b, _ = make(mode="build")
        q, _ = make(mode="query")
        self.assertIsNone(b.num_gpu)
        self.assertEqual(q.num_gpu, 0)
        for e in (b, q):
            self.assertEqual((e.model, e.query_prefix, e.doc_prefix), ("fake-embed", QP, DP))

    def test_bad_mode_raises(self):
        with self.assertRaises(ValueError):
            PrefixedOllamaEmbeddings.from_config("gpu", CFG, inner=FakeInner())

    def test_default_inner_passes_num_gpu(self):
        # 只建立物件（不送請求），確認 num_gpu 與 model 傳給 OllamaEmbeddings
        q = PrefixedOllamaEmbeddings.from_config("query", CFG)
        b = PrefixedOllamaEmbeddings.from_config("build", CFG)
        self.assertEqual((q.inner.model, q.inner.num_gpu, q.inner.dimensions), ("fake-embed", 0, None))
        self.assertIsNone(b.inner.num_gpu)


if __name__ == "__main__":
    unittest.main()
