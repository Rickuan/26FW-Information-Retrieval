"""W：共用權重函式與公式常數（由 T2 負責）。

build_norms（T2）、IndexReader.get_norms（T2）與 rank（T6）都只 import 這裡，不自己寫公式。
"""
from __future__ import annotations

LOG_BASE = 10
DEFAULT_SCHEME = "ltc"
FORMULA = "(1+log10 tf)*log10(N/df)"  # DEFAULT_SCHEME 的公式，寫入 doc_norms.meta.json 供核對


def weight(tf: int, df: int, N: int, scheme: str = DEFAULT_SCHEME) -> float:
    """SMART 權重，不含 normalization（normalization 由 get_norms 的 |d| 負責）。

    scheme 是 tf／idf／normalization 三個字母，weight 只看前兩個：
      tf：n = tf，l = 1 + log10 tf，b = 1（tf > 0 時）
      idf：n = 1，t = log10(N / df)
    預設 "ltc" 即 (1 + log10 tf) * log10(N / df)。tf == 0 或 df == 0 回傳 0.0。
    核心（T2）只需支援 "ltc"；其他 scheme 屬於 T2 加分項。

    Raises:
        ValueError: scheme 不是合法的三個字母，或尚未支援。
    """
    raise NotImplementedError


def norm_filenames(scheme: str = DEFAULT_SCHEME) -> tuple[str, str]:
    """回傳 (norm 檔名, meta 檔名)。

    "ltc" → ("doc_norms.bin", "doc_norms.meta.json")；
    其他 scheme（加分）→ ("doc_norms.<scheme>.bin", "doc_norms.<scheme>.meta.json")。
    """
    raise NotImplementedError
