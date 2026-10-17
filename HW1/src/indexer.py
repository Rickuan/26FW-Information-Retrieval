import time
import heapq
import pickle
from dataclasses import dataclass
from array import array
from itertools import groupby
from pathlib import Path

from documents import iter_documents
from tokenizer import Preprocessor
from trie import RadixTrie


@dataclass(slots=True)
class Posting:
    doc_num: int
    tf: int
    # positions: list[int]
    positions: array


@dataclass
class DocEntry:
    trec_id: str
    doc_len: int
    url: str


def add_document(index, doc_map, doc_num, trec_id, url, terms):
    doc_map[doc_num] = DocEntry(trec_id, len(terms), url)
    for pos, tok in terms:
        plist = index.get(tok)
        if plist is None:
            index[tok] = [Posting(doc_num, 1, array("I", (pos,)))]
            continue
        last = plist[-1]
        if last.doc_num == doc_num:
            last.tf += 1
            last.positions.append(pos)
        else:
            assert doc_num > last.doc_num, f"doc_num not increasing: {last.doc_num} -> {doc_num}"
            plist.append(Posting(doc_num, 1, array("I", (pos,))))


# ---------------------------------------------------------------------------
# SPIMI 磁碟格式：每筆 (term, postings) 各自一個 pickle，
# 讀取時可逐筆串流，任何時刻只有一筆在記憶體中。
# ---------------------------------------------------------------------------
def _write_record(f, term, plist):
    # 存成 tuple 而非直接 pickle dataclass：格式穩定、讀回時再組回 Posting
    rec = (term, [(p.doc_num, p.tf, p.positions) for p in plist])
    pickle.dump(rec, f, protocol=pickle.HIGHEST_PROTOCOL)


def _read_records(path):
    # 逐筆讀到 EOF；generator 讓多路歸併時每個 partial 只佔一筆紀錄的記憶體
    with open(path, "rb") as f:
        while True:
            try:
                yield pickle.load(f)
            except EOFError:
                return


class Indexer:
    def __init__(self, spimi=False, flush_every=3_000_000, tmp_dir="spimi_tmp"):
        self.index = {}
        self.doc_map = {}
        self.stats = {}
        self._trie = None

        # ---- SPIMI 設定 ----
        # flush_every：累積多少個「位置」就把目前索引寫到磁碟。
        # 用位置數而不是 RSS 判斷：Python 釋放 dict 後通常不會把記憶體還給 OS，
        # RSS 不會下降，第一次 flush 之後就會一直誤觸發。
        self.spimi = spimi
        self.flush_every = flush_every
        self.tmp_dir = Path(tmp_dir)
        self.n_partials = 0
        self._buffered = 0           # 目前記憶體中的位置數
        self._partials = []          # 已寫出的 partial 檔路徑（依產生順序）
        self._merged = None          # 歸併後的單一檔案
        self._vocab_size = 0         # SPIMI 模式下 self.index 會被清空，詞彙數由歸併時計算

    def add_document(self, doc, terms):
        add_document(self.index, self.doc_map, doc.doc_num, doc.trec_id, doc.url, terms)
        self._buffered += len(terms)
        # 只在文件與文件之間 flush：同一份文件的 postings 不會被拆到兩個 partial，
        # 歸併時同一個詞的 postings 才能直接串接，不需重新排序。
        if self.spimi and self._buffered >= self.flush_every:
            self._flush_partial()

    def get_stats(self):
        n = len(self.doc_map)
        total = sum(e.doc_len for e in self.doc_map.values())
        self.stats = {
            "N": n,
            "vocab_size": self._vocab_size if self.spimi else len(self.index),
            "total_tokens": total,
            "avg_doc_len": total / n if n else 0.0,
        }
        return self.stats

    def get_postings(self, term):
        if self.spimi:
            raise RuntimeError("get_postings only supported in memory mode")
        return self.index.get(term, [])

    def prefix_search(self, prefix, limit=None):
        if self._trie is None:
            self._trie = self.build_trie()
        return self._trie.prefix_search(prefix, limit)

    def build(self, warc_path, preprocessor, limit=None, progress=5000):
        self._trie = None
        if self.spimi:
            self._reset_tmp()
        t0 = time.time()
        for i, doc in enumerate(iter_documents(warc_path), 1):
            self.add_document(doc, preprocessor.process(doc.text))
            if progress and i % progress == 0:
                print(f"  ...{i} docs ({time.time() - t0:.0f}s)")
            if limit and i >= limit:
                break
        if self.spimi:
            # 迴圈結束時記憶體裡還有最後一塊，先寫出再歸併
            self._flush_partial()
            t1 = time.time()
            self._merge_partials()
            if progress:
                print(f"  merged {self.n_partials} partials ({time.time() - t1:.0f}s)")
        self.get_stats()
        return self

    def iter_postings(self):
        if not self.spimi:
            for term in sorted(self.index):
                yield term, self.index[term]
            return
        # SPIMI 模式：self.index 已清空，改從 merged 檔逐筆讀出並組回 Posting。
        # 輸出順序與全記憶體模式相同（依詞的字典序）。
        if self._merged is None:
            raise RuntimeError("SPIMI index not built yet; call build() first")
        for term, plist in _read_records(self._merged):
            yield term, [Posting(d, tf, pos) for d, tf, pos in plist]

    def build_trie(self):
        trie = RadixTrie()
        for term, plist in self.iter_postings():
            trie.insert(term, len(plist) if self.spimi else plist)
        return trie

    # ---------------------------------------------------------------------
    # SPIMI 內部
    # ---------------------------------------------------------------------
    def _reset_tmp(self):
        # 只刪本程式產生的檔案，不用 rmtree，避免誤刪 tmp_dir 裡的其他東西
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        for p in self.tmp_dir.glob("partial_*.pkl"):
            p.unlink()
        merged = self.tmp_dir / "merged.pkl"
        if merged.exists():
            merged.unlink()
        self._partials, self._merged, self.n_partials = [], None, 0

    def _flush_partial(self):
        # 把目前記憶體中的索引「依詞排序後」逐筆寫出，再整個清空。
        # 每個 partial 內部是排序好的，歸併時才能用多路歸併。
        if not self.index:
            return
        path = self.tmp_dir / f"partial_{self.n_partials:03d}.pkl"
        with open(path, "wb") as f:
            for term in sorted(self.index):
                _write_record(f, term, self.index[term])
        self._partials.append(path)
        self.n_partials += 1
        self.index = {}              # 換新 dict，舊的由 reference counting 立即釋放
        self._buffered = 0

    def _merge_partials(self):
        # 多路歸併：heapq.merge 同時從每個 partial 讀一筆，依詞的字典序輸出。
        #
        # 關鍵性質：遇到相同的詞時，heapq.merge 會依輸入串流的順序輸出
        # （先 partial_000、再 partial_001 ...）。partial 是依文件順序產生的，
        # 前一個 partial 的 docID 一定比後一個小，所以同一個詞的 postings
        # 直接串接就維持 docID 遞增，不需要重新排序。
        self._merged = self.tmp_dir / "merged.pkl"
        streams = [_read_records(p) for p in self._partials]
        vocab = 0
        with open(self._merged, "wb") as out:
            merged = heapq.merge(*streams, key=lambda rec: rec[0])
            for term, group in groupby(merged, key=lambda rec: rec[0]):
                plist = []
                for _, part in group:
                    # 防呆：串接處的 docID 必須遞增，否則代表上述性質被破壞
                    if plist and part[0][0] <= plist[-1][0]:
                        raise ValueError(f"docID order broken while merging term {term!r}")
                    plist.extend(part)
                pickle.dump((term, plist), out, protocol=pickle.HIGHEST_PROTOCOL)
                vocab += 1
        self._vocab_size = vocab
        # partial 已全部併入 merged，刪掉以釋放磁碟空間
        for p in self._partials:
            p.unlink()
        self._partials = []

    def cleanup(self):
        # 用完 iter_postings 後呼叫：刪除 merged 檔，暫存目錄若已空也一併刪除
        if self._merged is not None and self._merged.exists():
            self._merged.unlink()
        self._merged = None
        try:
            self.tmp_dir.rmdir()
        except OSError:
            pass