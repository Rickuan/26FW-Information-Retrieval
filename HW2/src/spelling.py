"""T4b／T4c：拼字更正（只提供「Did you mean」建議，不自動替換）與 Soundex。

T4c（T4.md §6.8.3、§6.8.5）起，suggest、suggest_soundex 的輸入與回傳都是原字（retreival → retrieval），
在原字詞彙（surface.py 的 SurfaceVocab，讀 HW2/index/surface_vocab.*）上比對，不再碰 stem 過的 dictionary。
k-gram index 與 Soundex 對照表都只有一份，由 SurfaceVocab 第一次使用時建立並快取（拼字、wildcard、
SOUNDEX() 共用）；這裡只讀不改。觸發條件包在 did_you_mean，比的是原字的 df。
"""
from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from surface import bigrams, load_surface

if TYPE_CHECKING:
    from writer import IndexReader

JACCARD_MIN = 0.3


def _osa(a: str, b: str) -> int:
    """Damerau 距離的 OSA（optimal string alignment）版本：插入、刪除、替換、相鄰對調各算 1。"""
    la, lb = len(a), len(b)
    prev2: list[int] = []
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        ai = a[i - 1]
        for j in range(1, lb + 1):
            bj = b[j - 1]
            d = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ai != bj))
            if i > 1 and j > 1 and ai == b[j - 2] and a[i - 2] == bj:
                d = min(d, prev2[j - 2] + 1)
            cur[j] = d
        prev2, prev = prev, cur
    return prev[lb]


def suggest(word: str, reader: IndexReader, limit: int = 5) -> list[str]:
    """回傳原字 word 的拼字建議（原字），最多 limit 個（§6.8.3、§8 G3）。

    1. 原字 k-gram index 上算 bigram（前後加 $）的 Jaccard，≥ JACCARD_MIN 的成為候選
    2. 排除輸入本身、stopword（stem 是空字串），以及 stem 與輸入的 stem 相同的原字（改了 query 也不變）
    3. 依 (Damerau-OSA 距離, -原字 df, 原字) 排序
    4. 依 stem 去重：每個 stem 只保留排序最前面的原字，也就是 OSA 最小的（同距離才比 df），再取前 limit 個

    word 是使用者輸入的原字（tokenize 後的一個 token），這裡只再做 casefold。
    查 index 時用 load_surface(reader).stem(s) 取建議的 stem；顯示給使用者的是原字。
    """
    if limit < 1:
        return []
    word = word.casefold()
    sv = load_surface(reader)
    index, sizes = sv.kgram()
    grams = bigrams(word)
    overlap: dict[int, int] = defaultdict(int)
    for g in grams:
        for wid in index.get(g, ()):
            overlap[wid] += 1
    n = len(grams)
    in_stem = sv.stem_of_any(word)
    words, stems, dfs = sv.words, sv.stems, sv.dfs
    cands = []
    for wid, c in overlap.items():
        if c / (n + sizes[wid] - c) >= JACCARD_MIN:
            st = stems[wid]
            if st and st != in_stem and words[wid] != word:
                cands.append(wid)
    cands.sort(key=lambda i: (_osa(word, words[i]), -dfs[i], words[i]))
    seen: set[str] = set()
    out: list[str] = []
    for i in cands:
        if stems[i] in seen:
            continue
        seen.add(stems[i])
        out.append(words[i])
        if len(out) == limit:
            break
    return out


def did_you_mean(word: str, reader: IndexReader, show: int = 3) -> list[str]:
    """T7 用的「Did you mean」：觸發時回傳 suggest(word)[:show]，否則回傳 []（§6.8.3、§8 G4）。

    令 s = suggest(word)。觸發條件是 s 非空，而且 原字 df(word) == 0 或 原字 df(s[0]) ≥ 原字 df(word) × 10；
    兩邊比的都是原字詞彙的 df（不是 stem 的 reader.df）。
    第一次呼叫要付 load_surface（約 0.5 s）與建原字 k-gram index（約 1.1 s）的成本，
    新 process 中共約 1.6 s（T4.md §9.1）；之後每次約 10–45 ms。建議 T7 只在結果很少時才呼叫。
    """
    word = word.casefold()
    s = suggest(word, reader)
    if not s:
        return []
    sv = load_surface(reader)
    d = sv.df(word)
    if d == 0 or sv.df(s[0]) >= d * 10:
        return s[:show]
    return []


_SOUNDEX_CODE = {c: d for d, letters in
                 {"1": "BFPV", "2": "CGJKQSXZ", "3": "DT", "4": "L", "5": "MN", "6": "R"}.items()
                 for c in letters}


def soundex(word: str) -> str:
    """American Soundex 編碼（第一個字母 + 3 位數字，例如 Robert → R163）。

    只看 ASCII 字母（其餘字元略過）；沒有任何字母時回傳空字串。
    相鄰同碼只記一次，第一個字母也算在內（Pfister → P236）；h／w 不隔開同碼（Ashcraft → A261），
    母音（a e i o u y）會隔開（Tymczak → T522）。
    """
    letters = [c for c in word.upper() if "A" <= c <= "Z"]
    if not letters:
        return ""
    first = letters[0]
    digits: list[str] = []
    prev = _SOUNDEX_CODE.get(first, "")
    for c in letters[1:]:
        if c in "HW":
            continue  # 不改 prev：h／w 兩側的同碼視為相鄰
        d = _SOUNDEX_CODE.get(c, "")
        if d and d != prev:
            digits.append(d)
            if len(digits) == 3:
                break
        prev = d  # 母音的 d 是 ""，會隔開兩側的同碼
    return (first + "".join(digits) + "000")[:4]


def suggest_soundex(word: str, reader: IndexReader, limit: int = 5) -> list[str]:
    """回傳與 word 同 Soundex 碼的原字，最多 limit 個；輸入與回傳都是原字（§6.8.5 G6）。

    使用 SurfaceVocab.soundex_groups()（與 SOUNDEX() 共用的唯一一份對照表，只收純 ASCII 字母的原字）。
    只依 (-原字 df, 原字) 排序，不考慮像不像；排除輸入本身、stopword、與輸入同 stem 的原字，
    再依 stem 去重（每個 stem 只保留 df 最高的原字）。
    """
    word = word.casefold()
    code = soundex(word)
    if not code or limit < 1:
        return []
    sv = load_surface(reader)
    in_stem = sv.stem_of_any(word)
    seen: set[str] = set()
    out: list[str] = []
    for i in sv.soundex_groups().get(code, ()):
        w, st = sv.words[i], sv.stems[i]
        if w == word or not st or st == in_stem or st in seen:
            continue
        seen.add(st)
        out.append(w)
        if len(out) == limit:
            break
    return out
