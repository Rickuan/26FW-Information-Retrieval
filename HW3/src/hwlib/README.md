# hwlib — HW1/HW2 程式碼副本

本目錄是 `HW2/src` 部分模組的副本，供 HW3 以套件方式匯入（見 `HW3/plans/HW3.md` 1.1、2.1）。
**只修改了 import 語句**（扁平絕對匯入 → 套件內相對匯入），其他程式碼與來源逐位元組相同。

- 來源路徑：`HW2/src/`
- 來源 commit：`fb1bb36971cfd997433e7f9b7ba6843d4efa9a13`
- 使用限制：只能透過 `rag/hw_bridge.py` 使用（1.6-3）

## 複製的檔案

`warc.py`、`extract.py`、`documents.py`、`tokenizer.py`、`indexer.py`、`trie.py`、`writer.py`、
`weighting.py`、`build_norms.py`、`rank.py`，外加新建的空白 `__init__.py`。

## import 修改紀錄（行號為修改後檔案的行號，與原檔相同）

| 檔案 | 行 | 原本 | 修改後 |
|---|---|---|---|
| `build_norms.py` | 17 | `from weighting import ...` | `from .weighting import ...` |
| `build_norms.py` | 18 | `from writer import ...` | `from .writer import ...` |
| `documents.py` | 14 | `from extract import ...` | `from .extract import ...` |
| `documents.py` | 15 | `from warc import ...` | `from .warc import ...` |
| `extract.py` | 19 | `from warc import NO_CONTENT_TYPE` | `from .warc import NO_CONTENT_TYPE` |
| `indexer.py` | 10 | `from documents import iter_documents` | `from .documents import iter_documents` |
| `indexer.py` | 11 | `from tokenizer import Preprocessor` | `from .tokenizer import Preprocessor` |
| `indexer.py` | 12 | `from trie import RadixTrie` | `from .trie import RadixTrie` |
| `rank.py` | 12 | `from weighting import formula, weight` | `from .weighting import formula, weight` |
| `rank.py` | 15 | `from writer import IndexReader`（位於 `if TYPE_CHECKING:` 區塊內） | `from .writer import IndexReader` |
| `writer.py` | 32 | `from indexer import DocEntry, Indexer, Posting` | `from .indexer import DocEntry, Indexer, Posting` |
| `writer.py` | 33 | `from weighting import ...` | `from .weighting import ...` |

未修改：`tokenizer.py`、`trie.py`、`warc.py`、`weighting.py`（沒有匯入其他本地模組；
`tokenizer.py` 函式內的 `from nltk...` 是第三方套件，不需修改）。

## 驗證方式

```bash
# 在 repo 根目錄執行；預期只有上表的 import 行有差異
for f in warc extract documents tokenizer indexer trie writer weighting build_norms rank; do
  diff HW2/src/$f.py HW3/src/hwlib/$f.py
done
```

## 依賴版本鎖定：charset-normalizer==3.5.2

`extract.py` 以 bs4 的 `UnicodeDammit` 偵測編碼；bs4 會自動使用已安裝的 `charset-normalizer`，
偵測結果會隨它的版本改變。HW3 原本解析出 3.5.3，全量建置時有 29 篇文件（亂碼 / 非 UTF-8 頁面）
解碼結果與 HW2 索引不同（vocab +241、tokens +451），`lexicon.tsv`、`postings.bin`、`doc_map.json`
都不再逐位元組相同。同一份程式碼在 3.5.2（根目錄環境的版本）下 29 篇全部與 HW2 一致，
因此在 `HW3/pyproject.toml` 鎖定 `charset-normalizer==3.5.2`。
升級 bs4、charset-normalizer 等套件前，需重新確認建置結果與 HW2/index 一致。

## 注意

- `build_norms.py` 底部的 `if __name__ == "__main__":` CLI 因為改成相對匯入，已無法以
  `python hwlib/build_norms.py` 直接執行；HW3 一律透過 `hw_bridge.build_doc_norms()` 呼叫。
- 停用詞需要 NLTK 的 `stopwords` 資料，第一次執行時會自動下載；手動下載：
  `uv run python -c "import nltk; nltk.download('stopwords')"`。
