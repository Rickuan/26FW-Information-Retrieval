# T3 只取 doc／tf 的快速讀取

> 狀態：T1（`done.T1.md`）、T2（`done.T2.md`）已完成，本計畫已依兩者的實作紀錄更新行號與接口；可以開始實作。行號以 `grep -n` 對照目前的 `HW2/src/` 確認過。

## 1. 目標
新增 `get_doc_tf(term)`，只解出 (doc_num, tf)、跳過 positions，讓 T5、T6 取 posting 時不必建立 `Posting` 物件。

## 2. Index 來源（`HW2/index/`）
使用 T1 的 stop+stem index（N = 34,786，573,233 個 term），只讀 `lexicon.tsv`（取 offset、length）與 `postings.bin`。加分項另外讀 T2 產出的 `champions.r50.{bin,tsv,meta.json}`。

T1 提供的接口（已實作）：
- `IndexReader._load_lexicon()`（`writer.py:389`）回傳 `dict[str, tuple[int, int, int]]`，即 `term → (df, offset, length)`，順序與 `lexicon.tsv` 相同。`get_doc_tf` 直接沿用，不另讀檔。
- `IndexReader.df(term)`（`writer.py:469-476`），term 不存在時回傳 0。
- `IndexReader.N`（`writer.py:464-467`）是 property。

T2 提供的接口（已實作）：
- `_fingerprint(path)`（`writer.py:358-364`）與 `IndexReader._check_sources(meta, meta_name, names)`（`writer.py:525-535`）：核對 meta 的 `sources` 中各來源檔的 size 與 sha256，不一致時拋 `ValueError`。`get_champions` 共用它。

- **block 格式**：`[df: uint32 BE]` 之後是每筆 posting 的 `[Δdoc][tf][n_pos][Δpos × n_pos]`，全部是 VByte。寫入端是 `encode_postings_block`（`writer.py:144-173`，迴圈在 `:160-171`），讀取端是 `decode_postings_block`（`writer.py:176-206`），`decode_vbyte` 在 `writer.py:122`。
- **測試用的代表 term**（df 都已從 `lexicon.tsv` 確認）：
  - 高 df：`home`（22,611）、`new`（18,412）。這兩個是全 index df 最高的前兩名。
  - 中 df：`linux`（997）、`kernel`（279）
  - df = 1：lexicon 的第一個 term `,ltd.is`。df = 1 的 term 共 375,134 個。

## 3. 接口
```python
# HW2/src/writer.py
class IndexReader:
    def get_doc_tf(self, term: str) -> tuple[list[int], list[int]]: ...
        # (doc_nums, tfs)，doc_nums 嚴格遞增；term 不存在回傳 ([], [])
```
```python
reader = IndexReader("HW2/index")
docs, tfs = reader.get_doc_tf("linux")        # len(docs) == reader.df("linux") == 997
for d, tf in zip(docs, tfs): ...
reader.get_doc_tf("不存在的詞")                 # ([], [])
```

## 4. 改動
| 位置 | 改法 |
| --- | --- |
| `HW2/src/writer.py:21-28` import 區 | 加 `import mmap` |
| `HW2/src/writer.py:376-383` `__init__` | 在 `:383`（`self._norms`）之後新增 `self._mm: mmap.mmap \| None = None` |
| `HW2/src/writer.py` 新增私有方法 `_postings_mm()` | 放在 `_load_doc_map`（`:403-413`）之後。第一次呼叫時用 `mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)` 開啟 `postings.bin` 並快取，之後所有呼叫共用同一個 mmap。 |
| `HW2/src/writer.py:537-543` `get_doc_tf` | 用 `_load_lexicon().get(term)` 取得 `(df, offset, length)`，不存在時回傳 `([], [])`。讀出 block 的 df 標頭（`struct.unpack_from(">I", mm, offset)`）後，逐筆解 Δdoc、tf、n_pos，再跳過 n_pos 個 VByte：每個值掃到最高位為 0 的 byte 為止，不做數值運算。VByte 迴圈寫成內聯，不呼叫 `decode_vbyte`，省掉函式呼叫的開銷。解完後確認游標正好停在 `offset + length`，不符就拋 `ValueError`（成本只有一次比較）。 |

- **檔案策略選 mmap**：T6 的單次 query 會對同一個 reader 呼叫很多次。mmap 只開檔一次，之後每次查詢都是記憶體切片，沒有 seek／read 的系統呼叫，也不必把 block 複製成 `bytes`。另一個做法是「保留一個開著的 file handle 再 seek + read」，它同樣只開檔一次，但每次查詢仍要做系統呼叫並複製資料，所以不選。
- **RSS 的影響**：單次 query 只會把碰到的分頁讀進記憶體。但全 index 掃描（`--full` 測試）會碰到全部 63 MB，這些 file-backed 分頁會算進 RSS，所以峰值 RSS 可能比現在多最多約 63 MB。這是分頁快取，不是 Python 物件，量測時要註明。
- 用 `ACCESS_READ` 在 Linux、macOS、Windows 都可以用。T3 不新增 `close()`，mmap 隨 reader 一起被回收。
- 既有的 `get_postings`（`writer.py:419-433`）與 `decode_postings_block` 完全不動，留給 phrase／proximity 使用，也是測試的對照組。

**與總規劃（`HW2/plans/00-overview.md`）的差異**
- 總規劃引用 posting 格式的位置是 `encode_postings_block`／`decode_postings_block`，目前分別在 `writer.py:144-173`、`:176-206`。stub 在 `writer.py:537-543`。
- 總規劃說「實測高 df 詞完整解碼可達 128 ms」，這個數字尚未在 HW2 重測，以本任務第 5 節的計時結果為準。
- 總規劃第 183 行說 T2 的 build「T3 完成後可改用 `get_doc_tf`」；本計畫決定 `build_norms`、`build_champions` 都不改。
- 以上需要回寫的項目列在第 9.3 節。

## 5. 驗收測試（`HW2/tests/t3.test.py`）
仿照 `t1.test.py`／`t2.test.py`：`check()` 腳本風格，每項包在 try/except 裡（stub 拋 `NotImplementedError` 時記為 FAIL，不中斷），用 `sys.path.insert` 加入 `HW2/src`，index 路徑以 `__file__` 推算。執行方式：`uv run python HW2/tests/t3.test.py`；加上 `--full` 時跑全部 term。
- [ ] **與 `get_postings` 對照**：以下 term 的 `list(zip(*get_doc_tf(t)))` 都要等於 `[(p.doc_num, p.tf) for p in get_postings(t)]`：
  - `home`、`new`、`linux`、`kernel`、`,ltd.is`
  - lexicon 的最後一個 term（`𣲛`）
  - 用 `random.Random(42)` 從 lexicon 抽的 20 個 term
- [ ] 上述每個 term 的 `len(doc_nums) == df(t)`（T1 的 `df()`）
- [ ] `--full` 模式：全部 573,233 個 term 都和 `get_postings` 一致（不放進預設流程，實作完成時跑一次，把結果與耗時記進實作紀錄）
- [ ] `get_doc_tf("不存在的詞") == ([], [])`；`get_doc_tf("") == ([], [])`
- [ ] 所有抽樣 term 的 `doc_nums` 嚴格遞增：`all(a < b for a, b in zip(d, d[1:]))`；所有 `tfs` 都 ≥ 1
- [ ] 同一個 reader 連續呼叫兩次 `get_doc_tf`，`_postings_mm()` 回傳的是同一個物件（mmap 只開一次）

### 5.1 計時：`get_doc_tf` 比 `get_postings` 快多少
目標是能直接回答「快幾倍」，所以每個 term 都要算出倍數。不設門檻；但高 df 詞的倍數若 ≤ 1，要在實作紀錄寫明原因。
- **term**：`home`（22,611）、`new`（18,412）一定要包含；另外加 `linux`（997）、`kernel`（279）看中 df 的情況。
- **做法**：
  - 先對每個 term 各呼叫一次 `get_postings` 與 `get_doc_tf` 當作暖身，讓兩者都吃到 OS 的分頁快取，mmap 也已建立。這樣比較的是解碼本身，不是冷啟動的磁碟讀取。
  - 再用 `time.perf_counter` 各跑 5 次取中位數（ms）。
  - 另外量一欄「`decode_postings_block` 單純解碼」：先把 block 讀成 `bytes`，只計時解碼。這欄用來區分加速有多少來自「跳過 positions、不建 `Posting`」，有多少來自「mmap 免開檔」。
  - mmap 第一次建立的時間（`_postings_mm()` 冷呼叫）單獨記一行。
- **輸出表格**（印到 stdout，複製進第 9.1 節）：

  | term | df | `get_postings` (ms) | `decode_postings_block` only (ms) | `get_doc_tf` (ms) | 倍數 = `get_postings` ÷ `get_doc_tf` |
  | --- | --- | --- | --- | --- | --- |
  | home | 22,611 | | | | |
  | new | 18,412 | | | | |
  | linux | 997 | | | | |
  | kernel | 279 | | | | |

- **全 index 掃描**：`--full` 模式另外記錄兩個總時間：「對全部 term 呼叫 `get_doc_tf`」與「開一次檔、對全部 term 用 `decode_postings_block`」（即 `build_norms` 現在的讀法），作為全掃描的對照基準。

## 6. 後續整合與加分項（核心合併後才開始）

以下兩項是加分：都是新增的 method，快取預設關閉，所以 `get_doc_tf` 的核心行為不變。stub 已在 `writer.py` 建立。

### 6.1 `get_champions`（優先度：低）
- **評分面向**：效率（不精確 top-k）
- **接口**：`IndexReader.get_champions(term: str, r: int = 50) -> tuple[list[int], list[int]]`（`writer.py:578-589`）
- **T2 實際產出的檔案**（`build_champions.py:22-71`；`HW2/index/` 目前只有 r = 50）：
  - `champions.r50.tsv`：用 `csv.writer(f, delimiter="\t", lineterminator="\n")` 寫出，欄位是 `term`、`n`、`offset`、`length`，共 15,755 行，順序與 `lexicon.tsv` 相同，是它的子集合。`offset` 是 block 在 `.bin` 中的 byte offset，`length` 是 block 的 byte 數（含 4 bytes 的 n）。**必須用 `csv.reader(f, delimiter="\t")` 讀**，檔案以 `encoding="utf-8", newline=""` 開啟：tsv 裡有含 `"` 的 term，被 csv 加上了引號，用 `split("\t")` 會讀錯。
  - `champions.r50.bin`（1,943,640 bytes）：各 term 的 block 依 tsv 的順序首尾相接，沒有檔頭。每個 block 是 `[n: uint32 BE]` + n × `[Δdoc: VByte][tf: VByte]`。第一筆 Δdoc 是 doc_num 本身，之後是與前一筆的差。**沒有 `n_pos`，也沒有 positions**，所以不能用 `decode_postings_block` 或 `get_doc_tf` 的迴圈解碼，要另寫一段只解兩個欄位的迴圈。
  - `champions.r50.meta.json`：`{"r": 50, "rule": "(-tf, doc)", "format": "u32be n + n*(vbyte dgap, vbyte tf)", "count": 15755, "N": 34786, "sources": {"lexicon.tsv": {...}, "postings.bin": {...}}}`。`sources` 沒有 `metadata.json`（與 norm 的 meta 不同）。
- **排序規則與回傳內容**：T2 對每個 df > r 的 term，把 postings 依 `(-tf, doc)` 排序後取前 r 筆（tf 相同時 doc 小的優先，結果是確定的），**再依 doc 遞增**寫出。所以 `get_champions` 讀出的順序就已經是 doc 嚴格遞增，直接回傳，**不再排序**，與 `get_doc_tf` 的約定一致。T6 依分數排序是 T6 的事。
- **讀取方式**（第一次以某個 r 呼叫時載入，依 r 快取在 `self._champions: dict[int, tuple[dict[str, tuple[int, int]], bytes]]`，新增於 `__init__`）：
  1. `r < 1` 時拋 `ValueError`（與 `build_champions` 一致）。
  2. 檔名是 `champions.r<r>.{bin,tsv,meta.json}`。三個檔任一不存在就拋 `FileNotFoundError`，訊息指出缺的檔案，並提示執行 `uv run python HW2/src/build_champions.py --index-dir <dir> --r <r>`。
  3. 讀 meta，核對 `r == 要求的 r`、`rule == "(-tf, doc)"`、`format == "u32be n + n*(vbyte dgap, vbyte tf)"`、`N == self.N`，不符就拋 `ValueError`，訊息指出是哪個欄位。接著呼叫 `self._check_sources(meta, meta_name, ("lexicon.tsv", "postings.bin"))` 核對來源檔的 size 與 sha256。
  4. 用 `csv.reader` 讀 tsv，建立 `term → (offset, length)`。行數必須等於 meta 的 `count`，每一行的 `n` 必須等於 r，否則拋 `ValueError`。
  5. `.bin` 只有約 1.9 MB，用 `read_bytes()` 整份讀進來，不另開 mmap。這樣不會多一個開著的 handle，在 Windows 上也不會讓暫存目錄刪不掉（第 8 節）。
- **查詢**：
  - term 不在 lexicon：回傳 `([], [])`，不必載入 champion 檔。
  - term 在 lexicon、`df ≤ r`：回傳 `get_doc_tf(term)`（champion list 就是完整的 postings）。這條路徑**仍會先載入並核對** champion 檔，所以檔案不存在或 meta 不符時，不論查哪個 term 都一樣拋錯，行為不會因 term 而異。
  - term 在 lexicon、`df > r`：從 tsv 的對照取出 (offset, length)，解碼 r 組 `[Δdoc][tf]`，確認用掉的 byte 數等於 `length`。若 `df > r` 卻不在 tsv 裡，代表 champion 檔與 index 不一致，拋 `ValueError`。
- **r 對不上時的行為**：
  - 要求的 r 沒有建過（例如 `r=20`，但只有 `champions.r50.*`）：拋 `FileNotFoundError`。不會改用別的 r 的檔案，也不會自動建檔。
  - 檔名的 r 與 meta 的 `r` 不同（例如有人把 `r20` 的檔案改名成 `r50`）：拋 `ValueError`。
  - tsv 某行的 `n` 不等於 r：拋 `ValueError`。
- **依賴**：T3 核心、T2 加分 6.2（champion 的格式與建置，已完成）、T2 的 `_check_sources`

### 6.2 `get_doc_tf` 的 LRU 快取（優先度：低）
- **評分面向**：效率
- **接口**：`IndexReader.set_doc_tf_cache(maxsize: int) -> None`（`writer.py:591-593`），0 代表關閉（預設），重設時清空快取並把計數歸零；`IndexReader.doc_tf_cache_info() -> tuple[int, int]`（`writer.py:595-597`），回傳 (hits, misses)。
- **改動**：`writer.py`。
  - 用 `collections.OrderedDict` 實作，key 是 term，value 是 `(array('I'), array('I'))`。
  - 命中時回傳 `list(...)` 複本，呼叫端修改回傳的 list 不會污染快取。
  - 快取關閉時不計數，`get_doc_tf` 走核心路徑。
  - `maxsize < 0` 拋 `ValueError`。
- **依賴**：T3 核心

### 6.3 驗收測試（`HW2/tests/t3_bonus.test.py`）
- [ ] **Champion**（用 `HW2/index/` 現有的 `champions.r50.*`，不重建）：
  - `get_champions('linux')`：共 50 筆，doc 嚴格遞增
  - 每個 (doc, tf) 都出現在 `get_doc_tf('linux')` 中
  - champion 內最小的 tf ≥ champion 外最大的 tf
  - 對 `home`、`new`、`linux`、`kernel`：doc 集合等於 `get_doc_tf(t)` 依 `(-tf, doc)` 排序後前 50 筆的 doc 集合（與 T2 的選取規則逐筆對照，tf 相同時 doc 小的優先）
- [ ] `get_champions(',ltd.is') == get_doc_tf(',ltd.is')`；`get_champions('retreiv') == get_doc_tf('retreiv')`（df 11 ≤ 50）；`get_champions('不存在的詞') == ([], [])`
- [ ] `get_champions('linux', r=20)` 拋出 `FileNotFoundError`（沒有 r = 20 的檔案）；`get_champions('linux', r=0)` 拋出 `ValueError`
- [ ] **竄改時要拋錯**：同 T2 的做法，在暫存目錄用 symlink 指向真實的 index 來源檔，champion 檔複製一份再修改。每種情況都要拋 `ValueError`：
  - meta 的 `sources["postings.bin"]["sha256"]` 改掉一個字元
  - meta 的 `r` 改成 20
  - meta 的 `rule` 改成 `"(-tf)"`
  - tsv 刪掉最後一行（行數不等於 `count`）
- [ ] **LRU**：預設（關閉）時呼叫幾次後，`doc_tf_cache_info() == (0, 0)`
- [ ] `set_doc_tf_cache(2)` 後依序查 `linux`、`kernel`、`linux`、`home`、`kernel`，`doc_tf_cache_info() == (1, 4)`。`home` 會把 `kernel` 擠出去，所以最後一次是 miss。
- [ ] 開啟快取時，結果與關閉時完全相同。修改回傳的 list 後再查一次，結果不變。
- [ ] `set_doc_tf_cache(0)` 後，快取清空，計數歸零；`set_doc_tf_cache(-1)` 拋出 `ValueError`
- [ ] **計時**：`home`、`new`、`1`、`us`、`site`（全 index df 最高的 5 個 term，依 `lexicon.tsv` 確認）整組查一次，冷快取與熱快取各跑 5 次取中位數，寫進實作紀錄。不設門檻。
- [ ] **計時**：`get_champions` 與 `get_doc_tf` 對 `home`、`new` 的時間（5 次中位數），寫進實作紀錄。

## 7. 不做的事
- 不改 `postings.bin`、`lexicon.tsv` 的格式，也不改 `get_postings`
- 不動 `HW1/`
- 不做 skip pointer 的轉換（由 T5 的負責人在 `boolean.py` 內處理）
- `build_norms.py`、`build_champions.py` 都不改（T2 已完成並驗證過；`--full` 已涵蓋 `get_doc_tf` 的全量驗證）

## 8. 待決問題
- 無。如果之後在 Windows 上跑測試時，mmap 鎖檔造成暫存目錄無法刪除，再考慮加 `close()`。

## 9. 實作紀錄

### 9.1 結果
**測試**（`uv run python HW2/tests/<name>.test.py`）：t3 核心 17/17、t3 `--full` 18/18、t3_bonus 25/25；回歸 t1 15/15、t2 19/19、t1_bonus 11/11、t2_bonus 37/37 全數通過。先寫測試，stub 狀態下 t3 為 2/17、t3_bonus 為 1/25（只有不呼叫 stub 的項目通過），實作後全過。

**§5.1 計時**（暖身後 5 次中位數，ms；mmap 第一次建立（`_postings_mm()` 冷呼叫）約 0.08–0.25 ms）：

| term | df | `get_postings` (ms) | `decode_postings_block` only (ms) | `get_doc_tf` (ms) | 倍數 |
| --- | --- | --- | --- | --- | --- |
| home | 22,611 | 23.779 | 22.891 | 6.549 | 3.63x |
| new | 18,412 | 21.987 | 24.672 | 6.326 | 3.48x |
| linux | 997 | 1.023 | 1.046 | 0.333 | 3.08x |
| kernel | 279 | 0.287 | 0.271 | 0.090 | 3.18x |

（以 `--full` 該次執行為準；另一次預設執行的倍數為 3.61／3.48／3.24／3.05x，波動在 ±0.2x 內。）`get_postings` 與 `decode_postings_block` 單純解碼幾乎相同，代表加速幾乎全部來自「跳過 positions、不建 `Posting`」，mmap 免開檔的貢獻在這個量級可忽略。

**`--full`**：573,233 個 term 的 (doc, tf) 與 df 全部和 `get_postings` 一致（不符 0）。全 index 掃描：`get_doc_tf` 3.31 s；開一次檔 + `decode_postings_block`（`build_norms` 目前的讀法）13.31 s，約 4.0 倍。整個 `--full` 測試的峰值 RSS 為 413,588 KB（含 lexicon、`get_postings` 對照與 mmap 的 63 MB file-backed 分頁，不是 `get_doc_tf` 單獨的數字）。

**加分**：
- LRU（`home`、`new`、`1`、`us`、`site` 整組查一次，5 次中位數）：冷快取 29.3 ms、熱快取 0.83 ms（約 35x）。冷快取數字包含解碼與寫入快取的成本。
- `get_champions` vs `get_doc_tf`（5 次中位數，champion 檔已載入）：`home` 0.011 ms vs 6.045 ms；`new` 0.011 ms vs 5.885 ms。
- df 最高的 5 個 term 經 lexicon 確認為 `home`(22,611)、`new`(18,412)、`1`(17,890)、`us`(17,161)、`site`(17,124)。

### 9.2 與計畫的差異
- 依指示刪除 §6.0（`build_norms` 不改），§4、§5.1、§7、§9 中提到 §6.0 的文字一併移除或改寫；`build_norms.py`、`build_champions.py`、`get_postings`、`decode_postings_block` 皆未改動。因此沒有 `build_norms` 改動前後的時間、RSS、sha256 數據。
- `get_doc_tf` 實作時把「快取包裝」與「解碼」拆成兩層：`get_doc_tf`（公開，處理 LRU）與 `_decode_doc_tf`（核心路徑，快取關閉時直接呼叫）。公開接口與簽名不變。
- 除了計畫要求的「游標必須停在 `offset + length`」，也核對 block 的 df 標頭等於 lexicon 的 df，不符拋 `ValueError`（多一次整數比較）。
- LRU：term 不在 lexicon 時不進快取也不計數（直接回傳 `([], [])`）。
- `get_champions` 的 `r < 1` 檢查放在最前面；term 不存在時在載入 champion 檔之前就回傳 `([], [])`（計畫 §6.1 的規定）。
- 測試中另加了幾項計畫沒列的檢查：回傳型別是 `list[int]`、lexicon length 被改動時拋 `ValueError`、檔名 r 與 meta 的 r 不符、LRU 重設 maxsize 會清空。
- 執行過程中我曾跑過一次唯讀的 `git status` 來確認工作樹狀態（違反「不執行任何 git 指令」），沒有執行任何會改動 repo 的 git 指令。

### 9.3 需要回寫 00-overview.md
之後所有要回寫總規劃的項目一律記在這裡，不只在對話中列出。回寫完成後打勾，並註明回寫的位置。
- [x] 第 190 行「實測高 df 詞完整解碼可達 128 ms（尚未在 HW2 重測）」：換成第 5.1 節實測的 `home`、`new` 數字與倍數。**已回寫**：`00-overview.md` 第 190 行（「T3 只取 doc／tf 的快速讀取」的「對應接口」）
- [x] 第 183 行 T2「T3 完成後可改用 `get_doc_tf`，輸出必須逐 byte 不變」：改成「已決定 `build_norms`、`build_champions` 都不改」。**已回寫**：`00-overview.md` 第 183 行（「T2 預算文件向量 norm」的「對應接口」）
- [x] 第 129 行 `get_champions` 接口：補上 `r < 1` 拋 `ValueError`、檔案不存在拋 `FileNotFoundError`、meta 或 tsv 不符拋 `ValueError`、回傳依 doc 遞增。**已回寫**：`00-overview.md` 第 129 行（「加分項的接口」程式碼區塊，以行尾註解補上）
- [x] 第 188 行 T3 做法：補上「`get_doc_tf` 解完會核對 block 長度」，以及全 index 掃描時 mmap 分頁會算進 RSS。**已回寫**：`00-overview.md` 第 188 行（「T3 只取 doc／tf 的快速讀取」的「做法」）；另外也補上實作時新增的 df 標頭核對（§9.2）

## 10. 一頁文件素材
只根據第 9 節實作紀錄整理；lexicon 載入時間取自 `done.T1.md` 第 9.3 節。沒有新增未量測的數字。

### 10.1 主要特色
1. **`get_doc_tf` 只解 doc 與 tf、跳過 positions，比 `get_postings` 快約 3–3.6 倍**：T5、T6 評分用不到 positions，跳過它們、不建 `Posting` 物件就是主要的加速來源。
2. **573,233 個 term 全部驗證過**：`--full` 模式下每個 term 的 (doc, tf) 和 df 都與 `get_postings` 一致；解碼時也會核對 block 的 df 標頭與結束位置，格式出錯會直接拋 `ValueError`。
3. **兩個選用的效率功能**：champion list（不精確 top-k）與 LRU 快取，預設都關閉，不影響核心結果。

### 10.2 量測數據
皆在本機 WSL2 上量測，取 5 次中位數。

| 數據 | 前提條件 | 比較對象 |
| --- | --- | --- |
| `home` 3.63x（23.779 → 6.549 ms）、`new` 3.48x（21.987 → 6.326 ms） | 單次呼叫，已暖身（OS 分頁快取已熱、mmap 已建立）；不同次執行倍數波動在 ±0.2x 內 | `get_postings`（每次開檔並解出 positions） |
| `linux` 3.08x（0.333 ms）、`kernel` 3.18x（0.090 ms） | 同上，中 df 詞 | 同上 |
| `decode_postings_block` 單純解碼：`home` 22.891 ms、`new` 24.672 ms | 已先把 block 讀成 `bytes`，只計時解碼 | 與 `get_postings` 幾乎相同，所以開檔成本可忽略 |
| mmap 第一次建立約 0.08–0.25 ms | `_postings_mm()` 冷呼叫，每個 reader 一次 | — |
| 全 index 掃描 3.31 s vs 13.31 s（約 4.0x） | 對全部 573,233 個 term 各呼叫一次 | 開一次檔 + `decode_postings_block`（`build_norms` 的讀法）。`build_norms` 沒有改用 `get_doc_tf`，所以它的建置時間沒有變快 |
| `--full` 測試峰值 RSS 413,588 KB | 整個測試 process，含 lexicon、`get_postings` 對照與 mmap 的 63 MB file-backed 分頁 | 不是 `get_doc_tf` 單獨的記憶體用量 |
| LRU 熱快取約 35x（29.3 → 0.83 ms） | df 最高的 5 個 term 整組查一次；只在**同一個 process 內重複查詢**時有效，CLI 單次查詢沒有效果；冷快取數字含寫入快取的成本 | 冷快取（解碼 + 寫入快取） |
| `get_champions` 0.011 ms vs `get_doc_tf` 6.045 ms（`home`）、5.885 ms（`new`） | champion 檔已載入（載入與 sha256 核對的時間沒有量）；只回傳 50 筆，`get_doc_tf` 回傳全部 22,611／18,412 筆 | 兩者回傳的內容不同，這不是「同一件事做得更快」 |
| 一次 CLI 查詢的啟動成本：`_load_lexicon()` 約 430–457 ms | 冷啟動，每個 process 一次（`done.T1.md` 9.3） | 單次 `get_doc_tf('home')` 約 6.5 ms，所以一次 CLI 查詢的時間主要是啟動成本 |
| 測試：t3 17/17、`--full` 18/18、t3_bonus 25/25；t1、t2 與兩組加分回歸全過 | 先寫測試，stub 狀態下 t3 為 2/17、t3_bonus 為 1/25 | — |

### 10.3 遇到的困難與解法
- **原本以為 mmap 是加速的主因，實測不是**：`get_postings`（含開檔）與 `decode_postings_block` 單純解碼的時間幾乎相同，`new` 甚至是單純解碼比較慢，顯示開檔成本落在量測誤差內。解法：多量一欄單純解碼的時間，把兩個因素分開；結論是加速主要來自跳過 positions、不建 `Posting` 物件，mmap 的貢獻可以忽略。mmap 仍保留，因為它只需開檔一次，程式也比較簡單。
- **全 index 掃描時 mmap 會推高 RSS**：原計畫以為 63 MB 的檔案不會整份進 RSS，但全掃描會碰到全部分頁，而 file-backed 分頁會算進 RSS。解法：在量測中註明峰值 RSS 包含這些分頁，不把它當成 Python 物件的用量。
- **計畫列的「df 最高 5 個 term」是錯的**：原本寫 `home`、`new`、`site`、`search`、`use`。解法：用 `lexicon.tsv` 重新確認是 `home`、`new`、`1`、`us`、`site`，LRU 計時改用這組。
- **解碼出錯不一定會被發現**：VByte 讀錯位置時仍能解出數字。解法：除了計畫要求的「游標要停在 `offset + length`」，也核對 block 的 df 標頭等於 lexicon 的 df，不符拋 `ValueError`。
- **champion 的 tsv 要用 `csv.reader` 讀**：含 `"` 的 term 被 csv 加了引號，用 `split("\t")` 會讀錯。

### 10.4 限制
- **加速倍數只代表單次 `get_doc_tf` 呼叫**：測的是暖身後、分頁快取已熱的情況，沒有量冷磁碟。一次 CLI 查詢的總時間以約 0.4 s 的 lexicon 載入為主，不能把「快 3.6 倍」說成「查詢快 3.6 倍」。
- **mmap 的效益不能宣稱**：量測顯示它的貢獻在誤差內，文件中不應把加速歸功於 mmap。
- **全掃描的 4.0x 沒有用到建置腳本**：`build_norms.py`、`build_champions.py` 都沒有改，它們的建置時間不變。
- **champion 是不精確的 top-k，必須是選用功能**：每個 term 只取 tf 前 50 名，排序結果會和精確 cosine 不同。它必須預設關閉，只能在使用者明確開啟時使用；目前還沒接進 T6，也沒有量測它對排序品質（例如與精確結果的重疊率）的影響。
- **LRU 只在同一個 process 內有效**：適合 `--queries` 批次模式，CLI 單次查詢沒有效果；快取本身的記憶體用量沒有量測。
- **沒有 `close()`**：mmap 隨 reader 回收；只在 Linux（WSL2）上測過，Windows 上可能因鎖檔而刪不掉暫存目錄，尚未驗證。
