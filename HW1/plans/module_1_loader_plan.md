# Module 1：Loader & Preprocessor — 實作計畫
> **狀態：✅ 已完成**（`warc.py`, `extract.py`, `documents.py`）  
> **關聯**：[`inverted_index_plan.md`](inverted_index_plan.md)

---

## 1. 模組目標

從 `HW1/dataset/04.warc`（~1.05 GB ClueWeb09）串流解析，輸出乾淨純文字供 M2 斷詞使用。

---

## 2. 完成狀況

| Step | 工項 | 狀態 | 備註 |
|------|------|------|------|
| S1 | 環境與套件安裝 | ✅ | `pyproject.toml` 更新完畢 |
| S2 | WARC 串流解析（`warc.py`） | ✅ | 自製 parser，不用 warcio |
| S3 | HTTP 解耦與 Content-Type 過濾（`extract.py`） | ✅ | binary sniff + classify |
| S4 | HTML 清洗與編碼修復（`extract.py`） | ✅ | UnicodeDammit + ftfy + lxml |
| S5 | 對外介面封裝（`documents.py`） | ✅ | `iter_documents()` + stats |
| S6 | 測試腳本 | ✅ | `documents.test.py`, `extraction.test.py` |

---

## 3. 關鍵設計決策

- **不用 warcio**：ClueWeb09 的 Content-Length 有大量錯誤，warcio 會在第一筆後讀錯位置。  
  → 改用逐行讀取，以 `b"WARC/0.18"` 作為紀錄邊界。

- **解碼策略**：先用 `UnicodeDammit` 解碼成 `str` 再給 lxml，  
  直接給 `bytes` 時宣告編碼與內容不符會讓 lxml 默默截斷文件（空文件 163 → 1）。

- **Mojibake 修復**：只在 `MOJIBAKE = re.compile(r"Ã[\u0080-\u00bf]|...")` 偵測到時才呼叫 `ftfy.fix_encoding`，避免誤改正常文字。

---

## 4. 對外介面（固定，供 M2/M3 使用）

```python
@dataclass(frozen=True, slots=True)
class Document:
    doc_num: int     # TREC-ID 尾碼整數，作為 postings 的 docID
    trec_id: str     # e.g. "clueweb09-en0000-04-00000"
    url: str
    kind: str        # "html" | "plain"
    text: str        # 清洗後純文字

def iter_documents(path, stats: ExtractionStats | None = None) -> Iterator[Document]: ...
```

---

## 5. 驗收標準（AC）

- [x] RSS < 500 MB（Generator 串流，無一次性載入）
- [x] 僅保留 `WARC-Type: response`，正確提取 `WARC-TREC-ID`
- [x] binary content 被排除（前 1KB 控制字元比例 > 10%）
- [x] `<script>` / `<style>` / `<noscript>` 完全清除
- [x] 編碼解碼不拋未捕獲例外，空文件有記錄但 `text == ""`
- [x] `ExtractionStats.summary()` 可驗證 total == kept + excluded
