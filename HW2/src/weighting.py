"""W：共用權重函式與公式常數（由 T2 負責）。

build_norms（T2）、IndexReader.get_norms（T2）與 rank（T6）都只 import 這裡，不自己寫公式。
"""
from __future__ import annotations

import math

LOG_BASE = 10
DEFAULT_SCHEME = "ltc"
FORMULA = "(1+log10 tf)*log10(N/df)"  # DEFAULT_SCHEME 的公式，寫入 doc_norms.meta.json 供核對


# 三個位置各自的字母表：字母 → (計算函式, formula 片段)
_TF = {
    "n": (lambda tf: float(tf), "tf"),
    "l": (lambda tf: 1 + math.log10(tf), "(1+log10 tf)"),
    "b": (lambda tf: 1.0, "1"),
}
_IDF = {
    "n": (lambda N, df: 1.0, "1"),
    "t": (lambda N, df: math.log10(N / df), "log10(N/df)"),
}
_NORM = "nc"  # n = 不正規化，c = cosine


def _parse(scheme: str) -> tuple[str, str, str]:
    """檢查 scheme 是單邊的三個合法字母，回傳 (tf, idf, normalization)。"""
    if (not isinstance(scheme, str) or len(scheme) != 3
            or scheme[0] not in _TF or scheme[1] not in _IDF or scheme[2] not in _NORM):
        raise ValueError(f"invalid scheme: {scheme!r}")
    return scheme[0], scheme[1], scheme[2]


def weight(tf: int, df: int, N: int, scheme: str = DEFAULT_SCHEME) -> float:
    """SMART 權重，不含 normalization（normalization 由 get_norms 的 |d| 負責）。

    scheme 是 tf／idf／normalization 三個字母，weight 只看前兩個：
      tf：n = tf，l = 1 + log10 tf，b = 1（tf > 0 時）
      idf：n = 1，t = log10(N / df)
    預設 "ltc" 即 (1 + log10 tf) * log10(N / df)。tf == 0 或 df == 0 回傳 0.0。
    第三個字母只檢查合法性（n 或 c）。

    Raises:
        ValueError: scheme 不是合法的三個字母。
    """
    t, i, _n = _parse(scheme)
    if tf <= 0 or df <= 0:
        return 0.0
    return _TF[t][0](tf) * _IDF[i][0](N, df)


def formula(scheme: str = DEFAULT_SCHEME) -> str:
    """scheme 的 tf 片段 + "*" + idf 片段，例如 formula("ltc") == FORMULA。"""
    t, i, _n = _parse(scheme)
    return f"{_TF[t][1]}*{_IDF[i][1]}"


def norm_filenames(scheme: str = DEFAULT_SCHEME) -> tuple[str, str]:
    """回傳 (norm 檔名, meta 檔名)。

    "ltc" → ("doc_norms.bin", "doc_norms.meta.json")；
    其他 normalization 為 c 的 scheme → ("doc_norms.<scheme>.bin", "doc_norms.<scheme>.meta.json")。
    normalization 為 n 的 scheme 沒有 norm 檔，拋出 ValueError。
    """
    _t, _i, n = _parse(scheme)
    if n == "n":
        raise ValueError(f"scheme {scheme!r} has no norm file (normalization n)")
    if scheme == DEFAULT_SCHEME:
        return "doc_norms.bin", "doc_norms.meta.json"
    return f"doc_norms.{scheme}.bin", f"doc_norms.{scheme}.meta.json"
