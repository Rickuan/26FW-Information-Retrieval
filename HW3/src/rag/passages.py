"""把清理後的文件文字切成 passage（規格 2.4；規則細節見 plans/A2-docstore-passages.md 第 3 節）。

純函式：不讀 config、不碰 SQLite；passage_words / passage_stride 由呼叫端從 config 傳入。

規則（W = passage_words、S = passage_stride、words = text.split()、n = len(words)）：
1. n == 0（空文件或只有空白）→ 沒有 passage，也不佔 pid。
2. n <= W，或 n < MIN_SPLIT_WORDS → 整篇一段。
3. 其餘：起點 0, S, 2S, …，每段 [s, min(s + W, n))；某段結尾等於 n 就停止。
   最後一段一定止於 n（不漏尾端的字），且至少 W - S + 1 字。
4. passage 文字 = " ".join(words[start:end])，空白一律正規化為單一空白。
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator

MIN_SPLIT_WORDS = 30   # 少於此字數的文件整篇一段（W >= 30 時已被規則 2 涵蓋）


def _check_params(passage_words: int, passage_stride: int) -> None:
    if passage_words < 1:
        raise ValueError(f"passage_words must be >= 1, got {passage_words!r}")
    if not 1 <= passage_stride <= passage_words:
        # stride > words 會在相鄰兩段之間漏字；stride = 0 會無窮迴圈
        raise ValueError(
            f"passage_stride must be in [1, passage_words={passage_words}], got {passage_stride!r}"
        )


def split_passages(text: str, passage_words: int, passage_stride: int) -> list[tuple[int, int, str]]:
    """切分一篇文件。

    Returns:
        [(start_word, end_word, passage_text)]，位置含頭不含尾、對應 text.split() 的字序號，依 start 遞增。
    """
    _check_params(passage_words, passage_stride)
    words = text.split()
    n = len(words)
    if n == 0:
        return []
    if n <= passage_words or n < MIN_SPLIT_WORDS:
        return [(0, n, " ".join(words))]
    out: list[tuple[int, int, str]] = []
    start = 0
    while True:
        end = min(start + passage_words, n)
        out.append((start, end, " ".join(words[start:end])))
        if end == n:
            return out
        start += passage_stride


def number_passages(
    docs: Iterable[tuple[int, str]], passage_words: int, passage_stride: int
) -> Iterator[tuple[int, int, int, int, str]]:
    """依 docs 的順序切分並編號。

    Args:
        docs: (docid, text) 的 iterable（建置時為 WARC 順序 = docid 遞增）。

    Yields:
        (pid, docid, start_word, end_word, passage_text)；pid 從 0 起全域連續，空文件不佔號。
    """
    _check_params(passage_words, passage_stride)
    pid = 0
    for docid, text in docs:
        for start, end, ptext in split_passages(text, passage_words, passage_stride):
            yield pid, docid, start, end, ptext
            pid += 1
