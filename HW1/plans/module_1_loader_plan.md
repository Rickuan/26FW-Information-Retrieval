# 模組 1：Loader & 資料前處理 詳細規劃與執行計畫
> **專案/課程**：26FW Information Retrieval - HW1  
> **關聯母計畫**：[`HW1/plans/inverted_index_plan.md`](file:///Users/kuan/Desktop/26FW-Information-Retrieval/HW1/plans/inverted_index_plan.md)  
> **目標資料集**：`HW1/04.warc` (~1.05 GB ClueWeb09 Crawl)  
> **檔案路徑**：`HW1/plans/module_1_loader_plan.md`  
> **狀態**：規劃完成，待執行

---

## 1. 模組目標 (Module Objective)

本模組為倒排索引系統的第一道流水線，負責從約 1.05 GB 的 ClueWeb09 WARC 檔案（`04.warc`）中：
1. **串流解析 (Streaming Extraction)**：以記憶體友善的方式逐筆讀取 WARC 記錄，防止一次性載入造成記憶體耗盡（OOM）。
2. **記錄過濾 (Record Filtering)**：篩選出網頁內容紀錄（`WARC-Type: response`），並提取唯一的 `WARC-TREC-ID` 作為 Document ID。
3. **HTTP 響應解耦 (HTTP Decoupling)**：剝離 HTTP Headers，萃取實際 HTML 網頁內文。
4. **HTML 清洗與編碼修復 (HTML Cleaning & Encoding Fix)**：濾除 `<script>`, `<style>` 等雜訊標籤，清理 HTML Entities，使用 `ftfy` 修復文字編碼，並標準化空白字元。
5. **資料封裝與傳遞 (Data Packaging)**：輸出乾淨的標準文件物件（`Document`），作為模組 2（Tokenizer）的輸入。

---

## 2. 驗收標準 (Acceptance Criteria, AC)

本模組開發完成時，必須通過以下嚴格之驗收標準：

- [ ] **AC 1：串流讀取與記憶體控制 (Memory Footprint)**  
  處理 1.05 GB 的 `04.warc` 全檔時，處理程序的常駐記憶體（RSS）必須嚴格控制在 **500 MB 以內**，保證採用 Generator/Stream 架構，不得將所有文檔一次性存入記憶體串列。
- [ ] **AC 2：記錄過濾與 DocID 精確萃取 (Record & ID Filtering)**  
  僅處理 `WARC-Type: response` 記錄（跳過 `warcinfo` 等），正確提取 `WARC-TREC-ID`（例如 `clueweb09-en0000-04-00000`）；若無 TREC-ID 則安全退回至 `WARC-Record-ID`。
- [ ] **AC 3：HTTP 標頭分離與狀態碼過濾 (HTTP Separation)**  
  正確區隔 HTTP Status Line / Headers 與 Body 內文；預設僅保留 HTTP 狀態碼為 `200`（或有有效內文）之頁面，排除無效響應。
- [ ] **AC 4：HTML 標籤徹底清洗 (Noise Removal)**  
  完全移除 `<script>`, `<style>`, `<noscript>`, `<header>`, `<footer>`, `<nav>`, HTML 註釋等非內文區塊，萃取出的純文字不應含有任何 HTML 標籤（如 `<p>`, `<div>`）。
- [ ] **AC 5：編碼相容性與修復 (Robust Encoding & ftfy)**  
  支援 UTF-8、ISO-8859-1、Windows-1252 等多種網頁編碼；遇到非法位元組或亂碼時不拋出未捕獲例外，並透過 `ftfy.fix_text` 自動修復 Mojibake 亂碼。
- [ ] **AC 6：空白正規化與空文件過濾 (Whitespace & Empty Filtering)**  
  多餘的空白字元（換行、Tab、連續空格）統一縮減為標準單一空格；清洗後長度為 0 或小於預設門檻（如 10 字元）的無效文檔自動過濾。
- [ ] **AC 7：標準化資料結構產出 (Standardized Output)**  
  以統一的 `Document(doc_id: str, url: str, text: str)` 物件向後傳遞，具備型別提示（Type Hinting）。
- [ ] **AC 8：單元測試覆蓋 (Unit Test Coverage)**  
  建立單元測試集，覆蓋「典型 HTML」、「含惡意/損毀 script」、「多種字元編碼」、「畸形 WARC Header」等邊界情況，測試全數 Pass。

---

## 3. 進度追蹤表 (Progress Tracking Table)

> **狀態欄標示**：`未完成` / `進行中` / `已完成`

| 步驟編號 | 子任務項目 | 具體工作項目與產出物 | 關聯檔案 | 狀態 | 備註 |
| :---: | :--- | :--- | :--- | :---: | :--- |
| **Step 1** | **環境與相依套件設置** | 安裝 `warcio`, `beautifulsoup4`, `lxml`, `ftfy`, `tqdm`，並驗證虛擬環境 | `pyproject.toml` | **未完成** | 確認 `uv` 安裝無誤 |
| **Step 2** | **資料結構定義** | 定義 `Document` dataclass 與 `LoaderConfig` 設定類別 | `HW1/src/models.py` 或 `HW1/src/config.py` | **未完成** | 統一規格 |
| **Step 3** | **WARC 串流解析核心** | 實作串流迭代器，過濾 `response` 記錄並提取 `WARC-TREC-ID` 與 URI | `HW1/src/loader.py` | **未完成** | 基於 `warcio` |
| **Step 4** | **HTTP Payload 解耦** | 分離 HTTP 標頭與 Body，依 Content-Type 與狀態碼過濾無效頁面 | `HW1/src/loader.py` | **未完成** | 處理 HTTP/1.1 |
| **Step 5** | **HTML 清洗器 (Cleaner)** | 使用 `lxml` / `BeautifulSoup` 剔除 script/style，轉換 Entities，修復編碼 | `HW1/src/cleaner.py` | **未完成** | 結合 `ftfy` |
| **Step 6** | **例外處理與記憶體監控** | 加上 `try...except` 容錯防護，加入 `tqdm` 進度條與記憶體用量回報 | `HW1/src/loader.py` | **未完成** | RSS < 500MB |
| **Step 7** | **單元測試撰寫** | 撰寫 mock WARC 記錄之單元測試，驗證 8 項驗收標準 | `HW1/tests/test_loader.py` | **未完成** | `pytest` 測試 |
| **Step 8** | **真檔抽樣驗證與評測** | 對 `HW1/04.warc` 前 1,000 筆文件執行抽樣抽取，驗證解析速度與記憶體 | `HW1/scripts/verify_loader.py` | **未完成** | 產出抽樣結果 |

---

## 4. 每個步驟之詳細執行細節 (Detailed Step-by-Step Plan)

### Step 1：環境與相依套件設置 (Environment & Dependencies)
- **要做的事情**：
  1. 檢查並更新 `pyproject.toml`，加入必要套件：
     - `warcio>=1.7.4`（高效流式 WARC 解析）
     - `beautifulsoup4>=4.15.0`
     - `lxml>=6.1.3`（高效 C-based HTML 解析引擎）
     - `ftfy>=6.3.1`（Unicode 亂碼修復）
     - `tqdm>=4.66.0`（串流讀取進度條）
     - `psutil>=5.9.0`（記憶體監控用）
     - `pytest>=8.0.0`（測試框架）
  2. 執行 `uv pip install` 或 `uv sync` 完成安裝。

---

### Step 2：資料結構定義 (Data Models & Configuration)
- **要做的事情**：
  1. 定義 `Document` 類別：
     ```python
     @dataclass
     class Document:
         doc_id: str          # 例如 clueweb09-en0000-04-00000
         url: str             # WARC-Target-URI
         raw_text: str        # 清洗後之純文字內容
         content_length: int  # 字元數或位元組長度
     ```
  2. 定義 `LoaderConfig` 類別：
     ```python
     @dataclass
     class LoaderConfig:
         warc_path: str = "HW1/04.warc"
         min_text_length: int = 10        # 過濾太短的無意義文件
         allowed_http_statuses: tuple = (200,)
         fix_encoding: bool = True
         strip_boilerplate: bool = True   # 是否移除導航/頁尾等標籤
     ```

---

### Step 3：WARC 串流解析核心 (WARC Streaming Parser)
- **要做的事情**：
  1. 引入 `warcio.ArchiveIterator` 以二進位模式開啟檔案：
     ```python
     with open(self.config.warc_path, 'rb') as stream:
         for record in ArchiveIterator(stream):
             ...
     ```
  2. 檢查 `record.rec_type`：
     - 若不是 `'response'`，立即 `continue` 跳過。
  3. 提取記錄中繼資料（Metadata）：
     - `doc_id = record.rec_headers.get_header('WARC-TREC-ID')`
     - 若未設定 `WARC-TREC-ID`，則退回取 `record.rec_headers.get_header('WARC-Record-ID')`。
     - `url = record.rec_headers.get_header('WARC-Target-URI')`。

---

### Step 4：HTTP Payload 解耦 (HTTP Payload Decoupling)
- **要做的事情**：
  1. 讀取 HTTP 響應：
     - 調用 `record.content_stream()` 取得 HTTP 串流。
     - 解析 HTTP 狀態碼（例如 `record.http_headers.get_statuscode()`）：若非 200 且配置要求過濾，則跳過。
  2. 檢查 `Content-Type`：
     - 檢查是否包含 `text/html` 或 `text/plain`。若為圖片、PDF 或二進制檔案則略過。
  3. 提取 Raw Payload 位元組流。

---

### Step 5：HTML 清洗器 (HTML Cleaner & Normalizer)
- **要做的事情**：
  1. **解碼 (Decoding)**：
     - 嘗試依 HTTP Header 中宣告的 charset 解碼（如 `utf-8`, `iso-8859-1`, `windows-1252`）。
     - 若解碼失敗，採用 `raw_bytes.decode('utf-8', errors='replace')` 兜底。
  2. **HTML 解析與標籤剔除**：
     - 使用 `lxml.html`（速度極快）或 `BeautifulSoup(html, 'lxml')`。
     - 剔除特定標籤：`script`, `style`, `noscript`, `header`, `footer`, `nav`, `svg`, `iframe`。
     - 移除 HTML 註解（`Comment` 物件）。
  3. **文字萃取**：
     - 呼叫 `get_text(separator=' ')` 取得標籤間純文字。
  4. **文字編碼修復與空白正規化**：
     - 若開啟 `fix_encoding`，調用 `ftfy.fix_text(text)` 修正 `&amp;amp;`、mojibake 亂碼等。
     - 呼叫 `html.unescape()` 將 HTML 實體字符還原為正常標點/文字。
     - 使用正規表達式 `re.sub(r'\s+', ' ', text).strip()` 將連續空白、換行與 Tab 壓縮為單一空格。
  5. **有效性檢查**：
     - 若清洗後字數小於 `min_text_length`，則放棄該文件。

---

### Step 6：例外處理與記憶體監控 (Error Handling & Memory Monitoring)
- **要做的事情**：
  1. 對單筆 Document 處理加上 `try...except Exception as e`，記錄錯誤日誌並繼續讀取下一筆，防止單一損毀 HTML 終止整個 1GB 流水線。
  2. 整合 `tqdm` 於 `stream_documents()`，即時顯示已解析的文件數量與每秒處理文件數（docs/sec）。
  3. 實作 `psutil.Process().memory_info().rss` 監控機制，若記憶體超過警戒線發出 Warning。

---

### Step 7：單元測試撰寫 (Unit Testing with Pytest)
- **要做的事情**：
  在 `HW1/tests/test_loader.py` 撰寫測試案例：
  1. `test_warc_filter_non_response()`：驗證 `warcinfo` 確實被略過。
  2. `test_trec_id_extraction()`：驗證 `WARC-TREC-ID` 提取準確無誤。
  3. `test_html_cleaner_removes_scripts_and_styles()`：驗證 `<script>alert(1)</script>` 與 `<style>body{color:red}</style>` 徹底被清除，不殘留於文字中。
  4. `test_html_entities_unescape()`：驗證 `&lt;hello&gt; &amp; world` 正確轉換為 `<hello> & world`。
  5. `test_mojibake_encoding_fix()`：驗證經過 `ftfy` 後亂碼字串能正確修復。
  6. `test_empty_or_short_document_filtered()`：驗證純標籤或小於 10 字元之無效頁面被自動略過。

---

### Step 8：真檔抽樣驗證與評測 (Sample Validation on `04.warc`)
- **要做的事情**：
  1. 撰寫抽樣腳本 `HW1/scripts/verify_loader.py`。
  2. 讀取 `HW1/04.warc` 前 500 ~ 1,000 筆資料。
  3. 驗證項目：
     - 總讀取 records 數、有效 response 數、清洗成功率。
     - 檢查輸出前 3 筆之 `doc_id` 與 `raw_text` 內容是否乾淨。
     - 記錄處理速度（docs/sec）與記憶體峰值（Peak RSS MB）。

---

## 5. 模組介面原型 (Class Prototype)

```python
# HW1/src/loader.py
from collections.abc import Generator
from dataclasses import dataclass
import logging
import psutil
from warcio.archiveiterator import ArchiveIterator
from bs4 import BeautifulSoup
import ftfy
import html
import re

@dataclass
class Document:
    doc_id: str
    url: str
    text: str
    length: int

class WarcLoader:
    def __init__(self, warc_path: str, min_text_len: int = 10):
        self.warc_path = warc_path
        self.min_text_len = min_text_len
        self.logger = logging.getLogger(__name__)

    def clean_html(self, html_content: str) -> str:
        """移除 script/style 標籤、修復編碼並正規化空白"""
        pass

    def stream_documents(self) -> Generator[Document, None, None]:
        """
        以 Generator 串流逐筆解析 WARC 檔案
        Yields:
            Document(doc_id, url, text, length)
        """
        pass
```

---

## 6. 下一步行動指示

在開始撰寫程式碼前，請確認本規劃檔案各項驗收標準（AC 1 ~ AC 8）與步驟規劃是否符合預期。  
確認無誤後，即可依照進度表順序從 **Step 1（相依套件設置）** 開始推進實作！
