import time
from dataclasses import dataclass

from documents import iter_documents
from tokenizer import Preprocessor


@dataclass(slots=True)
class Posting:
    doc_num: int
    tf: int
    positions: list[int]


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
            index[tok] = [Posting(doc_num, 1, [pos])]
            continue
        last = plist[-1]
        if last.doc_num == doc_num:
            last.tf += 1
            last.positions.append(pos)
        else:
            assert doc_num > last.doc_num, f"doc_num not increasing: {last.doc_num} -> {doc_num}"
            plist.append(Posting(doc_num, 1, [pos]))


class Indexer:
    def __init__(self):
        self.index = {}
        self.doc_map = {}
        self.stats = {}

    def add_document(self, doc, terms):
        add_document(self.index, self.doc_map, doc.doc_num, doc.trec_id, doc.url, terms)

    def get_stats(self):
        n = len(self.doc_map)
        total = sum(e.doc_len for e in self.doc_map.values())
        self.stats = {
            "N": n,
            "vocab_size": len(self.index),
            "total_tokens": total,
            "avg_doc_len": total / n if n else 0.0,
        }
        return self.stats

    def build(self, warc_path, preprocessor, limit=None, progress=5000):
        t0 = time.time()
        for i, doc in enumerate(iter_documents(warc_path), 1):
            self.add_document(doc, preprocessor.process(doc.text))
            if progress and i % progress == 0:
                print(f"  ...{i} docs ({time.time() - t0:.0f}s)")
            if limit and i >= limit:
                break
        self.get_stats()
        return self