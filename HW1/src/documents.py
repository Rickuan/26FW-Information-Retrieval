"""對外介面：WARC → Document。

- iter_documents(path, stats)：indexer 唯一需要的入口。
- to_document(resp, stats)：單筆轉換；診斷工具需要原始 body 時，
  用 iter_responses + to_document，確保與 indexer 走同一套規則。
空文件（擷取後無文字）也會產出，以保留 docID 對照完整性。
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field

from extract import MOJIBAKE, classify, extract_text
from warc import WarcResponse, iter_responses


@dataclass(frozen=True, slots=True)
class Document:
    doc_num: int
    trec_id: str
    url: str
    kind: str     # 'html' / 'plain'
    text: str


@dataclass
class ExtractionStats:
    total: int = 0
    kept: int = 0
    empty: int = 0
    with_replacement_char: int = 0
    mojibake_remaining: int = 0
    content_types: Counter = field(default_factory=Counter)
    excluded: Counter = field(default_factory=Counter)

    @property
    def n_excluded(self) -> int:
        return sum(self.excluded.values())

    def summary(self) -> str:
        lines = [
            f"response 紀錄總數: {self.total}",
            f"保留: {self.kept}（其中擷取後無文字: {self.empty}）",
            f"排除: {self.n_excluded}",
            f"含 U+FFFD 的文件: {self.with_replacement_char}",
            f"殘留亂碼的文件: {self.mojibake_remaining}",
        ]
        for reason, n in self.excluded.most_common():
            lines.append(f"  排除原因 {n:6d}  {reason}")
        consistent = self.total == self.kept + self.n_excluded
        lines.append(f"一致性 total == kept + excluded: {'✓' if consistent else '✗'}")
        return "\n".join(lines)


def to_document(resp: WarcResponse, stats: ExtractionStats | None = None) -> Document | None:
    if stats is not None:
        stats.total += 1
        stats.content_types[resp.content_type] += 1

    kind, reason = classify(resp.content_type, resp.body)
    if kind == "exclude":
        if stats is not None:
            stats.excluded[reason] += 1
        return None

    try:
        text = extract_text(resp.body, kind)
    except Exception as e:  # noqa: BLE001  bs4/lxml 對壞 HTML 可能丟各種例外
        if stats is not None:
            stats.excluded[f"parse error: {type(e).__name__}"] += 1
        return None

    if stats is not None:
        stats.kept += 1
        if not text:
            stats.empty += 1
        if "\ufffd" in text:
            stats.with_replacement_char += 1
        if MOJIBAKE.search(text):
            stats.mojibake_remaining += 1

    return Document(resp.doc_num, resp.trec_id, resp.url, kind, text)


def iter_documents(path, stats: ExtractionStats | None = None) -> Iterator[Document]:
    for resp in iter_responses(path):
        doc = to_document(resp, stats)
        if doc is not None:
            yield doc