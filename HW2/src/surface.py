"""T4c：原字詞彙層（surface vocabulary）的讀取與核對（T4.md §6.8.1）。

surface_vocab.tsv 由 build_surface_vocab.py 從 HW1/output（未 stem 的 index）建出，放在 HW2/index；
每列是一個原字、它在 HW1 index 的 df，以及用 Preprocessor.normalize_token 算出的 stem
（stopword 記空字串）。查詢時只讀 HW2/index 的 surface_vocab.*，不讀 HW1/output。

資料層：surface_stem、load_surface、SurfaceVocab（df、stem、stem_of_any）。
SurfaceVocab 另有延遲建立的原字 k-gram index（§6.8.2，拼字與 wildcard 共用）、wildcard 比對（§6.8.4），
以及整個專案唯一的一份 Soundex 分組（§6.8.5，SOUNDEX() 與 suggest_soundex 共用）。
"""
from __future__ import annotations

import csv
import json
import re
import weakref
from array import array
from collections import defaultdict
from typing import TYPE_CHECKING

from tokenizer import Preprocessor

if TYPE_CHECKING:
    from writer import IndexReader

FORMAT = 1
TSV_NAME = "surface_vocab.tsv"
META_NAME = "surface_vocab.meta.json"
HEADER = ["word", "df", "stem"]
SOURCES = ("lexicon.tsv", "metadata.json")
STEM_RULE = "per-token: casefold → stopword → stem if isalpha (no tokenize)"

# reader → SurfaceVocab（與 spelling.py 相同，依 reader 快取在模組層級，writer.py 不動）
_surface_cache: "weakref.WeakKeyDictionary[IndexReader, SurfaceVocab]" = weakref.WeakKeyDictionary()


def surface_stem(pre: Preprocessor, word: str) -> str:
    """原字的 stem：逐 token 規則，不經過 tokenize；stopword 回傳空字串。

    只是 pre.normalize_token 的薄包裝，不另外實作 stopword 判斷或 stem（§8 G1）。
    """
    return pre.normalize_token(word) or ""


def bigrams(word: str) -> set[str]:
    """word 的 bigram 集合，前後加 $（retrieval → $r、re、…、l$）。拼字的 Jaccard 與 k-gram index 共用。"""
    s = f"${word}$"
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _fragments(pattern: str) -> list[str]:
    return pattern.split("*")


def pattern_bigrams(pattern: str) -> set[str]:
    """wildcard pattern 的固定片段的 bigram 聯集：第一段前面加 $、最後一段後面加 $（§6.8.4 第 1 步）。

    co*tion → $c、co、ti、io、on、n$；*mon → mo、on、n$；*x* → 空集合（片段太短又沒有邊界）。
    """
    frags = _fragments(pattern)
    frags[0] = "$" + frags[0]
    frags[-1] = frags[-1] + "$"
    return {f[i:i + 2] for f in frags for i in range(len(f) - 1)}


def pattern_regex(pattern: str) -> re.Pattern[str]:
    """只有 * 是萬用字元：每個固定片段 re.escape 後用 .* 接起來（不用 fnmatch，它會把 ?、[...] 當萬用字元）。"""
    return re.compile(".*".join(re.escape(f) for f in _fragments(pattern)), re.S)


class SurfaceVocab:
    """原字詞彙：words（已排序）、dfs（原字 df）、stems（stopword 為空字串）。

    df()、stem() 只做精確比對，不對輸入做 casefold。
    kgram()、soundex_groups() 第一次呼叫時才建立，之後快取在這個物件上（_kgram、_soundex）。
    """

    def __init__(self, words: list[str], dfs: array, stems: list[str], pre: Preprocessor) -> None:
        self.words = words
        self.dfs = dfs
        self.stems = stems
        self.pre = pre
        self.word_id: dict[str, int] = {w: i for i, w in enumerate(words)}
        self._kgram: tuple[dict[str, array], array] | None = None
        self._soundex: dict[str, list[int]] | None = None

    def __len__(self) -> int:
        return len(self.words)

    def __contains__(self, word: str) -> bool:
        return word in self.word_id

    def df(self, word: str) -> int:
        """原字的 df（HW1 index）；原字不存在時回傳 0。"""
        i = self.word_id.get(word)
        return 0 if i is None else self.dfs[i]

    def stem(self, word: str) -> str | None:
        """原字的 stem（stopword 為空字串）；原字不存在時回傳 None。"""
        i = self.word_id.get(word)
        return None if i is None else self.stems[i]

    def stem_of_any(self, word: str) -> str:
        """任何字的 stem：在詞彙中就查表，否則用 surface_stem 現算。"""
        i = self.word_id.get(word)
        return self.stems[i] if i is not None else surface_stem(self.pre, word)

    def kgram(self) -> tuple[dict[str, array], array]:
        """原字的 bigram index（§6.8.2）：(gram → 遞增的原字 id array('I'), 每個原字的 bigram 數 array('H'))。"""
        if self._kgram is None:
            index: dict[str, array] = defaultdict(lambda: array("I"))
            sizes = array("H")
            for wid, word in enumerate(self.words):
                grams = bigrams(word)
                sizes.append(min(len(grams), 0xFFFF))
                for g in grams:
                    index[g].append(wid)
            self._kgram = (dict(index), sizes)
        return self._kgram

    def wildcard_candidates(self, pattern: str) -> list[int] | range:
        """k-gram 篩選（§6.8.4 第 2 步）：pattern 所有 bigram 的 posting 交集，從最短的開始，變空就提早結束。

        沒有任何 bigram（*x*）時回傳全部原字的 id。結果只是候選，必須再經過 match_wildcard 的 post-filter。
        """
        grams = pattern_bigrams(pattern)
        if not grams:
            return range(len(self.words))
        index, _ = self.kgram()
        posts = []
        for g in grams:
            p = index.get(g)
            if p is None:
                return []
            posts.append(p)
        posts.sort(key=len)
        cur = set(posts[0])
        for p in posts[1:]:
            cur.intersection_update(p)
            if not cur:
                return []
        return sorted(cur)

    def match_wildcard(self, pattern: str) -> list[int]:
        """pattern（含 *，只有 * 是萬用字元）完整比對到的原字 id：k-gram 篩選 + regex post-filter（§6.8.4）。"""
        rx = pattern_regex(pattern).fullmatch
        words = self.words
        return [i for i in self.wildcard_candidates(pattern) if rx(words[i])]

    def soundex_groups(self) -> dict[str, list[int]]:
        """Soundex 碼 → 原字 id，每組依 (-原字 df, 原字) 排序；只收 isascii() and isalpha() 的原字（§6.8.5）。

        整個專案只有這一份對照表（§8 G6）：SOUNDEX() 的展開與 spelling.suggest_soundex 共用。
        """
        if self._soundex is None:
            from spelling import soundex  # 函式內才 import：spelling 會 import 本模組的 bigrams

            groups: dict[str, list[int]] = defaultdict(list)
            for wid, word in enumerate(self.words):
                if word.isascii() and word.isalpha():
                    groups[soundex(word)].append(wid)
            dfs, words = self.dfs, self.words
            self._soundex = {code: sorted(ids, key=lambda i: (-dfs[i], words[i])) for code, ids in groups.items()}
        return self._soundex


def load_surface(reader: IndexReader) -> SurfaceVocab:
    """讀取並核對 reader.output_dir 的 surface_vocab.*；結果依 reader 快取。

    Raises:
        FileNotFoundError: surface_vocab.tsv 或 surface_vocab.meta.json 不存在。
        ValueError: meta 與目前的 index 不一致（format、N、preprocessor、sources），
            或 tsv 的表頭、列數與 meta 不符。訊息含欄位名稱。
    """
    cached = _surface_cache.get(reader)
    if cached is not None:
        return cached

    tsv_path = reader.output_dir / TSV_NAME
    meta_path = reader.output_dir / META_NAME
    for path in (tsv_path, meta_path):
        if not path.exists():
            raise FileNotFoundError(
                f"{path} not found; run build_surface_vocab.py first "
                "(`uv run python HW2/src/build_surface_vocab.py`, needs HW1/output)"
            )
    with meta_path.open("r", encoding="utf-8") as f:
        meta = json.load(f)
    pre_cfg = reader.get_metadata()["preprocessor"]
    expected = {"format": FORMAT, "N": reader.N, "preprocessor": pre_cfg}
    for key, want in expected.items():
        if meta.get(key) != want:
            raise ValueError(f"{META_NAME}: {key} is {meta.get(key)!r}, expected {want!r}")
    reader._check_sources(meta, META_NAME, SOURCES)

    # stem 改用 lexicon 的字串物件（intern），減少記憶體；暫時的對照表用完即丟
    canon = {t: t for t in reader.vocabulary()}
    words: list[str] = []
    dfs = array("I")
    stems: list[str] = []
    with tsv_path.open("r", encoding="utf-8", newline="") as f:
        rows = csv.reader(f, delimiter="\t")
        header = next(rows, None)
        if header != HEADER:
            raise ValueError(f"{TSV_NAME}: header is {header!r}, expected {HEADER!r}")
        for row in rows:
            word, df, stem = row
            words.append(word)
            dfs.append(int(df))
            stems.append(canon.get(stem, stem))
    del canon
    if len(words) != meta.get("count"):
        raise ValueError(f"{TSV_NAME}: {len(words)} rows, meta count is {meta.get('count')!r}")
    n_stop = stems.count("")
    if n_stop != meta.get("stopword_count"):
        raise ValueError(
            f"{TSV_NAME}: {n_stop} rows with empty stem, meta stopword_count is "
            f"{meta.get('stopword_count')!r}"
        )

    vocab = SurfaceVocab(words, dfs, stems, Preprocessor.from_config(pre_cfg))
    _surface_cache[reader] = vocab
    return vocab
