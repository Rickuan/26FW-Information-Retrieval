import time
import heapq
import pickle
from array import array
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path

from documents import iter_documents
from tokenizer import Preprocessor
from trie import RadixTrie


@dataclass(slots=True)
class Posting:
    doc_num: int
    tf: int
    positions: array


@dataclass
class DocEntry:
    trec_id: str
    doc_len: int
    url: str


# 計畫 3-A 規格的參考實作（dict[str, list[Posting]]）。
# Indexer 內部已改用欄式儲存，此函式保留給單元測試與正確性對照使用。
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
# 欄式（columnar）儲存
#
# 原本每筆 posting 是「一個 Posting 物件 + 一個 array 物件」。全量 1,183 萬筆 posting
# 就有約 2,366 萬個 Python 物件，每個物件數十 bytes 的固定開銷佔了大部分記憶體，
# 真正的資料（docID、tf、位置）只是一小部分。
#
# 改為每個詞只存 3 個連續陣列：
#   docs: [12, 87, 301]               每筆 posting 的 doc_num
#   tfs:  [2, 1, 4]                   每筆 posting 的 tf
#   pos:  [5, 40, 3, 1, 9, 22, 30]    所有 positions 依序串接
# 第 k 筆 posting 的位置 = pos[sum(tfs[:k]) : sum(tfs[:k+1])]
# 物件數降為「詞彙數 × 4」（約 260 萬）。
#
# 對外介面不變：iter_postings() / get_postings() / index[term] 都在「讀取時」
# 才把 3 個陣列組回 list[Posting]，M4 / M5 不需要修改。
# ---------------------------------------------------------------------------
def _to_postings(docs, tfs, pos):
    out = []
    start = 0
    for d, tf in zip(docs, tfs):
        end = start + tf
        out.append(Posting(d, tf, pos[start:end]))   # array 切片會產生新的 array('I')
        start = end
    return out


class _Columns:
    __slots__ = ("docs", "tfs", "pos")

    def __init__(self, docs=None, tfs=None, pos=None):
        self.docs = docs if docs is not None else array("I")
        self.tfs = tfs if tfs is not None else array("I")
        self.pos = pos if pos is not None else array("I")

    def add(self, doc_num, pos):
        docs = self.docs
        if docs and docs[-1] == doc_num:
            # 同一份文件再次出現：只需把最後一筆的 tf 加 1
            self.tfs[-1] += 1
        else:
            # 新文件：文件依序加入，docID 必須遞增
            assert not docs or doc_num > docs[-1], f"doc_num not increasing: {docs[-1]} -> {doc_num}"
            docs.append(doc_num)
            self.tfs.append(1)
        self.pos.append(pos)

    def to_postings(self):
        return _to_postings(self.docs, self.tfs, self.pos)


class _PostingsView(Mapping):
    # 讓 idx.index 維持原計畫的用法：idx.index[term]、for term in idx.index、
    # len(idx.index)、term in idx.index、.items() / .values() 都能用。
    # 差別在於取值時才組出 list[Posting]，每次都是新物件：
    #   idx.index[t] == 內容相同，但 idx.index[t] is idx.index[t] 為 False
    def __init__(self, cols):
        self._cols = cols

    def __getitem__(self, term):
        return self._cols[term].to_postings()

    def __iter__(self):
        return iter(self._cols)

    def __len__(self):
        return len(self._cols)

    def __contains__(self, term):
        return term in self._cols


# ---------------------------------------------------------------------------
# SPIMI 磁碟格式：每筆紀錄是 (term, docs, tfs, pos)，各自一個 pickle，
# 讀取時可逐筆串流，任何時刻只有一筆在記憶體中。
# 直接存 3 個 array：pickle 會以連續 bytes 儲存，比存 Posting tuple 更小更快。
# ---------------------------------------------------------------------------
def _write_record(f, term, docs, tfs, pos):
    pickle.dump((term, docs, tfs, pos), f, protocol=pickle.HIGHEST_PROTOCOL)


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
        self._cols = {}              # term -> _Columns（實際資料，欄式儲存）
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
        self._vocab_size = 0         # SPIMI 模式下 _cols 會被清空，詞彙數由歸併時計算

    @property
    def index(self):
        # 唯讀的 dict 介面（見 _PostingsView），相容原計畫的 idx.index 用法
        return _PostingsView(self._cols)

    def add_document(self, doc, terms):
        self.doc_map[doc.doc_num] = DocEntry(doc.trec_id, len(terms), doc.url)
        cols = self._cols
        doc_num = doc.doc_num
        for pos, tok in terms:
            c = cols.get(tok)
            if c is None:
                c = cols[tok] = _Columns()
            c.add(doc_num, pos)
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
            "vocab_size": self._vocab_size if self.spimi else len(self._cols),
            "total_tokens": total,
            "avg_doc_len": total / n if n else 0.0,
        }
        return self.stats

    def df(self, term):
        # 不組 Posting 物件，直接回傳 df（僅全記憶體模式；查無回傳 0）
        c = self._cols.get(term)
        return len(c.docs) if c else 0

    def get_postings(self, term):
        if self.spimi:
            raise RuntimeError("get_postings only supported in memory mode")
        c = self._cols.get(term)
        return c.to_postings() if c else []

    def prefix_search(self, prefix, limit=None):
        if self._trie is None:
            self._trie = self.build_trie()
        res = self._trie.prefix_search(prefix, limit)
        if self.spimi:
            return res                                   # [(term, df), ...]
        # 全記憶體模式：trie 只存 df，命中的詞才組出 postings
        return [(t, self.get_postings(t)) for t, _ in res]

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
            for term in sorted(self._cols):
                yield term, self._cols[term].to_postings()
            return
        # SPIMI 模式：_cols 已清空，改從 merged 檔逐筆讀出並組回 Posting。
        # 輸出順序與全記憶體模式相同（依詞的字典序）。
        if self._merged is None:
            raise RuntimeError("SPIMI index not built yet; call build() first")
        for term, docs, tfs, pos in _read_records(self._merged):
            yield term, _to_postings(docs, tfs, pos)

    def build_trie(self):
        # trie 只存 df，不存 postings：postings 由 get_postings() 在需要時才組出。
        # 兩種模式都直接讀 docs 陣列長度，不必組出任何 Posting 物件。
        trie = RadixTrie()
        if self.spimi:
            for term, docs, _, _ in _read_records(self._merged):
                trie.insert(term, len(docs))
        else:
            for term in sorted(self._cols):
                trie.insert(term, len(self._cols[term].docs))
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
        if not self._cols:
            return
        path = self.tmp_dir / f"partial_{self.n_partials:03d}.pkl"
        with open(path, "wb") as f:
            for term in sorted(self._cols):
                c = self._cols[term]
                _write_record(f, term, c.docs, c.tfs, c.pos)
        self._partials.append(path)
        self.n_partials += 1
        self._cols = {}              # 換新 dict，舊的由 reference counting 立即釋放
        self._buffered = 0

    def _merge_partials(self):
        # 多路歸併：heapq.merge 同時從每個 partial 讀一筆，依詞的字典序輸出。
        #
        # 關鍵性質：遇到相同的詞時，heapq.merge 會依輸入串流的順序輸出
        # （先 partial_000、再 partial_001 ...）。partial 是依文件順序產生的，
        # 前一個 partial 的 docID 一定比後一個小，所以同一個詞的 3 個陣列
        # 直接串接（extend）就維持 docID 遞增，不需要重新排序。
        self._merged = self.tmp_dir / "merged.pkl"
        streams = [_read_records(p) for p in self._partials]
        vocab = 0
        with open(self._merged, "wb") as out:
            merged = heapq.merge(*streams, key=lambda rec: rec[0])
            for term, group in groupby(merged, key=lambda rec: rec[0]):
                docs, tfs, pos = array("I"), array("I"), array("I")
                for _, d, t, p in group:
                    # 防呆：串接處的 docID 必須遞增，否則代表上述性質被破壞
                    if docs and d[0] <= docs[-1]:
                        raise ValueError(f"docID order broken while merging term {term!r}")
                    docs.extend(d)
                    tfs.extend(t)
                    pos.extend(p)
                _write_record(out, term, docs, tfs, pos)
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