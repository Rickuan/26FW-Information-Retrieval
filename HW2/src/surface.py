"""T4c：原字詞彙層（surface vocabulary）的讀取與核對（T4.md §6.8.1）。

surface_vocab.tsv 由 build_surface_vocab.py 從 HW1/output（未 stem 的 index）建出，放在 HW2/index；
每列是一個原字、它在 HW1 index 的 df，以及用 Preprocessor.normalize_token 算出的 stem
（stopword 記空字串）。查詢時只讀 HW2/index 的 surface_vocab.*，不讀 HW1/output。

本模組目前只有資料層：surface_stem、load_surface、SurfaceVocab（df、stem、stem_of_any）。
k-gram index、Soundex 分組與 wildcard 比對（§6.8.2–§6.8.5）尚未實作。
"""
from __future__ import annotations

import csv
import json
import weakref
from array import array
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


class SurfaceVocab:
    """原字詞彙：words（已排序）、dfs（原字 df）、stems（stopword 為空字串）。

    df()、stem() 只做精確比對，不對輸入做 casefold。
    """

    def __init__(self, words: list[str], dfs: array, stems: list[str], pre: Preprocessor) -> None:
        self.words = words
        self.dfs = dfs
        self.stems = stems
        self.pre = pre
        self.word_id: dict[str, int] = {w: i for i, w in enumerate(words)}

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
