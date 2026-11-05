"""T2：預算文件 norm |d|，寫出 norm 檔與 meta。

執行：uv run python HW2/src/build_norms.py --index-dir HW2/index [--scheme ltc]
  預設 ltc → doc_norms.bin + doc_norms.meta.json；
  其他 scheme（加分）→ doc_norms.<scheme>.bin + doc_norms.<scheme>.meta.json（檔名見 weighting.norm_filenames）。
"""
from __future__ import annotations

from pathlib import Path


def build_norms(index_dir: str | Path, scheme: str = "ltc") -> None:
    """一次掃過整個 index，計算每篇文件的 |d|（array('d')，下標 = doc_num）並寫出 meta。

    meta 記錄 log_base、formula、scheme、N、count，以及 lexicon.tsv、postings.bin、
    metadata.json 的 size 與 sha256。結束時印出建置時間與峰值記憶體。
    """
    raise NotImplementedError
