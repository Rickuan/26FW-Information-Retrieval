"""T2 加分：建立 champion list（每個 term 的 tf 前 r 名文件）。

執行：uv run python HW2/src/build_champions.py --index-dir HW2/index [--r 50]
輸出（只收 df > r 的 term；df ≤ r 的 term 由 get_champions 直接回傳完整 postings）：
  champions.r<r>.bin       每個 term 一個 block：[n: uint32 BE] + n × [Δdoc: VByte][tf: VByte]，doc 遞增
  champions.r<r>.tsv       term TAB n TAB byte_offset TAB byte_length（字典序）
  champions.r<r>.meta.json r、選取規則、來源 lexicon.tsv／postings.bin 的 size 與 sha256
"""
from __future__ import annotations

from pathlib import Path


def build_champions(index_dir: str | Path, r: int = 50) -> None:
    """對每個 df > r 的 term，依 (-tf, doc_num) 取前 r 篇，再依 doc_num 遞增寫出。"""
    raise NotImplementedError
