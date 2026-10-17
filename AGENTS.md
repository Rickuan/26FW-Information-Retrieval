# Project Conventions & Guidelines for AI Agents

> **Project**: 26FW Information Retrieval (`26FW-Information-Retrieval`)  
> **Environment**: Python 3.12+, `uv` package manager  

---

## 1. Git Commit & Pull Request Conventions

所有 AI 代理人（及開發者）在進行 Git commit 或開啟 Pull Request 時，**必須嚴格遵守以下格式**：

### 格式規範
```
[gitmoji] [分類：feat/doc/chore...][(optional: scope)]: [title]
```

- 範例：
  - `📝 doc(plan): add user slice planning for phase 6 main pipeline`
  - `✨ feat(skip): implement intersect_with_skips for postings`
  - `🐛 fix(indexer): handle edge case when term frequency is zero`
  - `🧪 test(writer): add round-trip validation for binary postings`
  - `⚡️ perf(tokenizer): optimize token normalization loop`
  - `🔧 chore(deps): add psutil to project dependencies`

### 分類 (Type)
- `feat`: 新增功能模組或演算法
- `fix`: 修復程式錯誤或邊界條件問題
- `doc`: 實作計畫文件、說明文件、註解調整
- `test`: 新增或調整單元測試、整合測試
- `perf`: 效能優化（記憶體減少、執行加速）
- `refactor`: 重構程式碼（不改變外部功能行為）
- `chore`: 設定檔調整、依賴管理、環境配置

### 常用 Gitmoji 對照表
| Gitmoji | 簡碼 (Shortcode) | 適用分類 | 說明 |
|---|---|---|---|
| 📝 | `:memo:` | `doc` | 撰寫文件、規格、註解 |
| ✨ | `:sparkles:` | `feat` | 新增功能 |
| 🐛 | `:bug:` | `fix` | 修復 bug |
| 🧪 | `:test_tube:` | `test` | 增加或修復測試 |
| ⚡️ | `:zap:` | `perf` | 提升效能、減少記憶體 |
| ♻️ | `:recycle:` | `refactor` | 重構程式碼 |
| 🔧 | `:wrench:` | `chore` | 修改設定檔或環境 |
| 🚚 | `:truck:` | `refactor` / `chore` | 移動或重新命名檔案 |

### Pull Request 流程規範
- 進行中之功能、計畫或尚未完全驗收之工項，一律建立 **Draft PR**。
- PR 標題必須與 commit 格式完全一致，開頭附帶相應之 gitmoji。
- PR 目標分支預設合併至 `main`。

---

## 2. 開發規範與指引
- **環境管理**：本專案使用 `uv` 進行環境管理（例如 `uv run python ...` 或啟動 `.venv`）。
- **文件與註解保護**：修改程式碼時，保留與變更無關之既有註解與 docstring。
- **測試先行與驗證**：每個模組（M1～M5）均有專屬之 `*.test.py` 與驗收標準（AC），提交前應確保驗證通過。
