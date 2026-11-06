# T1 Index 載入、df 與前處理設定還原

## 1. 目標
讓 HW2 從 `HW2/index/` 取得 N 與每個 term 的 df，並用 index 當初的前處理設定建立 query 端的 Preprocessor。

## 2. Index 來源（`HW2/index/`）
內容來自 HW1 的 stop+stem 版（`HW1/output_main`），已確認與繳交的 `postings.txt`、`dictionary.txt` 逐 byte 相同（`postings.bin` 也逐 byte 相同）。注意：不是 `HW1/output`，那份是未 stem 的版本。

`metadata.json` 的 preprocessor 設定是 `casefold=True`、`stopword=True`、`stem=True`、`lemma=False`。這是 stop+stem 版本，與組內的決定一致。

| 檔案 | 用途 | T1 程式會讀 |
| --- | --- | --- |
| `lexicon.tsv` | `term \t df \t offset \t length`，共 573,233 行 | ✅ df、offset |
| `postings.bin` | VByte+Delta 編碼的 postings | ✅（`get_postings`，測試對照用） |
| `metadata.json` | `N`、`preprocessor` 設定等 | ✅ N、preprocessor |
| `doc_map.json` | doc_num → trec_id／url／doc_len | ❌（T7 才可能用） |
| `dictionary.txt`、`postings.txt` | 作業規定的文字格式，繳交用 | ❌ |

## 3. 接口
```python
# HW2/src/writer.py
class IndexReader:
    N: int                                    # metadata["N"]（實作為 property）
    def df(self, term: str) -> int: ...       # term 不存在回傳 0

# HW2/src/tokenizer.py
class Preprocessor:
    @classmethod
    def from_config(cls, cfg: dict) -> "Preprocessor": ...  # 缺 lemma 時預設 False；缺其他欄位拋 ValueError
```
使用範例：
```python
reader = IndexReader("HW2/index")
pre = Preprocessor.from_config(reader.get_metadata()["preprocessor"])
terms = [t for _, t in pre.process("open source AND Linux")]   # ['open', 'sourc', 'linux']
print(reader.N, {t: reader.df(t) for t in terms})               # 34786 {'open': 5944, 'sourc': 4062, 'linux': 997}
```

## 4. 改動
| 位置 | 改法 |
| --- | --- |
| `HW2/src/writer.py:363` `__init__` | `_lexicon` 型別註解與註解改成 `term → (df, offset, length)` |
| `HW2/src/writer.py:372-384` `_load_lexicon` | 回傳型別從 `dict[str, tuple[int, int]]` 改成 `dict[str, tuple[int, int, int]]`；第 381 行不再丟棄 df，改存 `lexicon[term] = (df, offset, length)`；docstring 同步更新 |
| `HW2/src/writer.py:412` `get_postings` | 解包改成 `_df, offset, length = lexicon[term]`，其餘不動 |
| `HW2/src/writer.py:447-450` `N` | `return int(self.get_metadata()["N"])` |
| `HW2/src/writer.py:452-458` `df` | `entry = self._load_lexicon().get(term)`；`return entry[0] if entry else 0` |
| `HW2/src/tokenizer.py:107-114` `from_config` | 嚴格模式：`cfg` 是 `None` 或 `{}` 時拋出 `ValueError`。`casefold`、`stopword`、`stem` 缺任何一個也拋出 `ValueError`，訊息列出缺少的欄位（例如 `missing = [k for k in ("casefold", "stopword", "stem") if k not in cfg]`）。只有 `lemma` 可以缺，缺時用 `cfg.get("lemma", False)`。未知欄位忽略。（docstring 已更新為嚴格模式） |

`from_config` 採嚴格模式的理由：如果悄悄套用預設值，query 端的前處理會和 index 不一致，結果全錯，卻不會有任何錯誤訊息。

df 和 offset 放在同一個 tuple，不另開 dict，這樣 57 萬個 term 不會多一份 key 的記憶體。T3 也可以直接沿用這個 lexicon。`_lexicon` 中只有 `get_postings`（:409 取得 lexicon，:412 解包）會解包 tuple；`vocab_size`（:437）和 `__contains__`（:441）不受欄位數影響。

**與總規劃（`HW2/plans/00-overview.md`）的差異**
- 總規劃寫「直接改 HW1 的 writer.py／tokenizer.py」，實際上改的是 `HW2/src/` 的副本，`HW1/` 不動。（已回寫）
- 總規劃寫「把 `HW1/output` 複製到 `HW2/index/`」，實際來源是 `HW1/output_main`。（已回寫）
- `writer.py:352`、`:381`、`:402`、`:427` 仍然正確；`tokenizer.py:94-106` 也正確。stub 的位置在 `writer.py:447-458`、`tokenizer.py:107-114`。
- 總規劃說「三處重複的設定還原」在 `main.py:104`、`:214`、`:423`。實際上 `main.py` 只存在 `HW1/src/`，沒有複製到 `HW2/src`。三處的 `Preprocessor(` 分別在第 103、214、423 行，其中只有 214 是從 metadata 還原，另外兩處是從 CLI 參數建立。另有一處 `HW1/src/verify_output.py:64-69` 也是從 metadata 還原，而且沒有讀 lemma。T1 不改這些地方。

## 5. 驗收測試（`HW2/tests/t1.test.py`）
仿照 HW1 `*.test.py` 的 `check()` 腳本風格；用 `sys.path.insert` 加入 `HW2/src`，index 路徑以 `__file__` 推算。執行方式：`uv run python HW2/tests/t1.test.py`。
- [ ] `reader.N == 34786`
- [ ] `df('linux') == 997`、`df('sourc') == 4062`、`df('不存在的詞') == 0`
- [ ] 5 個抽樣 term（`linux`、`sourc`、`open`，以及 lexicon 的第一個和最後一個 term）的 `df(t) == len(get_postings(t))`
- [ ] `Preprocessor.from_config(metadata["preprocessor"])` 處理 `"open source AND Linux"`，得到的 term 是 `['open', 'sourc', 'linux']`
- [ ] `from_config(metadata["preprocessor"])` 建立的 Preprocessor，`casefold`、`stopword`、`stem`、`lemma` 都與 metadata 完全一致
- [ ] `from_config({"casefold": True, "stopword": True, "stem": True})` 不報錯，而且 `.lemma is False`
- [ ] `from_config({})` 拋出 `ValueError`
- [ ] `from_config({"casefold": True})` 拋出 `ValueError`，訊息包含 `stopword` 和 `stem`

## 6. 加分項（核心合併後才開始）
兩項都是新增的 method，不改動核心接口。stub 已在 `writer.py` 建立。

### 6.1 `prefix_terms`（優先度：中）
- **評分面向**：query 多樣性（wildcard 的基礎）、效率
- **接口**：`IndexReader.prefix_terms(prefix: str) -> list[str]`（`writer.py:494`）。依字典序回傳以 prefix 開頭的 term；空字串拋出 `ValueError`。
- **改動**：`writer.py`。對 `vocabulary()` 用 `bisect_left(vocab, prefix)` 到 `bisect_left(vocab, prefix[:-1] + chr(ord(prefix[-1]) + 1))` 切片。
- **選型**：比較 HW1 的 `RadixTrie`（`trie.py:35`，`prefix_search` 在 `:108`）和「排序 list + bisect」。下表已在本 index 上預先量測（`perf_counter` + `tracemalloc`），兩者回傳的結果完全相同：

  | 項目 | RadixTrie | 排序 list + bisect |
  | --- | --- | --- |
  | 建置時間 | 3.95 s | 0.07 s |
  | 額外記憶體 | 97 MB | 4 MB（字串與 lexicon 共用） |
  | `comput`（64 筆） | 0.018 ms | 0.001 ms |
  | `a`（31,236 筆） | 10.2 ms | 0.087 ms |

  結論是選 bisect。`lexicon.tsv` 本身已依 Python 字串順序排序（已驗證），所以 `list(lexicon)` 就是排序好的 list，不必再排一次。
- **依賴**：T1 核心（`_load_lexicon`）

### 6.2 `vocabulary`（優先度：中）
- **評分面向**：query 多樣性（拼字更正的基礎）
- **接口**：`IndexReader.vocabulary() -> list[str]`（`writer.py:487`）。回傳快取的同一個 list，呼叫端不可修改。
- **改動**：`writer.py`。第一次呼叫時 `list(self._load_lexicon())` 並快取。
- **依賴**：T1 核心

### 6.3 驗收測試（`HW2/tests/t1_bonus.test.py`）
- [ ] `len(vocabulary()) == 573233`、`vocabulary() == sorted(vocabulary())`、`vocabulary()[0] == ',ltd.is'`、`vocabulary()[-1] == '𣲛'`、`vocabulary() is vocabulary()`
- [ ] `prefix_terms('comput')`：共 64 筆，第一筆是 `'comput'`，全部以 `comput` 開頭，而且已排序
- [ ] `len(prefix_terms('lin')) == 629`、`len(prefix_terms('a')) == 31236`、`prefix_terms('zzzq') == []`
- [ ] `prefix_terms('')` 拋出 `ValueError`
- [ ] **獨立路徑對照**：用 `random.Random(42)` 抽 20 個 term，各取前 1–3 個字元當 prefix。`prefix_terms(p)` 要同時等於暴力掃描 `[t for t in vocabulary() if t.startswith(p)]`，以及 `RadixTrie.prefix_search(p)` 的 key 列表。
- [ ] 記錄 `vocabulary()` 第一次呼叫的時間與 `prefix_terms('a')` 的時間，寫進實作紀錄。

## 7. 不做的事
- 不改 `postings.bin`、`lexicon.tsv` 的格式，也不重建 index
- 不動 `HW1/`（包括 `main.py` 裡重複的設定還原）
- 不實作 T2 `get_norms()`、T3 `get_doc_tf()`

## 8. 待決問題
目前沒有待決問題。原本的兩個問題已經決定：
- **已決定**：`from_config` 採嚴格模式。缺 `casefold`／`stopword`／`stem` 時拋出 `ValueError`，只有 `lemma` 可以缺（預設 False）。不沿用 `Preprocessor.__init__` 或 HW1 `main.py:214` 的預設值。
- **已決定**：`cfg` 是 `{}` 或 `None` 時拋出 `ValueError`，不套用預設值。

## 9. 實作紀錄

### 9.1 結果
- 核心 `HW2/tests/t1.test.py`：實作前 0/15，實作後 15/15；加分完成後重跑仍是 15/15。
- 加分 `HW2/tests/t1_bonus.test.py`：實作前 0/11，實作後 11/11。
- 第 3 節的接口簽名都沒有改。改到的檔案只有 `HW2/src/writer.py`、`HW2/src/tokenizer.py`，另外新增了兩個測試檔。
- `HW2/src/` 裡沒有其他模組讀 `_lexicon`／`_load_lexicon`（已 grep 確認），tuple 從 2 欄改成 3 欄只影響 `get_postings`。

### 9.2 與計畫的差異
- **測試多了一項**：核心測試除了 `from_config({})`，也測 `from_config(None)` 會拋 `ValueError`（第 8 節已決定，但第 5 節的清單沒有列）。所以核心是 15 項，比第 5 節列出的多。
- **測試寫法**：每項 check 都包在 try/except 裡，stub 拋 `NotImplementedError` 時記為 FAIL，不會中斷整支腳本，這樣「先跑一次確認失敗」能看到全部項目。第一個／最後一個 term 是直接讀 `lexicon.tsv` 取得的，不經過 `IndexReader`（實際是 `,ltd.is`、`𣲛`）。
- **`from_config` 的錯誤訊息**：`cfg` 為空時是 `preprocessor config is empty: {}`（或 `None`）；缺欄位時是 `preprocessor config missing fields: stopword, stem`。
- **`IndexReader.__init__` 新增 `self._vocab`**：這是 `vocabulary()` 的快取，第 6.2 節沒有寫明要放在哪裡。
- **`prefix_terms` 多處理一個邊界情況**：prefix 最後一個字元是 U+10FFFF 時無法 `chr(ord(c) + 1)`，改成從 `lo` 往後線性掃描 `startswith`。其他情況照第 6.1 節的寫法。上界的 `bisect_left` 從 `lo` 開始找。
- **行號位移**：`writer.py` 第 23 行新增 `from bisect import bisect_left`，之後的行號全部 +1；`__init__` 多了一行，`_load_lexicon` 之後的行號再 +1。新行號：`IndexReader` :353、`_load_lexicon` :374（存 df 在 :384）、`get_postings` :404（解包在 :414）、`get_doc` :420、`get_metadata` :429、`N` :449-452、`df` :454-461、`vocabulary` :490、`prefix_terms` :500。`tokenizer.py` `from_config` 仍在 :107-108 起，`process` 仍在 :94。

### 9.3 量測（本機 WSL2，`perf_counter`）
| 項目 | 時間 |
| --- | --- |
| `_load_lexicon()`（57 萬行，冷啟動） | 約 430–457 ms |
| `vocabulary()` 第一次（lexicon 已載入） | 7.95 ms |
| `vocabulary()` 額外記憶體（`tracemalloc`） | 4.59 MB（字串與 lexicon 共用） |
| `prefix_terms('comput')`（1000 次平均） | 0.001 ms |
| `prefix_terms('a')`（100 次平均，31,236 筆） | 0.107 ms |
| RadixTrie 建置（只在對照測試中使用） | 1.31 s |

和第 6.1 節預先量測的數字一致（bisect：`comput` 0.001 ms、`a` 0.087 ms、4 MB）。RadixTrie 這次建置只花 1.31 s，比表中的 3.95 s 快；可能是因為這次只插入 `None` 當值，而且沒有開 `tracemalloc`。這不影響選擇 bisect 的結論。

## 10. 一頁文件素材
只根據第 9 節實作紀錄與第 4、8 節的已決定事項整理，沒有新增未量測的數字。

### 10.1 主要特色
1. **query 端的前處理一定和 index 一致**：`Preprocessor.from_config` 只從 `metadata.json` 還原設定，而且採嚴格模式，缺欄位就拋 `ValueError`。前處理不一致不會報錯，只會讓分數全錯，所以值得用嚴格模式擋住。
2. **df 不另開 dict**：lexicon 的 tuple 從 `(offset, length)` 擴成 `(df, offset, length)`，57 萬個 term 不會多一份 key 的記憶體，T3 也直接沿用同一個 lexicon。
3. **prefix 查詢用排序 list + bisect，不用 HW1 的 RadixTrie**：`lexicon.tsv` 本身已排序，不必另外建結構，就能當作 wildcard（T4b）的基礎。

### 10.2 量測數據
皆在本機 WSL2 上用 `perf_counter` 量測（記憶體用 `tracemalloc`），只量一台機器。

| 數據 | 前提條件 | 比較對象 |
| --- | --- | --- |
| `_load_lexicon()` 約 430–457 ms | 冷啟動、讀 573,233 行；每個 process 第一次用 reader 時都要付這筆成本 | 無（這是所有查詢的啟動成本） |
| `vocabulary()` 第一次 7.95 ms、額外 4.59 MB | lexicon 已載入；字串與 lexicon 共用，所以記憶體只有 list 本身 | HW1 `RadixTrie` 建置 1.31 s（只插入 `None` 當值、沒開 `tracemalloc`，只在對照測試中使用） |
| `prefix_terms('comput')` 0.001 ms（64 筆） | 1000 次平均，`vocabulary()` 已快取 | 實作紀錄沒有重測 RadixTrie 的查詢時間 |
| `prefix_terms('a')` 0.107 ms（31,236 筆） | 100 次平均，`vocabulary()` 已快取 | 同上 |
| 測試 15/15（核心）、11/11（加分） | 先在 stub 狀態確認 0/15、0/11 再實作 | 加分 `prefix_terms` 與暴力掃描、`RadixTrie.prefix_search` 對 20 個隨機 prefix 結果相同 |

### 10.3 遇到的困難與解法
- **Index 版本容易拿錯**：總規劃原本寫從 `HW1/output` 複製，但那是未 stem 的版本，交出去的是 `HW1/output_main`（stop+stem）。用錯版本程式照樣能跑，只是結果不同。解法：確認 `HW2/index/` 與繳交的 `dictionary.txt`／`postings.txt` 逐 byte 相同，HW2 程式一律明確指定這個路徑。
- **前處理設定可能悄悄套用預設值**：`Preprocessor.__init__` 和 HW1 `main.py:214` 都有預設值，缺欄位也不會報錯。解法：`from_config` 改成嚴格模式，`None`、`{}` 或缺 casefold／stopword／stem 都拋 `ValueError`，只有 `lemma` 可以缺（預設 False）；測試也涵蓋 `from_config(None)`。
- **`prefix_terms` 的上界在 U+10FFFF 時算不出來**：最後一個字元已是最大 code point，無法 `chr(ord(c) + 1)`。解法：這個情況改成從下界往後線性掃描 `startswith`。

### 10.4 限制
- **每次 CLI 查詢都要付約 0.4 s 的 lexicon 載入**，這是啟動成本，與單次 `df()` 或 prefix 查詢的時間要分開看。
- **`vocabulary()` 回傳的是共用的快取 list**，呼叫端修改它會影響之後所有呼叫；程式沒有保護，只靠約定。
- **與 RadixTrie 的比較只能說「建置快很多」**：實作紀錄只有 RadixTrie 建置時間（1.31 s；計畫階段另量到 3.95 s，兩次差很多），沒有重測它的查詢時間，不能寫出精確的查詢加速倍數。
- **prefix 是對 stem 後的 dictionary 比對**，prefix 本身不做 stem，所以 `computing*` 對不到 `comput`（T4b 的已知限制，原因在 T1 的資料形式）。
- **HW1 裡的設定還原沒有修**：`main.py query` 預設仍讀未 stem 的 `HW1/output`，`verify_output.py` 也沒有讀 lemma；T1 依範圍不動 `HW1/`。
