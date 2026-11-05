# T2 預算文件 norm（含 W：`weight()`）

> 狀態：T1 已完成（見 `done.T1.md`），本計畫已依其實作紀錄更新行號與接口；可以開始實作。

## 1. 目標
實作共用權重函式 `weight()`，並一次掃過整個 index，預先算出每篇文件的 |d|，存檔後供 T6 的 cosine 分母直接載入。

## 2. Index 來源（`HW2/index/`）
使用 T1 的 stop+stem index：N = 34,786，doc_num 從 0 到 34785 連續，共 573,233 個 term。唯一的空文件是 doc 24621（`doc_len = 0`）。T2 會新增兩個檔案，其餘檔案不動。

| 檔案 | 用途 | T2 讀／寫 |
| --- | --- | --- |
| `lexicon.tsv`、`postings.bin` | 依 term 逐一取出 (doc, tf) | 讀 |
| `metadata.json` | N | 讀 |
| `postings.txt` | 只給測試的獨立路徑使用 | 測試讀 |
| `doc_norms.bin` | `array('d')`，長度 N，下標 = doc_num（約 278 KB） | **新增** |
| `doc_norms.meta.json` | 記錄公式與來源 index 的指紋 | **新增** |

T1 提供的接口（已實作）：
- `IndexReader._load_lexicon()`（`writer.py:374`）回傳 `dict[str, tuple[int, int, int]]`，即 `term → (df, offset, length)`，順序與 `lexicon.tsv` 相同。
- `IndexReader.N`（`writer.py:449-452`）是 **property**，寫 `reader.N`，不是 `reader.N()`。
- `IndexReader.df(term)`（`writer.py:454-461`），term 不存在時回傳 0。

## 3. 接口
```python
# HW2/src/weighting.py（由 T2 負責；rank.py 屬於 T6）
LOG_BASE = 10
DEFAULT_SCHEME = "ltc"
FORMULA = "(1+log10 tf)*log10(N/df)"
def weight(tf: int, df: int, N: int, scheme: str = "ltc") -> float: ...
    # 只算 tf × idf，不含 normalization；scheme 是「單邊」三個字母
    # (1 + log10 tf) * log10(N / df)；tf == 0 或 df == 0 回傳 0.0；核心只需支援 "ltc"
def norm_filenames(scheme: str = "ltc") -> tuple[str, str]: ...   # ("doc_norms.bin", "doc_norms.meta.json")

# HW2/src/writer.py
class IndexReader:
    def get_norms(self, scheme: str = "ltc") -> array: ...   # array('d')，下標 = doc_num

# HW2/src/build_norms.py
def build_norms(index_dir: str | Path, scheme: str = "ltc") -> None: ...
```
```bash
uv run python HW2/src/build_norms.py --index-dir HW2/index   # 建一次即可
```
```python
reader = IndexReader("HW2/index")
norms = reader.get_norms()                    # meta 與 index 不一致時拋出 ValueError
norms[24621], len(norms)                      # (0.0, 34786)
```

## 4. 改動
| 位置 | 改法 |
| --- | --- |
| `HW2/src/weighting.py:12-24` `weight` | 先檢查 scheme，再處理 tf／df 的邊界（所以 `weight(0, 997, N, "xyz")` 也會拋錯）。核心：scheme 不是 `"ltc"` 時拋出 `ValueError`（其他 scheme 屬於加分項）。`if tf <= 0 or df <= 0: return 0.0`，否則 `return (1 + math.log10(tf)) * math.log10(N / df)`。只能用 `math.log10`。 |
| `HW2/src/weighting.py:27-33` `norm_filenames` | `"ltc"` 回傳 `("doc_norms.bin", "doc_norms.meta.json")`。`build_norms` 與 `get_norms` 都經由它取得檔名。 |
| `HW2/src/build_norms.py:12-18` `build_norms` | `reader = IndexReader(index_dir)`，`N = reader.N`，`norm2 = array('d', bytes(8 * N))`。`for term, (df, offset, length) in reader._load_lexicon().items():`，`postings.bin` 只開一次，依 offset／length 讀出 block，用 `decode_postings_block`（`writer.py:174`）解碼，再累加 `norm2[p.doc_num] += weight(p.tf, df, N, scheme) ** 2`。最後開根號，寫出 `doc_norms.bin`（`array.tofile`）與 meta。結束時印出建置時間（`time.perf_counter`）與峰值記憶體（`resource.getrusage(...).ru_maxrss`，同 HW1 `indexer.test.py:66`）。另外補上 `argparse` 的 `--index-dir`、`--scheme` 與 `if __name__ == "__main__":`。 |
| `doc_norms.meta.json` 欄位 | 見下方 JSON 範例 |
| `HW2/src/writer.py:463-476` `get_norms` | 第一次呼叫時讀 meta 並核對：`log_base`、`formula`、`scheme` 要等於 `weighting` 的常數與要求的 scheme；`N` 要等於 `self.N`；`sources` 裡三個來源檔的 size 與 sha256 都要相符；norm 檔大小要等於 `8 × N`。任何一項不符就拋出 `ValueError`，訊息指出是哪一項。檔案不存在時拋出 `FileNotFoundError`，提示先跑 `build_norms.py`。結果依 scheme 快取（新增 `self._norms: dict[str, array]`，放在 `__init__`）。 |

meta 格式（`sources` 的結構與 champion 的 meta 相同，T3 的 `get_champions` 可以共用同一段核對程式）：
```json
{
  "log_base": 10,
  "formula": "(1+log10 tf)*log10(N/df)",
  "scheme": "ltc",
  "N": 34786,
  "count": 34786,
  "sources": {
    "lexicon.tsv":   {"size": 13709652, "sha256": "..."},
    "postings.bin":  {"size": 62973150, "sha256": "..."},
    "metadata.json": {"size": 280,      "sha256": "..."}
  }
}
```

- 核對用 sha256 而不是只比大小。實測三個檔案共約 0.08 秒，每個 process 只做一次。建議在 `writer.py` 寫一個私有 helper（例如 `_check_sources(meta, names)`），讓 `get_norms` 與 T3 的 `get_champions` 共用。
- 公式常數（`LOG_BASE`、`FORMULA`、`DEFAULT_SCHEME`）只在 `weighting.py` 定義，`build_norms.py` 寫入、`get_norms` 核對，兩邊都引用這一份。
- 不用 `get_postings`（`writer.py:404`），因為它每次呼叫都要重新開檔，57 萬次太慢。T3 完成後，`build_norms.py` 可以把解碼換成 `get_doc_tf`，結果必須逐 byte 不變。

**與總規劃（`HW2/plans/00-overview.md`）的差異**
- W 改由 T2 負責，放在 `weighting.py`（避免與 T6 同時修改 `rank.py`）。（已回寫）
- `get_norms()` 在載入時核對 meta，不一致時拋出 `ValueError`。（已回寫）
- 總規劃說「那篇空文件」，實際是 doc 24621。
- 總規劃第 162 行的公式沒有寫 scheme；`build_norms` 實際會把 scheme 傳給 `weight`（核心固定是 ltc，結果相同）。

## 5. 驗收測試（`HW2/tests/t2.test.py`）
仿照 `t1.test.py`：`check()` 腳本風格，每項包在 try/except 裡（stub 拋 `NotImplementedError` 時記為 FAIL，不中斷），用 `sys.path.insert` 加入 `HW2/src`，index 路徑以 `__file__` 推算。執行方式：`uv run python HW2/tests/t2.test.py`。測試前要先跑過 `build_norms.py`。
- [ ] `weight()` 手算值（N = 34786，誤差 < 1e-12）：
  - `weight(1, 997, N) == log10(34786/997)`，約 1.5427093343
  - `weight(10, 997, N)`，約 3.0854186686（是上一項的 2 倍）
  - `weight(0, 997, N) == 0.0`
  - `weight(1, 0, N) == 0.0`
  - `weight(1, N, N) == 0.0`
- [ ] **獨立路徑對照**：用 `random.Random(42).sample(range(N), 20)` 抽 20 篇文件。
  - 測試檔自己寫一個 `postings.txt` 的解析器：以第一個 `", "` 切出 term，再取出 df 與各 posting 的 (doc, tf)。不 import `writer.parse_postings_line`、不讀 `postings.bin`、不用 `IndexReader`，權重公式也在測試內直接用 `math.log10` 寫一次。
  - 掃一遍 `postings.txt`，只累加這 20 篇文件的 norm²。開根號後與 `get_norms()[doc]` 比較，誤差 < 1e-9。
- [ ] `get_norms()[24621] == 0.0`；其餘 34,785 篇文件的 norm 都 > 0；`len(get_norms()) == 34786`
- [ ] **竄改 meta 時要拋錯**：在暫存目錄用 symlink 指向真實 index 檔，再寫入修改過的 meta。每種情況都要拋出 `ValueError`：
  - `log_base` 改成 `"e"`
  - `N` 改成 34785
  - `sources["postings.bin"]["sha256"]` 改掉一個字元
  - `doc_norms.bin` 截掉 8 bytes
- [ ] 刪掉 `doc_norms.bin` 時拋出 `FileNotFoundError`
- [ ] `build_norms.py` 印出的建置時間與峰值記憶體寫進實作紀錄。總規劃的參考值是約 16.6 秒、283 MB，不設門檻。

## 6. 加分項（核心合併後才開始）
所有新參數都有預設值，預設值的行為與核心完全相同。

### 6.1 SMART 權重方案（優先度：高）
- **評分面向**：權重方案
- **定義**：
  - `weight`、`get_norms`、`build_norms`、`norm_filenames` 的 `scheme` 都是**單邊**的三個字母：tf、idf、normalization。傳入 `"lnc.ltc"` 這種含 `.` 的字串會拋 `ValueError`。
  - 文件端與 query 端分別指定，寫成 `ddd.qqq`：`lnc.ltc` 代表文件用 lnc、query 用 ltc。拆開 `ddd.qqq` 是 T6 `rank` 的工作（見下方「T6 怎麼用」）。
  - `weight()` 只算 tf × idf，**不看第三個字母**（但會檢查它是 `n` 或 `c`）。normalization 由文件端的 `get_norms` 與 query 端的 |q| 處理。

  | 位置 | 字母 | 意義 | `formula` 片段 |
  | --- | --- | --- | --- |
  | tf | `n` | tf 原值 | `tf` |
  | tf | `l` | 1 + log10 tf | `(1+log10 tf)` |
  | tf | `b` | 1（tf > 0 時） | `1` |
  | idf | `n` | 1（不用 idf） | `1` |
  | idf | `t` | log10(N / df) | `log10(N/df)` |
  | normalization | `n` | 不正規化，\|d\| 視為 1 | — |
  | normalization | `c` | cosine：除以 sqrt(Σw²) | — |

  不論哪個 scheme，tf ≤ 0 或 df ≤ 0 都回傳 0.0（df = 0 代表 term 不在 index 中）。三個位置各自寫成小函式，所以 2 × 3 × 2 = 12 種組合都能用；測試至少涵蓋 ltc、lnc、ntc、bnn。
- **normalization 是 `n` 時（決定）**：
  - `get_norms("xxn")` 回傳長度 N、全部為 1.0 的 `array('d')`，**不讀檔、不需要 build**（|d| 依定義是 1，與 index 內容無關，只需 N）。這樣 T6 不必為 `n` 寫特例，分母一律是 `norms[doc]`。注意 doc 24621 在這裡是 1.0，不是 0.0；它沒有任何 term，不會出現在累加器裡，所以沒影響。
  - `build_norms(index_dir, "xxn")` 拋出 `ValueError`（沒有東西要建），不寫任何檔案。
  - `norm_filenames("xxn")` 也拋出 `ValueError`，避免有人去找不存在的檔案。
  - 不選「`get_norms` 拋錯」的理由：那樣 T6 就要自己判斷第三個字母，還要另外處理 doc 的分母，等於把 normalization 的邏輯分散到兩個地方。
- **接口**：`weight(tf, df, N, scheme="ltc")`（`weighting.py:12`）、`norm_filenames(scheme)`（`weighting.py:27`）、`get_norms(scheme="ltc")`（`writer.py:463`）、`build_norms(index_dir, scheme="ltc")`（`build_norms.py:12`）。CLI 是 `--scheme X`（單邊）。新增一個函式：
  ```python
  # HW2/src/weighting.py（加分新增）
  def formula(scheme: str = "ltc") -> str: ...   # tf 片段 + "*" + idf 片段；formula("ltc") == FORMULA
  ```
  例如 `formula("lnc") == "(1+log10 tf)*1"`、`formula("bnn") == "1*1"`。
- **改動**：
  - `weighting.py`：依字母分派，scheme 不合法（長度不是 3、字母不在表中）時拋出 `ValueError`。`formula()` 由同一張字母表產生。
  - `norm_filenames`：`"ltc"` 不變；其他 normalization 為 `c` 的 scheme 回傳 `doc_norms.<scheme>.bin`、`doc_norms.<scheme>.meta.json`；`n` 拋錯（見上）。
  - `build_norms.py`：normalization 是 `c` 時照核心流程掃描，並把 scheme 傳給 `weight`；meta 的 `scheme` 填該 scheme、`formula` 填 `formula(scheme)`。
  - `get_norms`：`n` 直接回傳全 1；`c` 時核對 meta，`formula` 改成比對 `formula(scheme)`（ltc 時等於 `FORMULA`，核心行為不變）。
  - 預設檔名與 ltc 的行為與核心完全相同。
- **T6 怎麼用**（寫給 T6；T6 的接口以 `00-overview.md` 為準）：
  - `rank(qtf, candidates, reader, scheme="ltc.ltc")`。`scheme` 是完整的 `ddd.qqq`，`rank` 用 `doc_s, q_s = scheme.split(".")` 拆開；格式錯誤時拋出 `ValueError`。
  - 文件端權重：`weight(tf, reader.df(t), reader.N, doc_s)`；文件端分母：`reader.get_norms(doc_s)[doc]`。
  - query 端權重：`w_tq = weight(qtf[t], reader.df(t), reader.N, q_s)`。`q_s[2] == "c"` 時除以 |q| = sqrt(Σ_t w_tq²)，`"n"` 時不除。|q| 由 T6 自己算，`weighting` 不提供。
  - 分數：`score(d) = Σ_t weight(tf_td, df_t, N, doc_s) × w_tq / (norms[d] × qnorm)`；`norms[d] == 0` 的文件（只有 c 方案下的 doc 24621）跳過。|q| = 0（例如所有 query term 的 df 都是 0 或 N）時，所有分數都是 0，輸出方式由 T6／T7 決定。
  - 預設 `ltc.ltc` 必須與核心結果完全相同：核心等同 `weight(tf, df, N)` + `get_norms()` + 除以 |q|。
  - champion list：T6 另加一個可關閉的參數（建議 `champion_r: int | None = None`），不是 `None` 時用 `reader.get_champions(t, champion_r)` 取代 `reader.get_doc_tf(t)`。分母仍用完整的 `get_norms(doc_s)`，不另算 champion 版的 norm。
- **依賴**：T2 核心
- **驗收測試**：見 6.3。

### 6.2 Champion list（優先度：低）
- **評分面向**：效率（不精確 top-k）
- **接口**：`build_champions(index_dir, r=50)`（`build_champions.py:14`）。CLI 是 `uv run python HW2/src/build_champions.py --index-dir HW2/index [--r 50]`。r ≥ 1，否則拋 `ValueError`。
- **選取規則**：只收 df > r 的 term。每個 term 把 postings 依 `(-tf, doc)` 排序取前 r 筆（tf 相同時 doc 小的優先，結果是確定的），再依 doc 遞增排序後寫出。所以收錄的 term 一定剛好 r 筆。df ≤ r 的 term 不寫入，champion list 就是完整的 postings，由 `get_champions` 直接回傳 `get_doc_tf` 的結果。r = 50 時只需收 15,755 個 term，其餘 557,478 個（97.3%）都不必寫入。
- **檔案格式**（檔名帶 r，所以不同的 r 可以並存；T3 的 `get_champions` 依此讀取）：
  - `champions.r<r>.bin`：各 term 的 block 依 tsv 的順序首尾相接，沒有檔頭。每個 block：
    - `n`：4 bytes，big-endian uint32（`struct.pack(">I", n)`），等於 r
    - 接著 n 組 `[Δdoc][tf]`，兩者都用 `writer.encode_vbyte`（LEB128 變體：低位在前，非最後一個 byte 設最高位），與 `postings.bin` 相同
    - Δdoc：第一筆是 doc_num 本身（相對於 0），之後是與前一筆的差（> 0）
    - **沒有** `n_pos` 欄位，也沒有 positions。所以**不能**用 `decode_postings_block` 解碼，要另寫解碼（或在 T3 共用 `get_doc_tf` 的迴圈但不跳 positions）。
  - `champions.r<r>.tsv`：與 `lexicon.tsv` 完全相同的寫法——`csv.writer(f, delimiter="\t", lineterminator="\n")`，檔案用 `encoding="utf-8", newline=""` 開啟。讀取時必須用 `csv.reader(f, delimiter="\t")`，不能用 `line.split("\t")`：lexicon 裡有 634 個 term 含 `"`，會被 csv 加上引號（例如 `"absw""at""absw.or.uk"`）。
    - 欄位：`term`、`n`（= r）、`offset`（block 在 `.bin` 中的 byte offset）、`length`（block 的 byte 數，含 4 bytes 的 n）
    - 順序與 `lexicon.tsv` 相同（Python 字串順序），只是子集合
  - `champions.r<r>.meta.json`：
    ```json
    {
      "r": 50,
      "rule": "(-tf, doc)",
      "format": "u32be n + n*(vbyte dgap, vbyte tf)",
      "count": 15755,
      "N": 34786,
      "sources": {
        "lexicon.tsv":  {"size": 13709652, "sha256": "..."},
        "postings.bin": {"size": 62973150, "sha256": "..."}
      }
    }
    ```
    `count` 是 tsv 的行數。`get_champions` 至少要核對 `r` 等於要求的 r、`rule`、`format`，以及 `sources` 的 size 與 sha256（與 `get_norms` 共用 `_check_sources`）。
- **改動**：`build_champions.py`。讀取方式與 `build_norms` 相同（`_load_lexicon()` + 開一次 `postings.bin` + `decode_postings_block`），先用 lexicon 的 df 跳過 df ≤ r 的 term，不必解碼。結束時印出建置時間、峰值記憶體與檔案大小。補上 `argparse` 與 `if __name__ == "__main__":`。
- **依賴**：T1 核心。不依賴 T3（T3 未完成時也能建；T3 完成後可以把解碼換成 `get_doc_tf`，輸出必須逐 byte 不變）。T3 加分的 `get_champions` 讀取這些檔案。

### 6.3 驗收測試（`HW2/tests/t2_bonus.test.py`）
- [ ] **SMART 手算值**（N = 34786，df = 997，tf = 10，誤差 < 1e-12）：
  - `ltc` → 3.0854186686
  - `lnc` → 2.0
  - `ntc` → 15.427093343
  - `bnn` → 1.0
  - `weight(0, 997, N, "bnn") == 0.0`
- [ ] 核心的 5 組手算值都滿足 `weight(tf, df, N, "ltc") == weight(tf, df, N)`
- [ ] `weight(1, 997, N, s)` 對 `"xyz"`、`"lt"`、`"ltx"`、`"lnc.ltc"` 都拋出 `ValueError`；`weight(0, 997, N, "xyz")` 也拋出 `ValueError`
- [ ] `formula("ltc") == FORMULA`；`formula("lnc") == "(1+log10 tf)*1"`
- [ ] 不加參數與 `--scheme ltc` 建出的 `doc_norms.bin` sha256 相同，而且都等於核心建出的檔案
- [ ] `get_norms("lnc")`：沿用核心的 `postings.txt` 獨立解析器與同一組 20 篇文件，改算 sqrt(Σ(1 + log10 tf)²)，誤差 < 1e-9；doc 24621 的值為 0.0
- [ ] `get_norms("bnn")`、`get_norms("ltn")`：長度 34786、全部都是 1.0，而且 index 目錄中沒有 `doc_norms.bnn.*` 檔案；`build_norms(index_dir, "bnn")` 拋出 `ValueError`
- [ ] 把 `doc_norms.lnc.meta.json` 的 `scheme` 改成 `"ltc"` 後，`get_norms("lnc")` 拋出 `ValueError`；還沒建 `ntc` 時，`get_norms("ntc")` 拋出 `FileNotFoundError`
- [ ] **Champion**：`r = 50` 建置後，測試檔自己解析 `champions.r50.tsv`（用 `csv.reader`）與 `champions.r50.bin`（自己寫 `struct` + VByte 解碼，不經過 `IndexReader`、不 import `writer` 的解碼函式）。對 `home`、`new`、`linux`、`kernel`：
  - 筆數都是 50，tsv 的 `n` 也是 50，`length` 等於實際解碼用掉的 byte 數
  - doc 集合等於 `get_postings(t)` 依 `(-tf, doc)` 排序後前 50 筆的 doc 集合
  - doc 嚴格遞增，tf 與 postings 相同
- [ ] `champions.r50.tsv` 的行數等於 `lexicon.tsv` 中 df > 50 的 term 數（目前是 15,755，`awk -F'\t' '$2>50' lexicon.tsv | wc -l` 與 csv 解析結果一致）；meta 的 `count` 也是 15,755；`retreiv`（df 11）與 `,ltd.is`（df 1）不在檔案內
- [ ] 記錄 champion 的建置時間、峰值記憶體與檔案大小

## 7. 不做的事
- 不改 `postings.bin`、`lexicon.tsv` 的格式，也不重建 index
- 不動 `HW1/`
- 不做 T3 的快速讀取與 `get_champions`，也不改 T6 的 `rank()`（T6、T7 需要配合的地方見 `00-overview.md` 對應的小節與本文件 6.1「T6 怎麼用」）
- 不拿 `doc_len` 當 norm

## 8. 待決問題
- **需組內決定**：`doc_norms*.bin`、`champions.*` 與 meta 要不要放進繳交的 zip。若不放，README 要寫清楚重建指令與所需時間。（與總規劃「zip 是否附 index」一併決定）
- **已決定**：normalization 是 `n` 時，`get_norms` 回傳全部為 1.0，不讀檔；`build_norms` 與 `norm_filenames` 遇到 `n` 拋 `ValueError`（理由見 6.1）。

## 9. 實作紀錄
### 核心
- `uv run python HW2/tests/t2.test.py`：19/19 通過（先在 stub 狀態下確認 0/19，再實作；加分完成後重跑仍 19/19）。
- `build_norms.py`（ltc）：**15.27 s**，峰值 RSS **221.0 MB**（`ru_maxrss`）；`doc_norms.bin` 278,288 bytes（8 × 34,786）。總規劃參考值 16.6 s／283 MB。
- 20 篇對照最大誤差：**0.0**（與 `postings.txt` 獨立路徑逐位相同）。
- `doc_norms.bin` sha256：`fbea829859d5087d9c06cb54a5fe38deaa97f8608bb62f0213ad50fbbcec0b6a`；加分實作後用預設 API 與 `--scheme ltc` 重建，三者相同。

### 加分
- `uv run python HW2/tests/t2_bonus.test.py`：37/37 通過。
- SMART：lnc 在暫存目錄建置 16.56 s／235.1 MB（`doc_norms.lnc.bin` 278,288 bytes）；ltc 重建 17.07 s／222.0 MB。lnc 20 篇對照最大誤差 0.0。
- Champion（r = 50）：`build_champions.py` **15.17 s**，峰值 RSS **222.2 MB**；`champions.r50.bin` 1,943,640 bytes、`.tsv` 333,990 bytes、`.meta.json` 410 bytes；15,755 個 term，與 `awk '$2>50'` 一致。

### 偏離計畫之處
- **接口簽名沒有改動。** 以下是計畫未明寫的實作細節：
- `writer.py` 新增模組層級的 `_fingerprint(path)`、`_NORM_SOURCES` 與方法 `IndexReader._check_sources(meta, meta_name, names)`；`build_norms.py` 從 `writer` import 這兩個私有名稱。計畫只建議寫 `_check_sources`，`_fingerprint` 是為了讓 build 與核對共用同一份 size／sha256 計算。T3 的 `get_champions` 可直接呼叫 `_check_sources(meta, name, ("lexicon.tsv", "postings.bin"))`。
- `writer.py` 現在 `from weighting import LOG_BASE, formula, norm_filenames`（`weighting` 不 import `writer`，無循環）。
- `get_norms` 除計畫列的欄位外，也核對 meta 的 `count == N`。
- `get_norms` 缺檔時，bin 或 meta 任一不存在都拋 `FileNotFoundError`。
- 核心先以 `scheme != "ltc"` 拋錯實作；加分階段改成字母表分派，因此 scheme 不合法時的訊息由 `unsupported scheme` 變成 `invalid scheme`（行為仍是 `ValueError`）。
- 加分的 `weight()` 在 tf 字母為 `n` 時回傳 `float(tf)`；`_parse` 對空字串、非 3 字元、含 `.` 的字串都拋 `ValueError`。
- `t2_bonus.test.py` 的 lnc／ltc 建置都在暫存目錄（symlink 來源檔）進行，所以 `HW2/index/` 裡**沒有** `doc_norms.lnc.*`；index 中新增的檔案只有 `doc_norms.bin`、`doc_norms.meta.json`、`champions.r50.{bin,tsv,meta.json}`。
- 加分測試是先寫測試、再實作；沒有另外跑一次「stub 狀態全部失敗」。
- `build_champions` 的「T3 完成後改用 `get_doc_tf`」尚未做（T3 不在範圍）。
- 沒有執行任何 git 指令。
