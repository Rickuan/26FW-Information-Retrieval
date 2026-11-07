# T4 Query parser（核心 T4a、加分 T4b）

> 狀態：T4a、T4b、T4c（§6.8「原字詞彙層與擴充」：資料層、拼字、wildcard、SOUNDEX）都已完成（§9）。§6.8 取代 §6.4 的展開方式與 §6.5 的候選與觸發條件，§2、§3 表中與它衝突的地方以 §6.8 為準。
>
> 原狀態：T1（`done.T1.md`）、T2（`done.T2.md`）、T3（`done.T3.md`）已完成，本計畫已依三者的實作紀錄更新上游接口與行號；可以開始實作。行號以 `grep -n` 對照目前工作樹的 `HW2/src/` 確認過。與 `00-overview.md` 不一致的地方一律以總規劃為準，差異列在 §4.4，需要回寫的項目列在 §9.3。

## 1. 目標
把 query 字串解析成 AST，並列出整個 query 的評分 term 與 query tf，供 T5 過濾、T6 評分。只有一個遞迴下降 parser，接口是 `parse(query, pre)`。T4a／T4b 只代表實作順序與 commit 切分：T4a 先做 `Term`／`And`／`Or`，T4b 再把 NOT、括號、phrase、proximity、wildcard 與拼字建議加進同一個 parser。測試分成核心（`t4.test.py`）與加分（`t4_bonus.test.py`）兩組。

## 2. Index 來源與上游接口（`HW2/index/`）
使用 T1 的 stop+stem index（N = 34,786，573,233 個 term）。`parse` 不讀 index；Preprocessor 一律用 `Preprocessor.from_config(reader.get_metadata()["preprocessor"])` 建立，即 casefold、stopword、stem 為 True，lemma 為 False。測試用 `term in reader` 確認解析出的 token 都在 dictionary 中。T4b 的 `expand`、`position_match`、`suggest` 會經由 `IndexReader` 讀 index。

T4 會用到的接口（都已實作，行為依實作紀錄與原始碼確認）：

| 接口 | 位置 | 實際行為 | T4 誰用 |
| --- | --- | --- | --- |
| `Preprocessor.process(text)` | `tokenizer.py:106-112`（T4c 重構前是 `:94-106`；單一 token 的步驟抽成 `normalize_token`，`:94-104`） | 回傳 `list[(position, term)]`。position 從 1 起算，在過濾 stopword **之前**編號，所以空洞會保留（`"lord of the rings"` → `[(1, 'lord'), (4, 'ring')]`）。只有 `tok.isalpha()` 的 token 才會 stem。 | `parse` |
| `Preprocessor.from_config(cfg)` | `tokenizer.py:113-130`（T4c 重構前是 `:107-124`） | 嚴格模式：`cfg` 為 `None`／`{}` 或缺 casefold／stopword／stem 時拋 `ValueError`；只有 lemma 可缺 | 測試、T7 |
| `IndexReader.df(term)` | `writer.py:486-493` | 取自 lexicon 的 `(df, offset, length)[0]`；term 不存在回傳 0 | `expand`、`suggest`、測試 |
| `IndexReader.N` | `writer.py:481-484` | **property**，寫 `reader.N` | 測試 |
| `IndexReader.__contains__` | `writer.py:473-475` | `term in reader` | 測試 |
| `IndexReader.get_postings(term)` | `writer.py:436-450` | 回傳 `list[Posting]`，`positions` 是 `array('I')`；term 不存在回傳 `[]`。**每次呼叫都重新開檔**（`:447`）並解出全部 positions，`home` 暖身後約 24 ms（`done.T3.md` §9.1） | `position_match`、測試的暴力對照 |
| `IndexReader.get_doc_tf(term)` | `writer.py:554-575`（核心路徑 `_decode_doc_tf` 在 `:577`） | `(doc_nums, tfs)`，doc 嚴格遞增；term 不存在回傳 `([], [])`；block 不一致拋 `ValueError` | `position_match` 先取候選文件（選用） |
| `IndexReader.vocabulary()` | `writer.py:639-647` | 依 Python 字串順序排序的全部 term。回傳**共用的快取 list**（`vocabulary() is vocabulary()`），呼叫端**不可修改**，程式沒有保護 | `suggest`、`suggest_soundex` |
| `IndexReader.prefix_terms(prefix)` | `writer.py:649-666` | 依字典序回傳以 prefix 開頭的 term；回傳的是切片（新的 list，可以修改）。**prefix 是空字串時拋 `ValueError`**（`:655-656`）。`prefix_terms('comput')` 64 筆、`prefix_terms('a')` 31,236 筆 | `expand` |

已用真實 index 確認：`df` 為 `linux` 997、`kernel` 279、`window` 4,552、`open` 5,944、`sourc` 4,062、`retreiv` 11、`retriev` 409、`linu` 28；`comput*` 依 `(-df, term)` 排序的第一個是 `comput`，`a*` 的第一個是 `also`。

## 3. 接口與 stub 位置
### 3.1 已經是真正程式碼的部分
`HW2/src/parser.py` 的 AST dataclass 是**真正的程式碼**（不是 stub），組員可以直接 import：

| 名稱 | 位置 | 欄位 |
| --- | --- | --- |
| `Term` | `parser.py:19-21` | `tokens: list[str]`（沒加引號的運算元，隱含 AND） |
| `Phrase` | `parser.py:24-27` | `tokens: list[str]`、`positions: list[int]`（取自 `process`，保留 stopword 空洞） |
| `Near` | `parser.py:30-34` | `left: Phrase`、`right: Phrase`、`k: int`。單一 token 視為長度 1 的 `Phrase`（`Phrase(['linux'], [1])`）；距離規則見 §6.3 |
| `Wildcard` | `parser.py:37-39` | `prefix: str`（只做 casefold，不做 stem） |
| `Not` | `parser.py:42-44` | `child: Node` |
| `And`／`Or` | `parser.py:47-49`／`:52-54` | `children: list[Node]` |
| `Node` | `parser.py:57` | `Term \| Phrase \| Near \| Wildcard \| Not \| And \| Or` |

- 都是一般的 `@dataclass`（非 frozen）：有 `__eq__`，測試可以直接用 `==` 比對整棵樹；**不可 hash**，不能當 dict key 或放進 set。也因為可變，`expand` 不得修改傳入的樹。
- import 關係：`positional.py:6` 在執行期 `from parser import Near, Phrase`；`boolean.py:6` `from parser import Node`。`parser.py` 不 import 這兩個模組，沒有循環。`parser` 這個模組名在 Python 3.10 之後不再與標準庫衝突。

### 3.2 還是 stub 的部分（`raise NotImplementedError`）
| 函式 | 位置 | 段落 |
| --- | --- | --- |
| `parse(query: str, pre: Preprocessor) -> Node \| None` | `parser.py:60-75` | 核心 + 加分 |
| `expand(node: Node \| None, reader: IndexReader, limit: int = 100) -> Node \| None` | `parser.py:78-84` | 核心（原樣回傳）+ 加分（Wildcard） |
| `query_terms(node: Node) -> Counter[str]` | `parser.py:87-95` | 核心 |
| `position_match(node: Phrase \| Near, reader: IndexReader) -> set[int]` | `positional.py:12-19` | 加分 |
| `suggest(term: str, reader: IndexReader, limit: int = 5) -> list[str]` | `spelling.py:13-20` | 加分 |
| `soundex(word: str) -> str` | `spelling.py:23-25` | 加分 |
| `suggest_soundex(term: str, reader: IndexReader, limit: int = 5) -> list[str]` | `spelling.py:28-30` | 加分 |

`boolean.evaluate`（`boolean.py:12-23`）屬於 T5，T4 不動；它的 docstring 已經寫好 Phrase／Near 會呼叫 `position_match`。

### 3.3 查詢流程（與 `00-overview.md`「查詢流程」相同）
```python
node = parse(query, pre)          # None → 直接輸出空結果，後面都不呼叫
node = expand(node, reader)       # 沒有 Wildcard 時原樣回傳；可能回傳 None（見 §4.4 D1）
cands = evaluate(node, reader)    # T5；None 代表不過濾
qtf = query_terms(node)           # T4
hits = rank(qtf, cands, reader)   # T6
```
例：`parse("open source AND Linux", pre)` → `And([Term(['open', 'sourc']), Term(['linux'])])`，`query_terms` → `Counter({'open': 1, 'sourc': 1, 'linux': 1})`。

## 4. 實作切分

| 段落 | 範圍 | 改的檔案 | 測試檔 | 不動 |
| --- | --- | --- | --- | --- |
| **核心（T4a）** | lexer；遞迴下降的 `Term`／`And`／`Or`；優先序 AND > OR；空節點規則 `_prune`；`query_terms`（完整規則）；`expand` 的原樣回傳路徑 | `HW2/src/parser.py` | `HW2/tests/t4.test.py`（新增） | `positional.py`、`spelling.py`、`writer.py`、`tokenizer.py`、`boolean.py` |
| **加分（T4b）** | 括號、`Not`、`Phrase`、`Near`、`Wildcard` 與 `expand` 的展開；`position_match`；`suggest`；`soundex`／`suggest_soundex` | `HW2/src/parser.py`、`HW2/src/positional.py`、`HW2/src/spelling.py` | `HW2/tests/t4_bonus.test.py`（新增）；`t4.test.py` 必須照樣全過 | `writer.py`、`tokenizer.py`、`boolean.py` |

兩個測試檔都仿照 `t1`～`t3` 的 `check()` 腳本風格：每項包在 try/except 裡（stub 拋 `NotImplementedError` 時記為 FAIL，不中斷），用 `sys.path.insert` 加入 `HW2/src`，index 路徑以 `__file__` 推算。先寫測試、在 stub 狀態跑一次確認失敗，再實作。

### 4.1 核心（T4a）：`parser.py`
完整語法如下。T4a 只實作標註「T4a」的部分，T4b 在同一個 parser 上擴充：
```
or      := and ("OR" and)*                       # T4a
and     := unary (["AND"] unary)*                # T4a；相鄰的運算元視為隱含 AND（T4b 才會出現）
unary   := "NOT" unary | primary                 # NOT：T4b
primary := WORD+                                 # T4a：連續的 WORD 合成一個 Term
         | "(" or ")" | PHRASE | WILDCARD        # T4b
         | side NEAR side                        # T4b；NEAR 是 /k
side    := WORD+ | PHRASE                        # T4b；Near 的一邊，一律轉成 Phrase
```

| 位置 | 改法 |
| --- | --- |
| `parser.py` 新增 `_lex(query)` | 回傳 `list[(kind, text, pos)]`，`pos` 是字元位置（從 0 起算）。核心用 `re.finditer(r"\S+", query)` 依空白切；只有**獨立的大寫** `AND`／`OR` 是運算子（`ANDROID`、`and`、`Or` 都是 `WORD`）。運算子在 `process` 之前就切出來，因為 `and`／`or` 是 stopword，順序反過來會被濾掉。寫成獨立函式，T4b 只換掉 regex 與分類規則。 |
| `parser.py:60-75` `parse` | 1. 去掉頭尾空白後若是空字串，回傳 `None`，不發出警告。2. `_lex` 後依上面的語法遞迴下降，所以 AND 的優先序高於 OR。3. `primary` 把連續的 `WORD` 用空白接起來，呼叫一次 `pre.process`，保留**全部** token：`Term([t for _, t in pre.process(text)])`（`e-mail` → `['e', 'mail']`，不要學 HW1 只取 `toks[0]`）。少了運算元的地方（例如 `linux AND`）產生空的 `Term([])`。4. 最後呼叫 `_prune`。docstring 保留。 |
| `parser.py` 新增 `_prune(node)` | 空節點規則，T4b 也沿用。見下方。 |
| `parser.py:78-84` `expand` | 核心只處理「樹中沒有 Wildcard」：原樣回傳（`None` 也原樣回傳）。遇到 Wildcard 先拋 `NotImplementedError`。因為流程固定會呼叫 `expand`，核心一定要實作這條路徑。 |
| `parser.py:87-95` `query_terms` | 遞迴走過整棵樹，把每個 `Term`／`Phrase` 的 tokens 與 `Near` 兩側（都是 `Phrase`）的全部 tokens 加進同一個 `Counter`，重複的 token 都要計數。跳過 `Not` 的子樹；遇到 `Wildcard` 拋 `ValueError`。規則很簡單，核心就一次做完（含 Phrase、Near、Not、Wildcard 分支）。 |

**空節點規則**（`_prune`，在樹上處理，與 `00-overview.md`「T4 Query parser」的「注意」一致）：
- 空的 `Term`／`Phrase` 從父節點移除，每移除一個就用 `warnings.warn` 警告一次（根節點本身是空的也算一次）
- 沒有 child 的 `And`／`Or` 移除；只剩一個 child 時攤平成那個 child
- `Not` 的 child 是空的就移除這個 `Not`
- 整棵樹都是空的就回傳 `None`
- T4 補充（總規劃未寫，見 §4.4 D3）：同類型的巢狀節點合併（`And([And([a, b]), c])` → `And([a, b, c])`）

**警告的約定**：一律用 `warnings.warn(..., stacklevel=2)`，類別用預設的 `UserWarning`。T7 負責把它們導到 stderr（`00-overview.md`「T7」的「警告」）。

### 4.2 核心驗收（`HW2/tests/t4.test.py`）
執行方式：`uv run python HW2/tests/t4.test.py`。下表用 `T([...])` 代表 `Term([...])`；AST 用 `==` 比對。警告用 `warnings.catch_warnings(record=True)` 計數，**區塊內必須先 `warnings.simplefilter("always")`**：Python 預設的過濾器同一個位置、同一則訊息只顯示一次，`AND` 的兩次警告會被併成一次。T4b 合併後這組測試必須照樣全部通過。

| 輸入 | 預期 AST | 預期 `query_terms` | 警告 |
| --- | --- | --- | --- |
| `Microsoft` | `T(['microsoft'])` | microsoft 1 | 無 |
| `United States government` | `T(['unit', 'state', 'govern'])` | 三個 term 各 1 | 無 |
| `open source AND Linux` | `And([T(['open', 'sourc']), T(['linux'])])` | open、sourc、linux 各 1 | 無 |
| `software engineer OR project manager` | `Or([T(['softwar', 'engin']), T(['project', 'manag'])])` | 四個 term 各 1 | 無 |
| `a AND b OR c` | `Or([T(['b']), T(['c'])])`：`a` 是 stopword，`And([∅, b])` 攤平成 `b` | b 1、c 1 | 1 次 |
| `linux AND kernel OR windows` | `Or([And([T(['linux']), T(['kernel'])]), T(['window'])])` | 三個 term 各 1 | 無 |
| `windows OR linux AND kernel` | `Or([T(['window']), And([T(['linux']), T(['kernel'])])])` | 同上 | 無 |
| `e-mail` | `T(['e', 'mail'])` | e 1、mail 1 | 無 |
| `new new york` | `T(['new', 'new', 'york'])` | new 2、york 1 | 無 |
| `open and linux` | `T(['open', 'linux'])`：小寫 and 不是運算子，被當成 stopword 濾掉 | open 1、linux 1 | 無 |
| `ANDROID linux` | `T(['android', 'linux'])`：`ANDROID` 不是運算子 | android 1、linux 1 | 無 |
| Python 字串 `''`、`'   '` | `None` | — | 無 |
| `the of`（只有 stopword） | `None` | — | 1 次 |
| `AND` | `None` | — | 2 次 |
| `AND linux` | `T(['linux'])` | linux 1 | 1 次 |
| `linux OR` | `T(['linux'])` | linux 1 | 1 次 |
| `linux AND OR kernel` | `Or([T(['linux']), T(['kernel'])])` | linux 1、kernel 1 | 1 次 |
| `linux OR the AND kernel` | `Or([T(['linux']), T(['kernel'])])`：`And([∅, kernel])` 攤平成 `kernel` | linux 1、kernel 1 | 1 次 |
| `linux AND the AND kernel` | `And([T(['linux']), T(['kernel'])])` | linux 1、kernel 1 | 1 次 |
| `linux OR linux` | `Or([T(['linux']), T(['linux'])])` | linux 2 | 無 |

- [ ] 上表每一列的 AST、`query_terms` 與警告次數都符合
- [ ] 上表出現的所有 token 都滿足 `t in reader`（已用 stop+stem 的 Preprocessor 實際跑過 `process`，結果與表中相同，`android` 也已確認存在）
- [ ] `a AND b OR c` 中的 `a` 會被濾掉，所以優先序由 `linux AND kernel OR windows` 與它的反向版本驗證
- [ ] `expand(node, reader)` 對上表每一列都回傳 `== node` 的結果；`expand(None, reader) is None`
- [ ] `query_terms` 的其他分支直接用手建的節點測：`query_terms(Not(T(['linux']))) == Counter()`；`query_terms(And([Phrase(['open', 'sourc'], [1, 2]), Near(Phrase(['linux'], [1]), Phrase(['kernel'], [1]), 5), Not(T(['window']))]))` 是 open、sourc、linux、kernel 各 1；`query_terms(Near(Phrase(['e', 'mail'], [1, 2]), Phrase(['server'], [1]), 5))` 是 e、mail、server 各 1；`query_terms(Wildcard('comput'))` 拋 `ValueError`
- [ ] `parse` 不讀 index：只用 Preprocessor 就能跑完上表

### 4.3 加分（T4b）：`parser.py`、`positional.py`、`spelling.py`
T4b 直接擴充同一個 `parse`，不新增參數，也不另寫 parser。一般文字的 query 在 T4b 前後結果相同；但 T4b 之後，`"`、`(`、`)`、獨立的 `NOT`、`/k`、結尾的 `*` 會成為語法符號。T5–T7 需要配合的地方見 `00-overview.md` 對應的小節。

| 項目 | 評分面向 | 接口 | 改動的檔案 | 依賴 | 優先度 |
| --- | --- | --- | --- | --- | --- |
| 6.1 NOT、括號 | query 多樣性 | `parse(query, pre)`（擴充語法） | `parser.py` | T4a | 中 |
| 6.2 Phrase | query 多樣性 | `Phrase`、`position_match(node, reader) -> set[int]`（`positional.py:12`） | `parser.py`、`positional.py` | T4a、`get_postings` | 高 |
| 6.3 Proximity | query 多樣性 | `Near`、同上 | 同上 | 同上 | 高 |
| 6.4 Wildcard | query 多樣性 | `Wildcard`、`expand(node, reader, limit=100)`（`parser.py:78`） | `parser.py` | T1 加分 `prefix_terms`、T1 `df` | 中 |
| 6.5 拼字更正 | query 多樣性 | `suggest(term, reader, limit=5) -> list[str]`（`spelling.py:13`） | `spelling.py` | T1 加分 `vocabulary`、T1 `df` | 中 |
| 6.6 Soundex | query 多樣性 | `soundex(word) -> str`（`spelling.py:23`）、`suggest_soundex(term, reader, limit=5)`（`spelling.py:28`） | `spelling.py` | 同上 | 低 |

詳細規則見第 6 節，驗收見 6.7。

### 4.4 與總規劃（`HW2/plans/00-overview.md`）的一致性檢查
以下逐項比對「接口定義」（第 51–136 行）、「查詢流程」（第 138–150 行）與「T4 Query parser」（第 192–217 行）。結論：沒有互相衝突的規則；本計畫原本只有一處寫法與總規劃不一致（D0，已改成以總規劃為準），其餘是總規劃沒寫、本計畫補充的細節，需要回寫（§9.3）。

| # | 項目 | 總規劃 | 本計畫 | 處理 |
| --- | --- | --- | --- | --- |
| D0 | 查詢流程中 `parse` 回傳 `None` | 第 139 行：直接輸出空結果，後面的步驟都不呼叫 | 舊版 §3 範例寫 `expand(parse(...), reader)`，把 `None` 傳進 `expand` | **已改成總規劃的寫法**（§3.3）。`expand(None)` 仍回傳 `None`（簽名允許），只當防呆 |
| D1 | `expand` 回傳 `None` | 第 139–145 行只說 `parse` 回傳 `None` 時停止；`evaluate(node: Node)` 不接受 `None` | Wildcard 展開成 0 個 term 且整棵樹因此變空時（例如 `computing*`），`expand` 回傳 `None` | 總規劃有漏洞，需回寫：「`parse` **或 `expand`** 回傳 `None` 時直接輸出空結果」 |
| D2 | `parse` 的 `ValueError` | 第 91、216 行：引號或括號沒有配對，訊息含字元位置（從 0 起算）；第 278 行 T7 只提這兩種 | 另外對單獨的 `*`（prefix 為空）與 `/0` 也拋 `ValueError`，訊息同樣含字元位置。（原本還有「Near 一側超過一個 token」，已刪除：Near 兩邊改成 `Phrase`，見 D13） | 不衝突（T7 一律接 `ValueError`），已回寫 |
| D3 | 空節點規則 | 第 204–208 行四條規則 | 同四條；另加「同類型巢狀節點合併」「只有一個 token 的 Phrase 簡化成 Term」「Near 一側為空時由另一側取代並警告（1 個 token 變 Term，多個 token 保留 Phrase）」「展開成 0 個 term 的 Wildcard 依規則移除並警告」 | 四條規則一致；補充的四條已回寫 |
| D4 | `expand` 的排序與警告 | 第 93 行：依 df 取前 limit 個，超過時警告 | 依 `(-df, term)` 排序（df 相同時依字典序）；超過時警告一次，訊息含總數；只有 1 個時是 `Term`；不修改傳入的樹 | 一致，需回寫同分規則 |
| D5 | `prefix_terms` 的錯誤 | 第 123 行只寫「排序 list + bisect」 | 空字串拋 `ValueError`（`writer.py:655-656`）。`parse` 遇到 `*` 已先拋錯，所以 `expand` 不會傳空字串 | 需回寫第 123 行 |
| D6 | 拼字建議的觸發條件 | 第 281–283 行：原詞 df == 0，或 `reader.df(s[0]) >= reader.df(token) * 10` | 同上；補充「`s` 是空 list 時不觸發」（否則 `s[0]` 會 `IndexError`）。df == 0 時第二條在 `s` 非空時必然成立，兩條可以合併成「`s` 非空且第二條成立」 | 一致，需回寫空 list 的情況 |
| D7 | `parse(query, pre)` | 第 88–91 行 | 相同，沒有 `extended` 參數 | 一致 |
| D8 | `expand(..., limit=100)` | 第 92 行，預設 100 | 相同 | 一致 |
| D9 | `position_match(node: Phrase \| Near, reader) -> set[int]` | 第 99 行：用 `get_postings` 的 positions | 相同；補充 `get_postings` 每次呼叫都重新開檔（`writer.py:447`），每個 token 只呼叫一次 | 一致 |
| D10 | 純 NOT | 第 96、107、215 行：`parse` 回傳 `Not(...)`，`evaluate` 回傳全集減 X，`query_terms` 回傳 `Counter()` | 相同；輸出方式由 T6／T7 決定 | 一致 |
| D11 | 優先序 | 第 90 行 NOT > AND > OR | 相同 | 一致 |
| D13 | Near 的欄位與距離 | 原本 `Near(left: Term, right: Term, k)`、「找距離 ≤ k 的配對」 | 改成 `Near(left: Phrase, right: Phrase, k)`；距離是兩段位置區間之間的間隔，不分先後，含 stopword 空洞（§6.3） | 本輪同步改了總規劃與 `parser.py` |
| D12 | 切運算子的做法 | 第 196 行：「先用大寫的 AND／OR 把原始字串切成運算元，再對每個運算元呼叫 `process`」 | lexer 切出 token（含字元位置）再遞迴下降；效果相同，運算子仍在 `process` 之前切出 | 用詞不同，效果一致；可選擇回寫成「lexer + 遞迴下降」 |

## 5. （已併入 §4.2）
核心驗收見 §4.2；保留本節編號，讓第 6 節以後的編號與舊版相同。

## 6. 加分項細節（T4b，T4a 合併後才開始）

### 6.1 語法擴充（優先序 NOT > AND > OR）
- **詞法擴充**：`_lex` 改用 `re.finditer(r'"[^"]*"?|[()]|[^\s()"]+', query)`，並記住字元位置。新增的 token 類型：
  - `PHRASE`：引號內的文字（沒有結尾引號時拋錯，位置是開頭引號）
  - `(`、`)`
  - 運算子 `NOT`：獨立的大寫 `NOT`
  - `NEAR`：整個 token 符合 `/\d+`
  - `WILDCARD`：結尾是 `*` 的詞
- **語法**：見 §4.1。`and` 中相鄰的運算元視為隱含 AND，例如 `linux NOT windows` 等於 `linux AND NOT windows`。
- **Near 的兩邊**（`side NEAR side`）：
  - 一邊是連續的 `WORD`（遇到運算子、`(`、`)`、`PHRASE`、`WILDCARD`、`NEAR` 就停），或一個 `PHRASE`。`e-mail /5 server` 的左邊是 `e-mail`，右邊是 `server`。
  - 每一邊各自呼叫一次 `pre.process`，轉成 `Phrase(tokens, positions)`，positions 從 1 起算並保留 stopword 空洞。**單一 token 時也是長度 1 的 `Phrase`**，不套用「單 token Phrase 簡化成 Term」的規則。
  - 一邊在 `process` 後變成空的：整個 Near 由另一邊取代，並發出警告一次；兩邊都空就依空節點規則移除。
    - 另一邊只有 1 個 token：變成 `Term`（`the /3 linux` → `Term(['linux'])`）
    - 另一邊有多個 token：保留為 `Phrase(tokens, positions)`，**不能**轉成 `Term`，否則會失去相鄰條件（`"open source" /3 the` → `Phrase(['open', 'sourc'], [1, 2])`）
- **錯誤**：以下情況拋 `ValueError`，訊息包含字元位置（從 0 起算）：
  - 引號沒有配對（位置是開頭的 `"`）
  - `(` 沒有配對（位置是該 `(`）
  - 多出來的 `)`（位置是該 `)`）
  - 單獨的 `*`（prefix 是空的）
  - `/0`
  - （原本的「Near 的一側經過 `process` 後超過一個 token 就拋錯」已刪除：`e-mail /5 server` 現在是合法的 Near）
- **缺少運算元**時沿用 T4a 規則：產生空節點並發出警告，再交給 `_prune`。例如 `linux AND`、`NOT`、`()`。

### 6.2 Phrase、6.3 Near（`position_match`，`positional.py:12-19`）
- `"open source"` → `Phrase(['open', 'sourc'], [1, 2])`；`"lord of the rings"` → `Phrase(['lord', 'ring'], [1, 4])`（已用 `process` 確認）。
- 單獨出現、只有一個 token 的 phrase 簡化成 `Term`；空的 phrase 依空節點規則移除。Near 的兩邊不簡化（§6.1）。
- **Phrase 的比對**：先用 `get_doc_tf` 的 doc 集合取交集，找出全部 token 都出現的文件；再對每個 token 呼叫一次 `get_postings`，只為候選文件建 `doc → set(positions)`。對每篇候選文件，檢查是否存在 p（取自 `tokens[0]` 的 positions），使每個 `tokens[i]` 都出現在 `p + positions[i] - positions[0]`。同一個 token 出現兩次（`"new new york"`）時共用同一份 postings。
- **Phrase 的區間**：每個符合的 p 對應一個位置區間 `[start, end] = [p, p + positions[-1] - positions[0]]`；長度 1 的 Phrase 是 `start == end`。區間以 index 的位置計算，包含 stopword 留下的空洞（`"lord of the rings"` 的區間是 `[p, p+3]`）。Phrase 與 Near 共用這個 helper（例如 `_phrase_intervals(phrase, reader) -> dict[int, list[tuple[int, int]]]`）。
- **Near 的比對**（取代原本的「`|p_l - p_r| ≤ k`」）：
  1. 左右兩邊各自用 phrase 的規則找出每篇文件中完整出現的區間；只看兩邊都有區間的文件。
  2. 兩段區間之間的間隔：右邊在後時是 `R.start − L.end`，左邊在後時是 `L.start − R.end`。**不分左右順序**，`a /5 b` 也比對 b 在 a 前面的情況。
  3. 任一方向滿足 `1 ≤ 間隔 ≤ k` 就命中；兩段區間重疊時兩個方向都 ≤ 0，不算命中。
  4. 一篇文件內只要有任一組（左區間, 右區間）命中，就算符合。
  - 相鄰（`linux kernel`）的間隔是 1；中間隔一個 stopword（`linux the kernel`）是 2。單一 token 的兩邊時，間隔就是兩個位置的差。
  - 實作：區間依 `start` 排序後可以用雙指標；正確性以測試的暴力對照為準。
- Near 某一側是空的（stopword）時，在 `parse` 就由另一側取代（1 個 token 是 `Term`，多個 token 是 `Phrase`，見 §6.1）並發出警告，所以 `position_match` 拿到的 Near 兩側都至少有一個 token。`position_match(node, reader) -> set[int]` 的簽名不變，T5 只呼叫它，不讀 Near 的欄位。
- `positional.py:13-18` 的 docstring 還是舊規則（「某對位置差的絕對值 ≤ k」），實作 T4b 時一併改成本節的規則。
- 位置以含 stopword 的 token 位置計算，與 index 相同。
- `get_postings` 每次呼叫都重新開檔並解出全部 positions（`writer.py:436-450`），高 df 詞（`home`）一次約 24 ms；T4b 不改 `writer.py`，只保證每個 token 只呼叫一次。

### 6.4 Wildcard（`expand`，`parser.py:78-84`）
> T4b 的版本，**已被 §6.8.4 取代**：wildcard 改在原字詞彙上比對、支援任意位置的 `*`、改用 `Wildcard(pattern)`；`computing*` 的限制已解除。本節保留作為歷史紀錄。
- `Comput*` → `Wildcard('comput')`：只做 casefold，不做 stem。所以 `computing*` 對不到 dictionary 中的 `comput`，會展開成空的結果並發出警告。這是已知限制，要寫進文件。
- **展開方式**：`reader.prefix_terms(prefix)`（`writer.py:649-666`；空字串會拋 `ValueError`，但 `parse` 已先擋掉 `*`）取得候選，依 `(-df, term)` 排序後取前 `limit` 個（預設 100），組成 `Or([Term([t]) ...])`。`prefix_terms` 回傳的是新的 list，但仍用 `sorted()`，不要原地排序。
  - 超過 `limit` 時發出一次警告，訊息包含總數
  - 只有 1 個時就是 `Term`
  - 0 個時依空節點規則移除（並警告）；整棵樹因此變空時回傳 `None`（§4.4 D1）
- 不修改傳入的樹，回傳新的樹；展開後再跑一次 `_prune`。

### 6.5 拼字更正（`suggest`，`spelling.py:13-20`）
> T4b 的版本，**已被 §6.8.3 取代**：候選、輸入輸出與觸發條件都改成原字（`retreival` → `retrieval`），stem 的 k-gram index 已刪除。本節保留作為歷史紀錄。
- **輸入**：dictionary 形式的 token（`process` 之後的結果）。
- **候選與排序**：
  - 用 `vocabulary()` 建立 bigram（前後加 `$`）的 k-gram index，第一次呼叫時建立並依 reader 快取。`writer.py` 不動，所以快取放在 `spelling.py` 的模組層級（例如以 reader 為 key 的 `weakref.WeakKeyDictionary`）。`vocabulary()` 是共用的 list，只讀不改。
  - 候選條件是 Jaccard ≥ 0.3，排除 term 本身
  - 依 `(Damerau-OSA 距離, -df, term)` 排序，取前 `limit` 個
- **只提供「Did you mean」建議**，不自動替換。
- **觸發條件**（已決定，由 T7 判斷，與 `00-overview.md` 第 281–283 行相同）：原詞的 df == 0，或 `reader.df(s[0]) >= reader.df(token) * 10`；顯示 `s[:3]`。另補充：`s` 是空的就不觸發（§4.4 D6）。
  - `retreival` 經過 stem 後是 `retreiv`，它本身就在 dictionary 中（df 11，是語料裡的錯字），所以只靠第一條不會觸發。
  - 最佳建議 `retriev` 的 df 是 409 ≥ 110，第二條會觸發。
- **限制**：dictionary 存的是 stem 過的詞，建議的結果也是 stem 形式。例如建議的是 `retriev`，不是 `retrieval`，畫面上要說明。
- **預先量測**（暴力掃描版，k-gram index 會更快）：`suggest('retreival')` 的前三名是 `retreiv`、`retrial`、`retriev`；`suggest('retreiv')` 的第一名是 `retriev`（df 409）。

### 6.6 Soundex（`spelling.py:23-30`，優先度低）
> T4b 的版本。`soundex()` 不改；`suggest_soundex` **已依 §6.8.5 改到原字詞彙上**（只維護一份對照表，依 stem 去重、回傳原字），並新增了 `SOUNDEX(x)` 運算子，把同碼的原字全部擴展進 query。
- 標準 American Soundex：保留第一個字母，其餘字母轉成數字；h／w 不隔開相同的數字。
- `suggest_soundex` 只比對純字母的 term，依 `(-df, term)` 排序，不含 term 本身。Soundex 碼的對照表同樣依 reader 快取在 `spelling.py`。
- **stem 的影響**：Soundex 只看第一個字母加上前三個子音碼，而 stem 通常只去掉字尾，所以多數 stem 和原形同碼（`comput`、`computer` 都是 C513）。但短字被 stem 時可能落到不同的碼。dictionary 約 57 萬個 term，Soundex 碼只有約 9 千種，碰撞非常多，所以只能當作輔助建議。

### 6.7 驗收測試（加分，`HW2/tests/t4_bonus.test.py`）
執行方式：`uv run python HW2/tests/t4_bonus.test.py`。警告計數同 §4.2（要 `simplefilter("always")`）。表中的 AST 是 `expand` 之前的結果。

| 輸入 | 預期 AST | 預期 `query_terms` | 警告 |
| --- | --- | --- | --- |
| `(linux OR windows) AND kernel` | `And([Or([T(['linux']), T(['window'])]), T(['kernel'])])` | linux、window、kernel 各 1 | 無 |
| `linux AND NOT windows` | `And([T(['linux']), Not(T(['window']))])` | linux 1（不含 window） | 無 |
| `linux NOT windows` | 同上（隱含 AND） | 同上 | 無 |
| `NOT linux` | `Not(T(['linux']))` | 空的 `Counter()` | 無 |
| `"open source" AND linux` | `And([Phrase(['open', 'sourc'], [1, 2]), T(['linux'])])` | open、sourc、linux 各 1 | 無 |
| `"lord of the rings"` | `Phrase(['lord', 'ring'], [1, 4])` | lord 1、ring 1 | 無 |
| `linux /5 kernel` | `Near(Phrase(['linux'], [1]), Phrase(['kernel'], [1]), 5)` | linux 1、kernel 1 | 無 |
| `e-mail /5 server` | `Near(Phrase(['e', 'mail'], [1, 2]), Phrase(['server'], [1]), 5)` | e、mail、server 各 1 | 無 |
| `the /3 linux` | `T(['linux'])`：左邊是空的，右邊只有 1 個 token，變成 Term | linux 1 | 1 次 |
| `"open source" /3 the` | `Phrase(['open', 'sourc'], [1, 2])`：右邊是空的，左邊有多個 token，保留為 Phrase（不轉成 Term） | open 1、sourc 1 | 1 次 |
| `NOT (a OR b)` | `Not(T(['b']))` | 空的 `Counter()` | 1 次 |
| `((linux))` | `T(['linux'])` | linux 1 | 無 |
| `"linux"` | `T(['linux'])` | linux 1 | 無 |
| `(linux AND kernel) AND window` | `And([T(['linux']), T(['kernel']), T(['window'])])`（同類型合併） | 三個 term 各 1 | 無 |
| `Comput*` | `Wildcard('comput')` | 拋 `ValueError`（尚未 expand） | 無 |

- [ ] 上表每一列都符合
- [ ] **核心回歸**：T4b 合併後，`t4.test.py` 仍全部通過
- [ ] **`comput*`**：`expand` 後是 `Or`，共 64 個 `Term`（完整展開），全部以 `comput` 開頭，第一個是 `T(['comput'])`（df 最高），沒有警告；`expand` 前後的原樹 `==` 不變
- [ ] **`a*`**：`expand` 後共 100 個 `Term`，第一個是 `T(['also'])`；警告 1 次，訊息包含 `31236`
- [ ] **`computing*`**：`expand` 後是 `None`，警告 1 次；`linux OR computing*` 展開後是 `T(['linux'])`
- [ ] **沒有配對時拋 `ValueError`**，訊息包含位置：
  - `"open source AND linux` → 位置 0
  - `(linux OR windows` → 位置 0
  - `linux)` → 位置 5
  - `linux AND (kernel` → 位置 10
- [ ] 單獨的 `*`、`linux /0 kernel` 拋 `ValueError`；`e-mail /5 server` **不**拋錯（見上表）
- [ ] **`position_match`**：結果用另一種寫法獨立對照：測試內直接用 `get_postings` 的 positions，以兩層迴圈暴力比對（每一邊找出 phrase 區間，再對所有區間組合檢查 §6.3 的間隔），不 import `positional.py` 的 helper，也不拿 `position_match` 的結果當預期值。
  - `"lord of the rings"`、`"open source"` 的結果與暴力比對完全相同
  - **`e-mail /5 server`**（左邊經 `process` 變成 `e`、`mail` 兩個 token）：與暴力比對完全相同。預先用同樣的暴力法在真實 index 上算出 27 篇，只用來檢查測試本身，不寫死成預期值
  - **不分順序**：doc 1400 在 `e-mail /5 server` 中只靠「`server` 在 `e mail` 前面」命中，要在結果中；`linux /5 kernel` 的結果也要包含只靠反方向命中的文件（由暴力法找出）
  - `"open source"` 的結果是 `open /1 source` 結果的子集
  - `linux /5 kernel` 與 `kernel /5 linux` 結果相同
  - `linux /1000000 kernel` 等於同時含 linux 與 kernel 的文件集合
- [ ] **拼字**：
  - `retriev` 在 `suggest('retreival')` 的前 3 名內
  - `suggest('retreiv')[0] == 'retriev'`
  - 結果不含輸入本身，長度 ≤ 5
  - 呼叫前後 `reader.vocabulary()` 的長度與前幾個元素不變（沒有被修改）
- [ ] **觸發條件**：預期值已用 `reader.df` 確認（`retreiv` 11、`retriev` 409、`linux` 997、`linu` 28），測試時再算一次。
  - `retreiv` 的最佳建議是 `retriev`（409 ≥ 110），會觸發
  - `linux` 的最佳建議是 `linu`（28 < 9970），不觸發
- [ ] **Soundex**：
  - `soundex('Robert') == soundex('Rupert') == 'R163'`
  - `soundex('Ashcraft') == 'A261'`、`soundex('Tymczak') == 'T522'`、`soundex('Pfister') == 'P236'`、`soundex('Honeyman') == 'H555'`
  - `'retriev' in suggest_soundex('retreiv', reader)`（兩者都是 R361）
- [ ] **計時**（寫進 §9.1，不設門檻）：k-gram index 的建置時間與記憶體（`tracemalloc`）、`suggest` 單次時間、`position_match('"open source"')` 與 `linux /5 kernel` 的時間

### 6.8 原字詞彙層與擴充（T4c，已實作，見 §9.1.3、§9.1.4）
T4b 完成後的追加項目。它取代 §6.4 的展開方式、§6.5 的候選與觸發條件，並新增 `SOUNDEX(x)` 運算子。§6.1–§6.3 的語法與 `position_match` 不變。本節的數字都是用一次性的唯讀腳本，在真實的 `HW1/output` 與 `HW2/index` 上預先量出來的（本機 WSL2，各量一次），只用來設計規則與檢查測試本身，不寫死成程式的行為。

**要解決的問題**
- (a) `suggest` 在 stem 過的 dictionary 上比對，所以建議的是 stem 形式：`retreival` 得到的是 `retreiv`（語料中的錯字，df 11）或 `retriev`，使用者看不懂。
- (b) wildcard 只支援結尾的 `*`。另外，prefix 是拿去比對 stem，所以 `computing*` 對不到任何 term（§6.4、§10.4）。
- (c) `suggest_soundex` 依 df 排序，從同碼的詞中挑出「最像的詞」。但 Soundex 的標準用法是把同一個碼的所有詞視為等價，一起擴展進 query。而且 Soundex 原本是為人名設計的，用在一般檢索中效果本來就有限。

#### 6.8.1 原字詞彙層（`build_surface_vocab.py`、`surface.py`）
**來源**：`HW1/output/`，也就是沒有 stem 的 index：N = 34,786，644,523 個詞，`casefold=True`、`stopword=False`、`stem=False`，metadata 沒有 `lemma` 欄位。`lexicon.tsv` 的格式與 `HW2/index/lexicon.tsv` 相同（term、df、offset、length，用 tab 分隔，以 `csv` 讀寫），而且已經依 Python 字串順序排序。兩個資料夾的檔名完全相同，**絕對不能**把 `HW1/output` 的檔案複製進 `HW2/index`。新產生的檔名（`surface_vocab.*`）不會和既有檔案衝突。

**建置腳本 `HW2/src/build_surface_vocab.py`**（新增；CLI：`uv run python HW2/src/build_surface_vocab.py [--hw1-dir DIR] [--index-dir DIR]`，預設路徑以 `__file__` 推算）：
1. **檢查來源**（任何一項不符就拋 `ValueError`，不寫任何檔案）：`HW1/output/metadata.json` 的 `N` 等於 `HW2/index` 的 `N`；preprocessor 是 `casefold` 與 HW2 相同、`stopword=False`、`stem=False`、`lemma` 不存在或是 False；`vocab_size` 等於 lexicon 的行數；lexicon 已排序。原因：`00-overview.md`「T1」提醒過 `main.test.py` 會把 `HW1/output` 覆蓋成 100 篇的小 index，用錯來源時建置照樣會成功，只是結果是錯的。
2. 用 `csv.reader(f, delimiter="\t")` 讀 `HW1/output/lexicon.tsv` 的前兩欄（原字、df）。
3. **算每個原字的 stem**（§8 G1 已決定：逐 token 規則，而且只能呼叫 Preprocessor 自己的程式）：先用 `Preprocessor.from_config(HW2/index 的 metadata["preprocessor"])` 建立 `pre`，再對**整個原字**呼叫 `pre.normalize_token(word)`，**不經過 `tokenize`**。回傳 `None`（stopword）時，stem 欄位記成空字串。`surface.py` 的 `surface_stem(pre, word) -> str` 只是 `pre.normalize_token(word) or ""` 的薄包裝，**不另外實作** stopword 判斷或 stem，建置與測試都用它。
   - **`tokenizer.py` 的重構**（T1 的檔案；只是把程式抽出來，行為不變）：重構前 `Preprocessor.process`（舊行號 `tokenizer.py:94-106`；重構後 `normalize_token` 在 `:94-104`、`process` 在 `:106-112`）的迴圈內容沒有可以單獨呼叫的方法，所以抽成一個新方法：
     ```python
     def normalize_token(self, tok: str) -> str | None:
         """process 對單一 token 做的步驟：casefold → stopword（回傳 None）→ lemma 或 stem（只處理 isalpha 的 token）。"""
         if self.casefold:
             tok = tok.casefold()
         if self.stopword and tok.casefold() in self.stops:
             return None
         if self.lemma and tok.isalpha():
             tok = self.lemmatizer.lemmatize(tok)
         elif self.stem and tok.isalpha():
             tok = self.stemmer.stem(tok, to_lowercase=self.casefold)
         return tok

     def process(self, text):
         res = []
         for pos, tok in enumerate(tokenize(text), start=1):
             t = self.normalize_token(tok)
             if t is not None:
                 res.append((pos, t))
         return res
     ```
     判斷順序、`tok.casefold() in self.stops` 的寫法、lemma 優先於 stem 的分支，都原封不動搬過去。`process` 的簽名、回傳格式與 position 編號（在過濾 stopword 之前編號）都不變；`from_config`、`tokenize` 不動。`indexer.py:215` 與 `parser.py` 仍然呼叫 `process`，不必改。
   - **如何證明行為不變**（寫進 `HW2/tests/t1.test.py` 新增的「`process` 重構」一節）：
     1. **golden 值**：**重構之前**，先用目前的 `process` 對一組固定的輸入產生預期值，寫成字面常數放進測試，並在重構前跑一次確認通過。重構後必須照樣通過。輸入涵蓋三種設定：HW2 的 stop+stem、HW1 的 casefold only、`casefold=False`；lemma 設定可以載入 wordnet 時另外加一組。輸入至少包含：
        - §4.2 與 §6.7 表中的 query
        - `lord of the rings`、`e-mail`、`10am`、`ID`、`cannot`、`O'Brien's`、`U.S.A.`
        - 一個 URL、`don't`、`Running RUNS ran`、`Café`、只有 stopword 的字串、空字串
     2. **組合關係**：對同一組輸入，`pre.process(text) == [(p, n) for p, t in enumerate(tokenize(text), 1) if (n := pre.normalize_token(t)) is not None]`。
     3. **`process` 確實呼叫 `normalize_token`**：用 `unittest.mock.patch.object` 包住實例的 `normalize_token` 計數，呼叫次數必須等於 `len(tokenize(text))`，證明 `process` 沒有保留另一份副本。
     4. 原有的 15 項照樣全過；`t1_bonus`、`t2`、`t3` 與 `t4` 系列也照樣全過。

     第 3 項在重構前一定會失敗，因為 `normalize_token` 還不存在；第 1 項在重構前後都必須通過。兩者的狀態分別記在 §9。
   - 不必重建 index：`process` 的輸出不變，所以 `HW2/index` 仍然有效。上面的 golden 值與 §6.8.8 第 7 節的一致性檢查共同保證這一點。
   - **為什麼不直接呼叫 `pre.process(word)`**：原字本來就是 `tokenize` 的輸出。把它拿出來單獨再 `tokenize` 一次，有時會被切開或改掉，因為 spaCy 對小寫字有特例規則。實測 644,523 個原字中有 631 個的結果和 index 不一致。

     | `pre.process(word)` 的結果 | 個數 | 例子 |
     | --- | --- | --- |
     | 變成多個 token | 285 | `100kb` → `['100', 'kb']`、`0.5mm` → `['0.5', 'mm']` |
     | 單一 token，但和原字不同 | 314 | `10am` → `['10']`、`,ltd.is` → `['ltd.is']`、`h.o.o.q` → `['hooq']`（其中 40 個不在 HW2 lexicon 中） |
     | 不是 stopword，卻變成空的 | 32 | `id`（df 1,519）、`im`、`cannot`：spaCy 會把小寫的 `id` 切成 `i` + `d`，兩個都是 stopword。但 HW2 index 裡有 `id`（df 1,579） |

     用 `process` 的話，HW2 lexicon 中有 617 個 term 找不到任何原字，`df(stem) < max(原字 df)` 有 2 例，`df(stem) > Σ 原字 df` 有 13 例。改用逐 token 的規則後，這些例外**全部是 0**（見下面的一致性檢查）。另外確認過：只要 `tokenize(word) == [word]`，兩種做法的結果完全相同，631 個差異全部來自 `tokenize` 改動了單獨的原字。逐 token 的規則跑完 644,523 個原字約 2.7 s，`process` 要 19.2 s。（這組數字是用腳本裡、和 `normalize_token` 相同的邏輯量的；正式實作改成呼叫 `normalize_token`，量測結果記在 §9。）
   - **stopword**（189 個，例如 `a`、`about`、`aren't`）：stem 欄位記**空字串**。這一列保留，原字的 df 照常記錄。展開與拼字建議時，stem 是空字串的原字一律略過。
   - **處理後變成多個 token 的原字**：用逐 token 的規則就**不會發生**，因為規則不經過 `tokenize`，一個原字只會得到一個 stem（或空字串）。所以 stem 欄位不需要表示多個 token 的格式。如果建置時發現 stem 含有空白或 tab（理論上不會出現），就拋 `ValueError`。
4. **一致性檢查**（建置時執行，結果寫進 meta，驗收時再檢查一次）：
   - 每個 stem 不是空字串的原字，它的 stem 都存在於 HW2 lexicon。實測**例外 0 個**
   - HW2 lexicon 的每個 term 至少對應到一個原字。實測**例外 0 個**（573,233 個 stem 全部涵蓋）
   - 補充（df 的上下界）：對每個 stem，`max(原字 df) ≤ reader.df(stem) ≤ Σ 原字 df`。實測**違反 0 個**
   - stopword 列數為 189；`pre.process(word)` 也回傳 `[]` 的有 189 個，兩者一致

   有任何例外就在 stderr 列出數量與前 20 個例子。預設把例外當成錯誤（拋 `ValueError`），因為實測是 0 個；加上 `--allow-mismatch` 才會照樣輸出，數量會記進 meta。
5. **輸出**（先寫成 `*.tmp`，再用 `os.replace` 換掉正式檔名。先換 tsv，最後才換 meta，所以 meta 存在就代表 tsv 已經完整）：
   - `HW2/index/surface_vocab.tsv`：用 `csv.writer(f, delimiter="\t", lineterminator="\n")` 寫入，開檔時加上 `newline=""`。第一列是表頭 `word	df	stem`，之後每列一個原字，順序與 HW1 lexicon 相同（已排序）。stopword 的 stem 欄位是空字串。
   - `HW2/index/surface_vocab.meta.json`：
     ```
     {"format": 1, "count": 644523, "stopword_count": 189, "N": 34786,
      "preprocessor": <HW2/index metadata["preprocessor"]>,
      "stem_rule": "per-token: casefold → stopword → stem if isalpha (no tokenize)",
      "origin": {"dir": "HW1/output", "N": 34786, "vocab_size": 644523,
                 "preprocessor": <HW1/output metadata["preprocessor"]>,
                 "lexicon.tsv": {"size", "sha256"}, "metadata.json": {"size", "sha256"}},
      "sources": {"lexicon.tsv": {"size", "sha256"}, "metadata.json": {"size", "sha256"}},
      "consistency": {"stem_not_in_index": 0, "index_term_without_word": 0, "df_bound_violations": 0},
      "created_at": "..."}
     ```
     `sources` 是 HW2/index 的檔案，格式與 `doc_norms.meta.json` 相同，用 `writer._fingerprint` 計算（唯讀呼叫，不改 `writer.py`）。`origin` 只記錄 HW1 來源的 fingerprint 供追查，查詢時不核對，因為查詢時不讀 `HW1/output`。預先量到的 fingerprint：`HW1/output/lexicon.tsv` 是 15,550,484 bytes、sha256 `fbcb18ac…`；`HW2/index/lexicon.tsv` 是 13,709,652 bytes、sha256 `db26f70a…`（與 `doc_norms.meta.json` 記錄的相同）。

**讀取 `HW2/src/surface.py`**（新增）：
- `load_surface(reader) -> SurfaceVocab`：第一次呼叫時讀 `reader.output_dir / "surface_vocab.tsv"` 與 meta，之後依 reader 快取在模組層級（`weakref.WeakKeyDictionary`，與 `spelling.py` 的做法相同）。**查詢時不讀 `HW1/output`。**
- **核對 meta**（任何一項不符就拋 `ValueError`，訊息含欄位名稱）：`format == 1`；`N == reader.N`；`preprocessor == reader.get_metadata()["preprocessor"]`；`reader._check_sources(meta, "surface_vocab.meta.json", ("lexicon.tsv", "metadata.json"))`（唯讀呼叫既有的 helper，`writer.py` 不改）；表頭是 `["word", "df", "stem"]`；資料列數等於 `meta["count"]`。tsv 或 meta 不存在時拋 `FileNotFoundError("... run build_surface_vocab.py first")`，與 `get_norms` 的做法一致。
- `SurfaceVocab` 的內容：`words: list[str]`（已排序）、`dfs: array('I')`、`stems: list[str]`。stem 讀進來後用 HW2 lexicon 的 key 做 intern（`lexicon.get(stem) is not None` 時改用 lexicon 的字串物件），減少記憶體。另外有一個 `word → id` 的 dict。提供的方法：
  - `df(word) -> int`：原字不存在回傳 0
  - `stem(word) -> str | None`：原字不存在回傳 `None`
  - `stem_of_any(word) -> str`：對不在詞彙中的字，用 `surface_stem`（也就是 `pre.normalize_token`）現算。`pre` 在 `load_surface` 時由 `Preprocessor.from_config(reader.get_metadata()["preprocessor"])` 建立一次
  - 延遲建立的 `kgram()`（§6.8.2）、`soundex_groups()`（§6.8.5）。**整個專案只有這一份 Soundex 對照表**（§8 G6），`SOUNDEX()` 與 `suggest_soundex` 共用
- `surface.py` 從 `spelling.py` 搬來 `_bigrams`（改名 `bigrams`），`spelling.py` 改成 import 它；`soundex` 仍留在 `spelling.py`，`soundex_groups()` 在函式內才 import，避免循環 import。

#### 6.8.2 原字的 k-gram index（拼字與 wildcard 共用）
- 結構沿用 §9.2 T4b 第 11 點：bigram，前後加 `$`；`gram → array('I')`（原字 id），另存每個原字的 bigram 數（`array('H')`）供 Jaccard 使用。建在 644,523 個原字上，第一次需要時才建立，之後依 reader 快取。
- 預先量測（直接用記憶體中的 list 建置，**不含**讀 tsv 的時間）：建置 1.05 s（不開 tracemalloc），開 tracemalloc 時 4.69 s，建置後占用 32.1 MiB（峰值 33.0 MiB）。讀 tsv 與核對 sha256 的時間實作時再量。
- **舊的、建在 stem 詞彙上的 k-gram index 刪除**（`_kgram_index`、`_kgram_cache`）。理由：
  - 它唯一的使用者是 `suggest`，而 `suggest` 改成在原字上比對
  - wildcard 從來沒有用過它
  - 兩套同時存在，記憶體會變兩倍（約 29 + 32 MiB），第一次查詢也要建兩次
  - 「建議 stem 形式」正是這次要修正的問題

  `_osa`、`JACCARD_MIN` 留在 `spelling.py`。

#### 6.8.3 拼字更正改在原字上比對（`suggest`，取代 §6.5 的候選與觸發條件）
- **接口**：簽名不變，仍是 `suggest(word, reader, limit=5) -> list[str]`，但參數與回傳值的意義改變：
  - **輸入**是使用者輸入的原字（只做 `tokenize` + casefold，不濾 stopword、不做 stem），例如 `retreival`，不再是 `retreiv`
  - **回傳**原字，例如 `retrieval`
- **候選與排序**：
  1. 用原字的 k-gram index 計算 Jaccard，≥ 0.3 的成為候選（門檻與 §6.5 相同）
  2. 排除輸入本身、stem 是空字串的原字（stopword），以及 **stem 與輸入的 stem 相同**的原字。後者改的話 query 不會有任何變化，例如 `retreival` 的候選 `retreived`、`retreives`、`retreiver` 都 stem 成 `retreiv`。輸入的 stem 用 `stem_of_any` 計算
  3. 依 `(Damerau-OSA 距離, -原字 df, 原字)` 排序
  4. **依 stem 去重**：同一個 stem 只保留第 3 步排序中最前面的原字，也就是 **OSA 距離最小**的那個；距離相同時才比原字 df。**不是**保留 df 最高的原字（這點與 `suggest_soundex` 不同，後者只依 df 排序）。去重後取前 `limit` 個。
     - `retreival` 的候選 `retrieval`（OSA 1，df 81）與 `retrieved`（OSA 較大，df 140）的 stem 都是 `retriev`，保留 **`retrieval`**。如果改成依 df 保留，就會顯示 `retrieved`，這是錯的
     - `computr` 的候選 `computer`、`compute`、`comput` 的 OSA 都是 1，stem 都是 `comput`，距離相同時比 df，保留 `computer`（5,223）
- **查 index**：如果要改用建議的原字重新查詢，用 `load_surface(reader).stem(s)` 取 stem，也就是建置時由 Preprocessor 的逐 token 步驟算出的結果。**顯示給使用者的是原字**（`retreival` → `retrieval`）。
- **觸發條件**（取代 §6.5 與 §4.4 D6 中以 stem df 判斷的版本）：令 `s = suggest(word, reader)`、`sv = load_surface(reader)`。條件是 `s` 非空，**而且** `sv.df(word) == 0` 或 `sv.df(s[0]) >= sv.df(word) * 10`。兩邊比的都是**原字的 df**，不再用 `reader.df`。顯示 `s[:3]`。
- **T7 怎麼取得使用者的原字**（建議）：在 `parser.py` 新增 `query_words(query, pre) -> list[str]`：
  - 用 `_lex` 取出 `WORD`、`PHRASE` 內文與 Near 兩側的文字，切法和 `parse` 相同
  - 跑 `tokenize` 與 casefold；略過 stopword（stopword 會被 `process` 濾掉，不參與檢索）
  - 依出現順序去重
  - 不包含 Wildcard 與 `SOUNDEX(...)` 的參數；不檢查語法（`parse` 已經先檢查過）

  另外在 `spelling.py` 新增 `did_you_mean(word, reader, show=3) -> list[str]`，把上面的觸發條件包起來：觸發時回傳 `s[:show]`，否則回傳 `[]`。T7 只要呼叫它即可，不必知道原字 df 從哪裡來。（§8 G4 已決定。）
- **預先量測**（原字 df；括號內是 df 與 stem）：

  | 輸入（原字 df） | 前幾名 | 是否觸發 |
  | --- | --- | --- |
  | `retreival`（1，stem `retreiv`） | `retrieval`（81，`retriev`）、`retrial`（2）、`retreat`（178）、`revival`（88）、`pretrial`（11） | 是（81 ≥ 10） |
  | `retrieval`（81） | `retreival`（1）、`retrial`、`retrievr`、`medieval`（222）、`retreat` | 否（1 < 810） |
  | `linux`（997） | `linus`（28，`linu`）、`linqx`、`linuq`、`lieux`、`linx` | 否（28 < 9,970） |
  | `kernal`（2） | `kernel`（266） | 是 |
  | `computr`（0） | `computer`（5,223）、`computo`、`computar`、`computor`、`compete` | 是（df == 0） |
  | `recieve`（40）、`goverment`（53）、`informaton`（2） | `receive`（4,456）、`government`（2,605）、`information`（11,168） | 都觸發 |

  單次 `suggest`（k-gram 已建好、還沒套用去重的版本）約 12–54 ms。已知的副作用：`linus`（28）是正確的人名，它的第一名是 `links`（9,251），會觸發 Did you mean。`teh` 的正解 `the` 是 stopword，會被排除；而且短字的對調讓 bigram Jaccard 只有 1/7，本來就篩不進候選。兩者都寫進 §10.4。

#### 6.8.4 Wildcard 支援任意位置的 `*`（取代 §6.4 的展開方式）
- **AST**：`Wildcard(prefix: str)` 改成 **`Wildcard(pattern: str)`**。pattern 是 lexer 切出來的整個 token 經過 casefold、把連續的 `*` 合併成一個之後的字串，**包含 `*`**：`Comput*` → `Wildcard('comput*')`、`CO*TION` → `Wildcard('co*tion')`、`co**tion` → `Wildcard('co*tion')`。不做 stem，也不經過 `tokenize`，pattern 直接拿去比對原字。
- **lexer**（`_lex` 的分類順序：PHRASE → 括號 → 運算子 → `SOUNDEX`（§6.8.5）→ NEAR → WILDCARD → WORD）：token **含有** `*`（任何位置、任意數量）就是 `WILDCARD`，不再只看結尾。`_TOKEN_RE` 不變。合併 `*` 之後如果只剩 `*`（`*`、`**`）就拋 `ValueError`，訊息含字元位置；訊息改成 `wildcard without any fixed text '*' at position N`。`/5*` 不符合 `/\d+`，所以是 WILDCARD，固定片段是 `/5`。
- **展開**：
  1. 用 `*` 切出 pattern 的固定片段。第一段前面加 `$`，最後一段後面加 `$`，取所有片段的 bigram 聯集。例：`co*tion` → `$c`、`co`、`ti`、`io`、`on`、`n$`；`*mon` → `mo`、`on`、`n$`。
  2. 從最短的 posting 開始，對原字 k-gram index 取交集，交集變空就提早結束。**沒有任何 bigram 時**（例如 `*x*`、`*q*z*`，片段都只有 1 個字元、又沒有邊界），候選就是全部原字（掃過 644,523 個原字，預先量到 47–78 ms）。
  3. **post-filter**：用 `re.fullmatch` 比對完整的 pattern，regex 是把每個片段 `re.escape` 後用 `.*` 接起來（`re.S`）。k-gram 只是篩選，一定要靠 post-filter 才能排除像 `ab*ba` 對到 `aba` 的情況。**不用 `fnmatch`**，因為它會把 `?`、`[...]` 當成萬用字元；本專案只有 `*` 是萬用字元。
  4. 比對到的原字轉成 stem，略過空字串（stopword），**去重**。
  5. 排序與截斷沿用 §6.4：依 `(-reader.df(stem), stem)` 排序，取前 `limit` 個（預設 100），組成 `Or([Term([t]) ...])`；只有 1 個時是 `Term`；0 個時移除並警告，整棵樹變空時回傳 `None`。**警告中的總數是去重後的 stem 數**，所以 `a*` 的警告仍是 `wildcard a* matched 31236 terms; using the top 100 by df`（訊息格式改成 `wildcard {pattern} ...`，pattern 本身已含 `*`）。
- **語意上的改變**：
  - `computing*` 現在會對到原字 `computing`，展開成 `T(['comput'])`，不再是 `None`
  - `computers*` 對到 7 個原字，得到 6 個 stem：`comput`、`computerspiel`、`computershar`、`computers`、`computersimulationen`、`computerspieleforum.de`
  - 只有結尾 `*` 的 pattern，如果 prefix 本身就是 stem 的前綴，結果和舊做法相同：`comput*` 64 個、`a*` 31,236 個、`lin*` 629 個、`x*` 2,543 個、`z*` 3,672 個、`retriev*` 3 個，集合與 `prefix_terms` 完全一樣，第一名也一樣（`comput`、`also`）。prefix 超出 stem 的部分時，結果會比舊做法多（`computi*` 會包含 `comput`）
- **預先量測**（k-gram 篩選 + post-filter，與暴力的 `fnmatchcase` 掃描再轉成 stem 的結果都完全相同）：

  | pattern | 候選 | 對到的原字 | 去重後的 stem | 前幾名 | 時間 |
  | --- | --- | --- | --- | --- | --- |
  | `*mon` | 609 | 276 | 276 | `common`、`mon`、`simon`、`lemon`、`solomon` | 第一次 478 ms（含暖身），之後未量 |
  | `co*tion` | 579 | 535 | 528 | `commun`、`comput`、`complet`、`content`、`condit` | 9.9 ms |
  | `*tion*` | 9,050 | 8,794 | 7,482 | `inform`、`commun`、`person`、`reserv`、`gener` | 17.3 ms |
  | `computers*` | 7 | 7 | 6 | `comput` 第一 | 9.2 ms |
  | `ab*ba` | 91 | 3 | 3 | `abba`、`ababa`、`abeba` | 3.7 ms |
  | `*x*`（沒有 bigram） | 644,523 | 23,734 | 22,129 | `next`、`text`、`experi` | 78 ms |
  | `e-mail*` | 0 | 0 | 0 | — | 1.1 ms |

  暴力掃描（`fnmatchcase` 掃過全部原字）每個 pattern 需要 82–146 ms。`*mon` 的 478 ms 是第一次呼叫，含 regex 編譯與暖身；用純 regex 全掃同一個 pattern 是 55 ms，實作後再量 k-gram 版本暖身後的時間。
- `expand` 不修改傳入的樹、先深拷貝、展開後再跑一次 `_prune`，這些都沿用 §6.4 與 §9.2 T4b 第 7 點。樹中有 Wildcard 或 Soundex 時才呼叫 `load_surface`；沒有時 `expand` 仍原樣回傳同一個物件，不讀任何檔案（T4a 的行為）。
- **`prefix_terms` 不再被 T4 使用**。它仍是 T1 的公開接口，`t1_bonus` 也還在測它，所以保留不動。

#### 6.8.5 `SOUNDEX(x)` 運算子
- **AST**：新增 `Soundex(word: str)`，`word` 只做 casefold（不濾 stopword、不做 stem）。`Node = Term | Phrase | Near | Wildcard | Soundex | Not | And | Or`。
- **lexer 規則**：只有當 token 的文字**恰好是大寫的 `SOUNDEX`**，而且**緊接在後面的字元是 `(`**（`query[m.end()] == "("`，中間沒有空白）時，kind 才是 `SOUNDEX`。`_TOKEN_RE` 不必改，因為它本來就會把 `SOUNDEX(robert)` 切成 `SOUNDEX`、`(`、`robert`、`)`。其他寫法一律照一般規則處理：

  | 輸入 | 結果 |
  | --- | --- |
  | `SOUNDEX(robert)`、`SOUNDEX(Robert)` | `Soundex('robert')` |
  | `SOUNDEX (robert)`（有空白） | `WORD` + 括號 → `And([T(['soundex']), T(['robert'])])` |
  | `soundex(robert)`、`Soundex(robert)` | 同上：小寫或大小寫混合不是運算子 |
  | `SOUNDEX`、`SOUNDEX robert`、`SOUNDEXES(x)` | 一般的 `WORD` |
  | `linux SOUNDEX(robert)` | 隱含 AND：`_UNARY_START` 要加入 `SOUNDEX` |

- **parser**：`parse_primary` 遇到 `SOUNDEX` 時，吃掉 `SOUNDEX` 與 `(`，接著**必須恰好是一個 `WORD` 再接 `)`**。以下情況拋 `ValueError`，訊息含字元位置（從 0 起算）：

  | 情況 | 例子 | 位置 |
  | --- | --- | --- |
  | 沒有 `)` | `SOUNDEX(robert` | 該 `(`，即 7。沿用 `unmatched '(' at position N` |
  | 括號內是空的 | `SOUNDEX()` | `SOUNDEX` 本身，即 0。訊息 `SOUNDEX() needs exactly one word at position N` |
  | 括號內不只一個 WORD | `SOUNDEX(robert smith)` | 同上 |
  | 括號內是其他 token（PHRASE、WILDCARD、NEAR、運算子、`(`、另一個 `SOUNDEX`） | `SOUNDEX("robert")`、`SOUNDEX(rob*)`、`SOUNDEX(NOT x)` | 同上 |
  | 單字中沒有任何 ASCII 字母 | `SOUNDEX(123)`、`SOUNDEX(李)` | 同上。訊息 `SOUNDEX() needs a word with ASCII letters at position N` |

  `SOUNDEX(o'brien)` 這類含有非字母字元的單字是合法的：`soundex()` 本來就會略過非字母字元（§9.2 T4b 第 11 點），所以等於 `O165`。
- **其他規則**：
  - `Soundex` 不能當 Near 的一側。`SOUNDEX(robert) /5 kernel` 依 §9.2 T4b 第 3 點，NEAR 的左側是空的，退化成 `T(['kernel'])` 並警告；`Soundex` 本身以隱含 AND 保留
  - `_prune` 原樣保留 `Soundex`
  - `query_terms` 遇到 `Soundex` 拋 `ValueError`，與 Wildcard 相同
  - `_contains_wildcard` 改名為 `_needs_expand`，同時涵蓋 Wildcard 與 Soundex
- **expand**：
  1. 用 `code = soundex(word)` 查 `SurfaceVocab.soundex_groups()`：只收 `isascii() and isalpha()` 的原字（與 `suggest_soundex` 的條件相同），依 Soundex 碼分組，第一次使用時建立並快取
  2. 同碼的**所有**原字轉成 stem，略過空字串，去重，**包含輸入的字本身**
  3. 排序、`limit`、警告與 0 個時的移除規則都與 wildcard 相同；警告訊息是 `SOUNDEX(robert) matched 214 terms; using the top 100 by df`
- **預先量測**：原字詞彙中共有 6,361 種 Soundex 碼，最大的一組有 1,240 個原字。實際存在、而且同碼的例子（括號內是原字 df）：

  | 碼 | 原字 |
  | --- | --- |
  | R163 | `robert`（1,242）／`rupert`（43） |
  | S530 | `smith`（1,406）／`smyth`（8） |
  | J525 | `johnson`（783）／`jonson`（9） |
  | S315 | `stephen`（572）／`steven`（443） |
  | M600 | `meyer`（163）／`mayer`（357） |
  | A261 | `ashcraft`（2）／`ashcroft`（10） |

  `R163` 有 268 個原字，去重後是 214 個 stem。依 stem df 排序：`report`（6,843）、`refer`（3,474）、`robert`（1,385）、`repair`、`reproduc`……；`robert` 排第 3，`rupert` 排第 20，都在前 100 個內。所以 `SOUNDEX(robert)` 的結果會被 `report`、`refer` 這類高 df 的一般詞主導。這正是 Soundex 不適合一般檢索的例子，要寫進 §10.4。反例（同音卻不同碼）：`catherine` C365 與 `kathryn` K365（第一個字母不同）、`thompson` T512 與 `thomson` T525、`lee` L000 與 `leigh` L200。
- **`suggest_soundex` 改用原字詞彙**（§8 G6 已決定）：
  - **只維護一份 Soundex 對照表**：`SurfaceVocab.soundex_groups()`。刪除 `spelling.py` 的 `_soundex_table` 與 `_soundex_cache`（stem 詞彙的那份）
  - **接口**：簽名不變，仍是 `suggest_soundex(word, reader, limit=5) -> list[str]`。和 `suggest` 一樣，**輸入是原字**（例如 `retreival`），**回傳原字**
  - **排序不改善**：仍然只依 df 排序，改用原字 df，鍵是 `(-原字 df, 原字)`。不考慮距離，也不考慮像不像
  - **過濾與去重**：
    1. 排除輸入本身、stem 是空字串的原字（stopword），以及 stem 與輸入相同的原字（規則同 G3）
    2. **依 stem 去重**，每個 stem 只保留排序最前面的原字（也就是原字 df 最高的那個）
    3. 取前 `limit` 個
  - 仍然只收 `isascii() and isalpha()` 的原字（建表時就篩掉），`soundex()` 本身不改
  - **預先量測**（括號內是原字 df 與 stem）：

    | 輸入 | 碼 | 前 5 名 |
    | --- | --- | --- |
    | `retreival` | R361 | `retrieved`（140，`retriev`）、`rutherford`（50）、`retroberry`（24）、`retribution`（21）、`retrouver`（15） |
    | `robert` | R163 | `report`（4,278）、`referred`（496，`refer`）、`reproduced`（310）、`reproduction`（167）、`roberto`（137） |
    | `smith` | S530 | `send`、`sunday`、`sound`、`sent`、`santa` |

    `retrieval`（81）與 `retrieved`（140）的 stem 都是 `retriev`，去重後只留下 df 較高的 `retrieved`。原字詞彙的對照表建置約 0.44 s，和舊的 stem 版（0.46 s）差不多。
  - 碰撞的情況和 stem 版一樣多，甚至更明顯：`robert` 的前幾名全是一般詞。這只是輔助功能，限制寫在 §10.4。

#### 6.8.6 對其他 task 的影響
- **T1**：因為 §8 G1，`tokenizer.py` 要做一次**行為不變**的重構：抽出 `Preprocessor.normalize_token`，`process` 改成呼叫它（§6.8.1 第 3 步）。`t1.test.py` 新增「`process` 重構」一節，用 golden 值、組合關係與呼叫計數證明行為不變。index 不必重建，T1 的其他接口（`from_config`、`IndexReader` 全部）不變。這是 T4c 對 T1 檔案唯一的改動，要記進 `done.T1.md` 的實作紀錄（見下方「`done.T1.md` 需要改的句子」）。
- **T2、T3 的程式碼不變**：`writer.py`、`weighting.py`、`build_norms.py`、`build_champions.py` 都不改。`writer._fingerprint` 與 `IndexReader._check_sources` 只是唯讀呼叫。`prefix_terms` 保留。`t1_bonus`、`t2`、`t3` 系列的測試不改，應該照樣全過。
- **T5**：`evaluate` 收到的樹一定已經 expand 過，不會出現 `Wildcard` 或 `Soundex`。`boolean.py` 不改；總規劃 T5 的註解要把 Soundex 也列進「遇到就拋 `ValueError`」（§9.3 F5）。
- **T6**：沒有影響。`query_terms` 的輸入同樣已經 expand 過。
- **T7**：
  - 拼字建議改用原字（`query_words` + `did_you_mean`）
  - 畫面上不必再說明「建議是 stem 形式」
  - `expand` 在 `surface_vocab.*` 不存在時拋 `FileNotFoundError`、meta 不符時拋 `ValueError`，T7 要印出訊息、以非 0 結束
  - 第一次使用 wildcard、SOUNDEX 或拼字建議時，要付讀 tsv 與建 k-gram 的成本（k-gram 約 1 s，讀檔時間待量）
- **繳交**（§8 G8 已決定）：zip **附上** `surface_vocab.tsv` 與 `surface_vocab.meta.json`，因為 TA 手上不一定有 `HW1/output`（未 stem 的 index），沒辦法自己重建。README 仍寫出重建指令與前提（需要 `HW1/output`），供組員使用。
- 需要回寫 `00-overview.md` 的項目，以及因為這次修改要更新的 E1–E6，都記在 §9.3（F1–F12）。
- **`done.T1.md` 需要改的句子**（前三項已改，第四項等實作後回寫，見 §9.3）：
  - §10.1 第 3 點：「……不必另外建結構，就能當作 wildcard（T4b）的基礎。」改成：「……不必另外建結構。T4b 最初的 wildcard 用它做 prefix 展開；T4 §6.8 之後，wildcard 改在原字詞彙的 k-gram index 上展開，不再呼叫 `prefix_terms`，但它仍是 T1 的公開接口（`t1_bonus` 有測試）。」
  - §6.1 第 74 行的評分面向「query 多樣性（wildcard 的基礎）」：改成「query 多樣性（T4b 最初的 wildcard 使用；§6.8 後改用原字 k-gram）」
  - §10.4 第 4 點「prefix 是對 stem 後的 dictionary 比對……`computing*` 對不到 `comput`（T4b 的已知限制……）」：補上「T4 §6.8 改在原字上比對後，`computing*` 會展開成 `comput`，這個限制已解除；`prefix_terms` 本身的行為不變」
  - §9（實作紀錄）新增一點：「T4c 在 `tokenizer.py` 抽出 `Preprocessor.normalize_token`，`process` 改成呼叫它，行為不變（`t1.test.py` 的 golden 值與呼叫計數證明）；`indexer.py` 不必改，index 不必重建」。另外，§3／§4 中 `process` 的行號（`tokenizer.py:94-106`）已改變：實作後 `normalize_token` 是 `:94-104`、`process` 是 `:106-112`、`from_config` 是 `:113-130`（已回寫 §2 與 `done.T1.md`）

#### 6.8.7 改動範圍
| 檔案 | 改動 |
| --- | --- |
| `HW2/src/build_surface_vocab.py` | 新增：建置腳本（§6.8.1） |
| `HW2/src/surface.py` | 新增：`surface_stem`、`load_surface`、`SurfaceVocab`（df、stem、k-gram、Soundex 分組、wildcard 比對）、`bigrams` |
| `HW2/src/parser.py` | `Wildcard(pattern)`；新增 `Soundex`、`Node` 加入 `Soundex`；`_lex` 的 WILDCARD 與 SOUNDEX 規則；`_UNARY_START` 加入 `SOUNDEX`；`parse_primary`；`_needs_expand`；`_expand_node` 的 Wildcard／Soundex 分支；`query_terms` 的 Soundex 分支；新增 `query_words`；更新 docstring |
| `HW2/src/spelling.py` | `suggest` 改在原字上比對；刪除 stem 的 k-gram index；`_bigrams` 移到 `surface.py`；新增 `did_you_mean`；`suggest_soundex` 改用原字詞彙的對照表，依 stem 去重、回傳原字（G6）；刪除 `_soundex_table`、`_soundex_cache`；`soundex()` 不改；更新模組 docstring（「建議的結果是 stem 形式」那句） |
| `HW2/src/tokenizer.py` | **因 G1 新增**：抽出 `Preprocessor.normalize_token`，`process` 改成呼叫它，行為不變（§6.8.1 第 3 步）。這是 T1 的檔案 |
| `HW2/tests/t1.test.py` | **因 G1 新增**：「`process` 重構」一節（golden 值、組合關係、呼叫計數）；原有的 15 項不改 |
| `HW2/tests/t4_bonus.test.py` | 修改既有的測試（見 §6.8.8 的列表，含 G6 造成的 Soundex 測試修改），新增第 7–10 節 |
| 不改 | `writer.py`、`indexer.py`、`positional.py`、`boolean.py`、`rank.py`、`HW1/`、`HW2/tests/t4.test.py`、`t1_bonus`–`t3_bonus` 的測試檔 |

與上一版相比，G1 讓範圍多了 `tokenizer.py` 與 `t1.test.py`。G6 沒有增加新的檔案，但增加了 `spelling.py` 的改動（`suggest_soundex` 改寫、刪除 stem 的 Soundex 表），以及 `t4_bonus.test.py` 中兩項 Soundex 測試與一項計時的修改。

#### 6.8.8 驗收測試
執行方式不變：`uv run python HW2/tests/t4_bonus.test.py`。測試前要先執行一次 `uv run python HW2/src/build_surface_vocab.py`。新的測試寫在 `t4_bonus.test.py` 的第 7–10 節；預期值一律由測試內獨立的暴力做法算出，不拿被測函式的結果當預期值。

**7. 原字詞彙層與一致性**
- [x] `surface_vocab.tsv` 共 644,523 列資料加上 1 列表頭，已排序；stem 是空字串的有 189 列；meta 的 `count`、`N`、`preprocessor`、`sources` 都正確
- [x] **一致性**（測試內重新算，不信任 meta 記錄的數字）：
  - 每個 stem 不是空字串的原字，它的 stem 都 `in reader`
  - `reader.vocabulary()` 的每個 term 都至少對應到一個原字
  - `max(原字 df) ≤ reader.df(stem) ≤ Σ 原字 df`

  三項的例外都必須是 0。如果有例外，FAIL 訊息列出數量與前 10 個例子。
- [x] **與 Preprocessor 一致**：用 `random.Random(42)` 抽 5,000 個原字，加上全部 189 個 stopword。只要 `tokenize(w) == [w]`，就要滿足 `[t for _, t in pre.process(w)] == ([stem] if stem else [])`。抽到 `tokenize` 會改動的原字時跳過並計數，計數寫進訊息（全體中共有 631 個）
- [x] **meta 核對**：在 `tempfile` 目錄中用 symlink 指向 `HW2/index` 的 `lexicon.tsv`、`metadata.json`、`surface_vocab.tsv`，再放一份改過的 meta：
  - sha256 改錯、`N` 改錯 → `load_surface` 拋 `ValueError`
  - 刪掉 meta → 拋 `FileNotFoundError`

  不修改 `HW2/index` 本身。
- [x] 建置腳本的來源檢查：把 `--hw1-dir` 指向 `HW2/index`（stem=True）時拋 `ValueError`，而且不會產生任何檔案。輸出目錄用 `--index-dir` 指向 tempfile 目錄

**8. 拼字（原字）**
- [x] `s = suggest('retreival', reader)`：`s[0] == 'retrieval'`（預先量到是第一名），而且 `'retrieved' not in s`、`'retrieve' not in s`。同一個 stem `retriev` 只出現一次，代表的是 OSA 最小的 `retrieval`，不是 df 較高的 `retrieved`（140）、`retrieve`（138）
- [x] 去重規則：在去重前的排序結果中，每個 stem 第一次出現的原字，必須正好是 `s` 中代表該 stem 的原字。測試內自己寫 OSA 重算排序
- [x] 結果不含 `retreived`、`retreives`、`retreiver`（stem 與輸入相同），不含 stopword，同一個 stem 只出現一次，長度 ≤ 5，不含輸入本身
- [x] 排序：測試內自己寫 OSA，重算 `(OSA, -原字 df, 原字)`，確認去重前的順序正確
- [x] 觸發條件（原字 df，測試時重新讀出）：
  - `retreival`（1）→ `retrieval`（81），觸發
  - `linux`（997）→ `linus`（28），不觸發
  - `kernal`（2）→ `kernel`，觸發
  - `computr`（0）→ `computer`，觸發
- [x] `load_surface(reader).stem('retrieval') == 'retriev'`，而且 `'retriev' in reader`

**9. Wildcard**
- [x] lexer：`*mon`、`co*tion`、`*tion*`、`a*b*c`、`/5*` 都是 `WILDCARD`；`*`、`**`、`linux OR **` 拋 `ValueError`（位置分別是 0、0、9）
- [x] `parse('Co*TION', pre) == Wildcard('co*tion')`、`parse('co**tion', pre) == Wildcard('co*tion')`
- [x] **與暴力掃描一致**：對 `*mon`、`co*tion`、`*tion*`、`ab*ba`、`*x*`（沒有 bigram，走全掃的路徑），各做兩件事：
  - 用 `expand(..., limit=10**9)` 取得的 term 集合，要等於暴力做法的結果：在 `fnmatch.fnmatchcase(word, pattern)` 為 True 的原字中，取 stem 不是空字串的部分去重
  - 預設 `limit=100` 時，結果的順序要等於暴力結果依 `(-reader.df(s), s)` 排序後的前 100 個

  預先量到的 stem 數：276、528、7,482、3、22,129。前三個都超過 100，所以要警告 1 次，訊息含總數。測試用的 pattern 不能含 `?` 或 `[`，因為 `fnmatch` 會把它們當成萬用字元。
- [x] post-filter：`ab*ba` 對到的原字長度都 ≥ 4，例如 `aba` 不能出現。k-gram 篩出 91 個候選，最後只剩 3 個
- [x] `computers*` 的展開結果包含 `T(['comput'])`，而且是第一個；共 6 個，沒有警告
- [x] `computing*` → `T(['comput'])`，沒有警告；`linux OR computing*` → `Or([T(['linux']), T(['comput'])])`
- [x] `e-mail*` → `None`，警告 1 次；`linux OR e-mail*` → `T(['linux'])`。這兩項取代舊的 `computing*` 測試
- [x] 樹中沒有 Wildcard／Soundex 時，`expand` 不呼叫 `load_surface`（用 spy 或 monkeypatch 檢查）

**10. SOUNDEX**
- [x] `parse('SOUNDEX(Robert)', pre) == Soundex('robert')`；`parse('linux SOUNDEX(robert)', pre) == And([T(['linux']), Soundex('robert')])`
- [x] `SOUNDEX (robert)`、`soundex(robert)` → `And([T(['soundex']), T(['robert'])])`；`SOUNDEX robert` → `T(['soundex', 'robert'])`
- [x] 以下輸入拋 `ValueError`，位置如括號所示：`SOUNDEX(robert`（7）、`SOUNDEX()`（0）、`SOUNDEX(robert smith)`（0）、`SOUNDEX(rob*)`（0）、`SOUNDEX("robert")`（0）、`SOUNDEX(123)`（0）
- [x] `query_terms(Soundex('robert'))` 拋 `ValueError`
- [x] `expand(SOUNDEX(robert), limit=10**9)` 的 term 集合，要等於暴力做法的結果：在原字詞彙中，取 `isascii() and isalpha()` 且 `soundex(w) == 'R163'` 的原字，stem 不是空字串的部分去重（預先量到 214 個）。集合必須同時包含 `robert` 與 `rupert`
- [x] 預設 `limit` 時共 100 個，警告 1 次，訊息含 `214`；`robert`、`rupert` 都在結果中
- [x] 再測兩組同碼的例子：`smith`／`smyth`（S530）、`stephen`／`steven`（S315）。兩個原字都要存在於原字詞彙，而且彼此的 stem 都出現在對方的 `expand(..., limit=10**9)` 結果中
- [x] `SOUNDEX(robert) /5 kernel` → `And([Soundex('robert'), T(['kernel'])])`，警告 1 次（NEAR 左側是空的）

**回歸**
- [x] `t4.test.py` **48/48，不改任何一行**。理由：
  - 第 200 行的 `query_terms(Wildcard("comput"))` 是用位置參數建立節點，欄位改名不影響；它只檢查會不會拋 `ValueError`
  - 第 233 行 `_lex` 的 `win*` 仍是 `WILDCARD`
  - 表中沒有任何 query 含有 `*` 或 `SOUNDEX`
- [x] `t1.test.py`：原有的 15 項加上「`process` 重構」一節全部通過（§6.8.1 第 3 步）。golden 值的那幾項在重構前就要先通過
- [x] `t1_bonus`、`t2`、`t3`（含 bonus）不改測試檔，照樣全過
- [x] `t4_bonus.test.py` 中既有的測試全部通過，需要修改的地方逐一列在下表：

| 位置（目前的行號） | 測試 | 改法 | 原因 |
| --- | --- | --- | --- |
| `:112` CASES | `("Comput*", Wildcard("comput"), …)` | 改成 `Wildcard("comput*")` | 欄位改成 pattern，包含 `*` |
| `:127` EXTRA | `("comput* OR linux", Or([Wildcard("comput"), …]))` | 改成 `Wildcard("comput*")` | 同上 |
| `:208` `_comput` | `node == Wildcard("comput")` | 改成 `Wildcard("comput*")`；64 個、第一個 `comput` 不變 | 同上；集合預先確認過與舊結果相同 |
| `:220` `_comput_order` | 預期值來自 `vocabulary()` 中以 `comput` 開頭的 term | 預期值改成暴力做法：原字詞彙中 `startswith("comput")` 的原字轉成 stem 後去重，再依 `(-df, term)` 排序。數值不變 | 預期值應該來自新的路徑；舊的寫法只是剛好相等 |
| `:235` `_a_star` | 100 個、第一個 `also`、訊息含 `31236` | 不改 | 去重後的 stem 數仍是 31,236（已確認），訊息仍是 `wildcard a* …` |
| `:245` `_a_limit` | 預期值來自 `reader.prefix_terms("a")` | 建議改成原字的暴力做法，數值不變 | 同 `_comput_order` |
| `:253-260` `_computing` | `computing*` → `None` | 改成 §6.8.8 第 9 節的兩項：`computing*` → `T(['comput'])`，以及 `e-mail*` → `None` | 語意改變：`computing*` 現在對得到原字 |
| `:263-270` `_single` | `Wildcard(prefix)`，挑 `prefix_terms(t)` 只有 1 個的 prefix | 直接用 `computing*`：結果是 `T(['comput'])`；或用原字的暴力做法挑一個「只對到 1 個 stem」的 pattern。建構方式改成 `Wildcard(p + "*")` | 欄位改名；「只有 1 個」改用原字的語意判斷 |
| `:275-284` `_nested`、`:287-300` `_expand_copy`、`:303-309` `_qtf_after` | 65 個、64 個 | 不改 | `comput*` 的結果不變 |
| `:310`、`:313` timing | `Wildcard("comput")`、`Wildcard("a")` | 改成 `Wildcard("comput*")`、`Wildcard("a*")`，標籤改成原字版本 | 沒有 `*` 的 pattern 只會精確比對一個字，量到的不是同一件事 |
| `:172`、`:176` ERRORS | `*`、`linux OR **` | 不改 | 仍然拋 `ValueError`，位置相同 |
| `:494-506` k-gram 建置計時 | `spelling._kgram_cache.clear()` | 改成清除 `surface.py` 的快取，標籤改成「原字 k-gram」 | stem 的 k-gram index 已刪除 |
| `:509-516` `_retreival` | `retriev` 在前 3 名 | 改成 `suggest('retreival')[0] == 'retrieval'`，而且結果不含 `retrieved` | 回傳原字；依 stem 去重時保留 OSA 最小的原字 |
| `:519-524` `_retreiv` | `suggest('retreiv')[0] == 'retriev'` | 刪除，由第 8 節的「`stem('retrieval') == 'retriev'`」取代 | 輸入不再是 stem |
| `:527-536` `_shape` | 6 個輸入的形狀檢查 | 加上檢查「沒有重複的 stem」，輸入不變 | 新增依 stem 去重的規則 |
| `:539-561` `_sorted` | 排序鍵 `-reader.df(t)` | 改成 `-原字 df`，而且只檢查去重前的順序 | df 的來源改變 |
| `:564-569` `_vocab_untouched` | `reader.vocabulary()` 沒有被修改 | 保留，另加「原字 list 沒有被修改」 | `suggest` 不再讀 `vocabulary()`，原本的檢查會變成理所當然的通過 |
| `:572-583` `_trigger` | 用 `reader.df` 檢查 `retreiv`／`linux` | 改成第 8 節的原字 df 版本 | 觸發條件改變 |
| `:586-587` timing | `suggest` 4 個詞 | 輸入改成原字（`retreival`、`linux`、`a`、`computer`） | — |
| `:590-593` Soundex 編碼 | `soundex()` 的 8 個例子 | 不改 | `soundex()` 不改 |
| `:596-601` Soundex 對照表建置計時 | 用 `suggest_soundex("linux")` 觸發 stem 詞彙的對照表 | 改成清除 `surface.py` 的快取後再呼叫，標籤改成「原字 Soundex 對照表」 | G6：只剩原字詞彙的那份表 |
| `:606-611` `_sx_suggest` | `'retriev' in suggest_soundex('retreiv')` | 改成 `s = suggest_soundex('retreival', reader)`：`'retrieved' in s`；`'retreival' not in s`；`len(s) <= 5`；`retrieval` 不在 `s` 中（它和 `retrieved` 同 stem，被去重掉了） | G6：輸入與回傳都是原字，依 stem 去重 |
| `:614-620` `_sx_sorted` | `limit=20`，檢查 `(-reader.df, term)` 排序、碼都是 R361、純字母 | 輸入改成 `retreival`。檢查以下各項：<br>• 排序鍵是 `(-原字 df, 原字)`<br>• 每個結果的碼都是 R361，而且 `isascii() and isalpha()`<br>• stem 兩兩不同<br>• 沒有 stem 是空字串的原字<br>• 沒有和輸入同 stem（`retreiv`）的原字 | G6 |
| `:621` timing | `suggest_soundex('retreiv')` | 改成 `suggest_soundex('retreival')` | 同上 |

G6 另外在第 10 節加一項：`SOUNDEX()` 與 `suggest_soundex` 用的是**同一個**對照表物件（兩次呼叫 `load_surface(reader).soundex_groups()` 會回傳同一個物件，用 `is` 檢查），而且 `spelling` 模組中不再有 `_soundex_table`／`_soundex_cache`。

- [x] **計時**（寫進 §9.1，不設門檻）：
  - `load_surface`（讀 tsv、核對 sha256）的時間與記憶體
  - 原字 k-gram index 的建置
  - `suggest`（原字）
  - `expand(*mon)`、`expand(*tion*)`、`expand(*x*)`（全掃）、`expand(a*)`
  - Soundex 原字對照表的建置（只有一份）、`expand(SOUNDEX(robert))`、`suggest_soundex('retreival')`
  - `build_surface_vocab.py` 的總時間（其中 `normalize_token` 跑完 644,523 個原字的時間）

## 7. 不做的事
- 不在 parser 裡檢查 df（不在 dictionary 中的詞由 T6 略過，由 T7 顯示建議）
- ~~不做 wildcard 的中間或前綴萬用字元（`*comp`、`co*ut`）~~：§6.8.4 改成要做
- 不自動替換拼字，只提供建議（§6.8 也一樣）
- wildcard 不支援 `?`、`[...]`，只有 `*` 是萬用字元（§6.8.4）
- 不動 `HW1/`，也不改 `writer.py`、`boolean.py`。`tokenizer.py` 在 T4a／T4b 都沒有改；§6.8 只會抽出 `normalize_token`，行為不變（§8 G1）。§6.8 會**讀** `HW1/output`，但只在建置 `surface_vocab.*` 時讀；查詢時不讀

## 8. 待決問題
T4 範圍內沒有待決問題；純 NOT 的輸出方式交由 T6／T7 決定：
- **已決定**：只有一個遞迴下降 parser，接口是 `parse(query, pre)`，沒有 `extended` 參數。T4a／T4b 只是實作順序與 commit 切分。
- **已決定**：沒加引號的多詞運算元（`open source`）是 `Term`，代表隱含 AND；要做 phrase 就用引號，對應 `Phrase` 節點。
- **已決定**：空節點規則在樹上處理，所以 `linux OR the AND kernel` 會得到 `Or`。
- **已決定**：拼字建議在「原詞的 df == 0，或最佳建議的 df ≥ 原詞 df × 10」時觸發，T7 顯示前 3 個建議。
- **已決定**：`expand` 的 `limit` 預設為 100。
- **已決定**：`Near(left: Phrase, right: Phrase, k)`，單一 token 是長度 1 的 Phrase；距離是兩段位置區間之間的間隔，不分先後，含 stopword 空洞；Near 一側多個 token 不再拋錯。
- 純 NOT 的 query（沒有任何評分 term）：輸出方式由 T6／T7 負責人決定。T4 只保證 `query_terms` 回傳空的 `Counter()`。
- **已決定**：`expand` 回傳 `None` 時與 `parse` 回傳 `None` 相同，直接輸出空結果（§4.4 D1，已回寫總規劃「查詢流程」）。

§6.8（T4c）的決定：
- **已決定 G1**：原字的 stem 用**逐 token 規則**算，不經過 `tokenize`。理由是一致性例外 0 個；直接用 `pre.process(word)` 的話，有 631 個原字不一致，617 個 index term 找不到原字。stopword 判斷與 stem **必須呼叫 Preprocessor 內部的同一段程式，不能另外實作一份**：
  - 在 `tokenizer.py` 抽出 `Preprocessor.normalize_token(tok) -> str | None`，`process` 改成呼叫它，行為不變
  - `surface_stem` 只是 `pre.normalize_token(word) or ""`
  - `t1.test.py` 用 golden 值、組合關係與呼叫計數證明行為不變（§6.8.1 第 3 步）
- **已決定 G2**：stopword 列（189 個）保留在 `surface_vocab.tsv` 中，stem 欄位記空字串，原字的 df 照常記錄。展開、拼字建議與 Soundex 都會略過 stem 是空字串的原字。
- **已決定 G3**：`suggest` 排除輸入本身、stopword，以及 stem 與輸入相同的候選；依 `(OSA, -原字 df, 原字)` 排序後，依 stem 去重，每個 stem 只保留排序最前面的原字，也就是 OSA 最小的那個（距離相同時才比 df），不是 df 最高的。例如 `retreival` 顯示 `retrieval`，不顯示 `retrieved`（§6.8.3）。
- **已決定 G4**：新增 `parser.query_words(query, pre) -> list[str]`，取出使用者輸入的原字（只做 `tokenize` 與 casefold，略過 stopword、Wildcard 與 `SOUNDEX()` 的參數，依出現順序去重）。另外新增 `spelling.did_you_mean(word, reader, show=3) -> list[str]`，把以原字 df 判斷的觸發條件包起來。T7 只呼叫這兩個函式（§6.8.3）。
- **已決定 G5**：`SOUNDEX()` 的參數中沒有任何 ASCII 字母時（`SOUNDEX(123)`），`parse` 拋 `ValueError`，訊息含字元位置；不留到 `expand` 才處理（§6.8.5）。
- **已決定 G6**：`suggest_soundex` 也改用原字詞彙，**只維護一份 Soundex 對照表**（`SurfaceVocab.soundex_groups()`，`SOUNDEX()` 也用它），刪除 stem 詞彙的 `_soundex_table`。簽名不變，輸入與回傳都是原字；排序仍只看 df（`(-原字 df, 原字)`），不做改善；回傳前排除輸入本身、stopword 與同 stem 的原字，並依 stem 去重，每個 stem 只顯示 df 最高的原字（§6.8.5）。
- **已決定 G7**：一致性檢查（stem 不在 index、index term 沒有原字、df 上下界）只要有任何例外，`build_surface_vocab.py` **預設失敗**：拋 `ValueError`，不寫任何檔案，並在 stderr 列出數量與前 20 個例子。只有加上 `--allow-mismatch` 時才照樣輸出，例外數量記進 meta（§6.8.1 第 4 步）。
- **已決定 G8**：繳交的 zip **附上** `surface_vocab.tsv` 與 `surface_vocab.meta.json`，因為 TA 不一定有 `HW1/output`，無法重建。大小在實作時量測並記進 §9；可參考 `HW1/output/lexicon.tsv` 的 15.6 MB。README 仍寫出重建指令與前提，供組員使用（§6.8.6）。

## 9. 實作紀錄

### 9.1 結果
**核心（T4a）、加分（T4b）與 T4c（§6.8）都已完成。** T4c 的紀錄在 §9.1.3（資料層）與 §9.1.4（拼字、wildcard、SOUNDEX）。以下是 T4a／T4b 當時的紀錄：核心改動 `HW2/src/parser.py` 並新增 `HW2/tests/t4.test.py`；加分改動 `parser.py`、`positional.py`、`spelling.py`，並新增 `HW2/tests/t4_bonus.test.py`。`writer.py`、`tokenizer.py`、`boolean.py`、`rank.py`、`HW1/`、`HW2/index/` 都沒有動；接口簽名與 AST dataclass 沒有改。

#### 9.1.1 核心（T4a）

| 測試 | stub 狀態 | 實作後 |
| --- | --- | --- |
| `t4.test.py`（核心） | 1/48 通過（唯一通過的是「表中 token 都在 dictionary」，它只用預期值，不呼叫 `parse`）；其餘 47 項都是 `NotImplementedError` | **48/48** |
| `t1.test.py` ／ `t1_bonus.test.py` | — | 15/15 ／ 11/11 |
| `t2.test.py` ／ `t2_bonus.test.py` | — | 19/19 ／ 37/37 |
| `t3.test.py` ／ `t3_bonus.test.py` | — | 17/17 ／ 25/25 |

`t4.test.py` 的 48 項：§4.2 表 21 列的 AST 與警告次數（21 項）、有 AST 的 17 列的 `query_terms`（17 項）、dictionary 檢查、`expand` 原樣回傳／`expand(None)`／不修改原樹（3 項）、`query_terms` 手建節點的 4 個分支、`parse` 不讀 index、`_lex` 的 token 分類（共 48）。警告計數都在 `catch_warnings(record=True)` 內先 `simplefilter("always")`。

實作位置（`parser.py`）：`_lex` 第 74 行（regex `_TOKEN_RE` 第 67 行）、`_Parser` 第 120 行、`_prune` 第 179 行、`_contains_wildcard` 第 217 行、`parse` 第 227 行、`expand` 第 247 行、`query_terms` 第 260 行。

加分語法在核心中的行為（用一次性腳本確認，未寫進 `t4.test.py`，見 §9.2 第 5 點）：`NOT linux`、`linux NOT windows`、`(linux)`、`linux)`、`"open source"`、`linux "x"`、`comput*`、`*`、`linux /5 kernel`、`linux AND (kernel`、`"open source AND linux` 都拋 `NotImplementedError("T4b: <語法> not implemented yet ('<token>' at position <pos>)")`；`expand` 遇到含 `Wildcard` 的樹拋 `NotImplementedError("T4b: wildcard expansion is not supported yet")`。

（以上是 T4a 當時的行為；T4b 已把這些 `NotImplementedError` 全部換成實作或 `ValueError`，`parser.py` 中已沒有 `T4b:` 字樣。）

#### 9.1.2 加分（T4b）
| 測試 | stub 狀態 | 實作後 |
| --- | --- | --- |
| `t4_bonus.test.py`（加分） | 2/96 通過（「表中 token 都在 dictionary」與「vocabulary 沒被修改」只檢查預期值或 reader 本身）；其餘都是 `NotImplementedError` | **99/99**（stub 之後補了 3 個 phrase 對照，見 §9.2 T4b 第 12 點） |
| `t4.test.py`（核心回歸） | — | **48/48** |
| `t1` ／ `t1_bonus` | — | 15/15 ／ 11/11 |
| `t2` ／ `t2_bonus` | — | 19/19 ／ 37/37 |
| `t3` ／ `t3_bonus` | — | 17/17 ／ 25/25 |

`t4_bonus.test.py` 的 99 項：§6.7 表 15 列加上 9 列補充（缺少運算元、Near 退化、括號前的隱含 AND、`NOT NOT`、多 token 的 Near 兩側）的 AST 與警告次數（24 項）、其中 20 列有 AST 的 `query_terms`（含兩列 Wildcard 拋 `ValueError`）、dictionary 檢查（共 45）；`ValueError` 9 種（含位置）與 `e-mail /5 server` 不拋錯（10）；`expand` 9 項；`position_match` 19 項（10 個 query 與暴力掃描對照、27 篇自我檢查、doc 1400、反方向、子集、對稱、極大 k、重疊、不在 dictionary 的 term、`get_postings` 呼叫次數）；`suggest` 6 項；Soundex 10 項（共 99）。

實作位置：
- `parser.py`：`_UNARY_START` 第 105 行、`_Parser` 第 109 行（`parse_unary` 第 148 行、`parse_primary` 第 154 行、`parse_side` 第 186 行）、`_prune` 第 225 行、`parse` 第 295 行、`expand` 第 316 行（`_expand_node` 第 330 行）、`query_terms` 第 359 行。dataclass 內容沒改，但因為多 import 了 `copy`，又往下移 1 行（`Term` `:22-24`、`Phrase` `:27-30`、`Near` `:33-37`、`Wildcard` `:40-42`、`Not` `:45-47`、`And` `:50-52`、`Or` `:55-57`、`Node` `:60`）
- `positional.py`：`position_match` 第 15 行、`_load_positions` 第 53 行、`_phrase_intervals` 第 75 行、`_near_hit` 第 95 行
- `spelling.py`：`_kgram_index` 第 31 行、`_osa` 第 47 行、`suggest` 第 65 行、`soundex` 第 96 行、`_soundex_table` 第 121 行、`suggest_soundex` 第 133 行

**`position_match` 結果**（全部與測試內的暴力掃描完全相同）：

| query | 篇數 | 備註 |
| --- | --- | --- |
| `"open source"` | 572 | `open /1 source` 是 603 篇，phrase 是它的子集 |
| `"lord of the rings"` | 82 | 區間 `[p, p+3]`，含 stopword 空洞 |
| `e-mail /5 server` | 27 | 與預先量測相同；doc 1400 只靠「`server` 在 `e mail` 前面」命中 |
| `linux /5 kernel` | 192 | 與 `kernel /5 linux` 相同；其中 3 篇只靠反方向命中 |
| `linux /1 kernel` | 182 | |
| `linux /1000000 kernel` | 222 | 等於同時含 linux 與 kernel 的文件 |
| `linux /5 linux` | 171 | 同一個位置（區間重疊）不算命中 |
| `"bye bye"`、`"step by step"`、`"the new york times"` | 37、181、1,114 | 同一個 token 出現兩次、跨 stopword 空洞、開頭是 stopword（positions `[2, 3, 4]`） |

**計時**：本機 WSL2，同一次 `t4_bonus.test.py` 執行，暖身一次後 5 次中位數。

| 項目 | 時間 | 前提／對照 |
| --- | --- | --- |
| `expand(comput*)` | 0.025–0.029 ms | 64 個 term 全部展開 |
| `expand(a*)` | 10.0–11.4 ms | 31,236 個候選依 `(-df, term)` 全部排序再取前 100；主要成本是排序 |
| `position_match("open source")` | 12.6–13.6 ms | 對照：只呼叫 `get_postings('open')` + `get_postings('sourc')` 是 10.1–10.8 ms |
| `position_match(linux /5 kernel)` | 1.9–2.0 ms | 對照：兩次 `get_postings` 1.4 ms |
| `position_match("lord of the rings")` | 2.6–2.8 ms | |
| `position_match(e-mail /5 server)` | 25–66 ms（4 次執行波動很大） | `e` df 9,596、`mail` 9,357、`server` 1,796；另一次單獨量測：三次 `get_postings` 22.3 ms、`position_match` 48.6 ms |
| k-gram index 建置（含第一次 `suggest`） | 0.95 s（不開 tracemalloc）；3.85 s（開 tracemalloc） | 每個 reader 一次；573,233 個 term |
| k-gram index 記憶體 | 建置後仍占用 28.8 MiB，峰值 38.6 MiB | `tracemalloc`，只算 Python 配置；`vocabulary()` 本身已由 reader 快取，不在這個數字內 |
| `suggest`（快取後） | `retreival` 22.1 ms、`linux` 14.6 ms、`a` 9.3 ms、`comput` 31.6 ms | 時間主要花在 Jaccard 篩選後對候選算 OSA |
| Soundex 對照表建置（含第一次 `suggest_soundex`） | 0.46 s | 每個 reader 一次，建置時就依 `(-df, term)` 排好 |
| `suggest_soundex`（快取後） | < 0.1 ms | 只是查表與跳過 term 本身 |

**拼字建議實際結果**：`suggest('retreival')` = `retreiv`(11)、`retrial`(2)、`retriev`(409)、`retreat`(251)、`pretrial`(11)，前三名與 §6.5 預先量測相同；`suggest('retreiv')` 第一名 `retriev`；`suggest('linux')` 第一名 `linu`(28)；`suggest('kernal')` 第一名 `kernel`(279)。`suggest_soundex('retreiv')` 前 5 個是 `retriev`、`rutherford`、`retrofit`、`retroberri`、`retribut`（都是 R361）。

#### 9.1.3 T4c 資料層（§6.8.1；拼字、wildcard、SOUNDEX 見 §9.1.4）
**範圍**：只做 §6.8.1 的資料層。改動 `HW2/src/tokenizer.py`（抽出 `normalize_token`）與 `HW2/tests/t1.test.py`（新增「`process` 重構」一節，原有 15 項不改）；新增 `HW2/src/build_surface_vocab.py`、`HW2/src/surface.py`、`HW2/tests/t4_surface.test.py`；`HW2/index/` 只新增 `surface_vocab.tsv`、`surface_vocab.meta.json`。`parser.py`、`spelling.py`、`t4_bonus.test.py` 都沒有動，§6.8.2–§6.8.5 尚未實作。建置前後用 `sha256sum` 比對過：`HW2/index` 的 11 個既有檔案與 `HW1/output` 的 6 個檔案都沒有改變。`HW2/index/` 整個在 `.gitignore` 中，所以 `surface_vocab.*` 不會出現在 git 中（依 G8，繳交時另外放進 zip）。

**`process` 重構的測試狀態**（`t1.test.py`）：
| 狀態 | 結果 | 說明 |
| --- | --- | --- |
| 重構前（golden 值剛寫進測試） | 19/27 | 原有 15 項 + 4 組 golden 值通過；組合關係與呼叫計數共 8 項 FAIL（`AttributeError: 'Preprocessor' object has no attribute 'normalize_token'`），與 §6.8.1 第 3 步的預期相符 |
| 重構後 | **27/27** | golden 值、組合關係、呼叫計數都通過 |

golden 值：48 個輸入（§4.2 表 21 個、§6.7 表 15 個、§6.8.1 列出的 11 個，再加一個含 `100kb 0.5mm h.o.o.q id im` 的長字串）× 4 種設定（HW2 stop+stem、HW1 casefold only、`casefold=False` 的 stop+stem、stop+lemma）。本機有 wordnet，所以 lemma 那組有跑；沒有 wordnet 時只印 `[SKIP]`，不觸發下載。golden 值由 scratchpad 的一次性腳本在重構前產生，以字面常數寫進測試。

**全部測試**（重構後、建置 `surface_vocab.*` 後）：
| 測試 | 結果 |
| --- | --- |
| `t1.test.py` | **27/27**（原有 15 + 重構 12） |
| `t1_bonus` ／ `t2` ／ `t2_bonus` | 11/11 ／ 19/19 ／ 37/37 |
| `t3` ／ `t3_bonus` | 17/17 ／ 25/25 |
| `t4` ／ `t4_bonus` | 48/48 ／ 99/99（測試檔未改） |
| `t4_surface.test.py`（新增） | **34/34** |

`t4_surface.test.py` 的 34 項：tsv 與 meta 8 項（表頭與列數、排序、189 個空 stem、stem 不含空白、meta 欄位、`sources` fingerprint、meta 的一致性數字、原字與 df 和 `HW1/output/lexicon.tsv` 相同）；測試內重算的一致性 5 項（stem 都在 index、index term 都有原字、df 上下界、與 `Preprocessor` 一致、`surface_stem` 等於 `normalize_token or ""`）；`load_surface` 7 項（內容與 tsv 相同、快取、`stem('retrieval') == 'retriev'`、`df('retrieval') == 81`、stopword／不存在的原字、`stem_of_any`、stem 與 lexicon 共用字串物件）；meta 核對 12 項（對照組、sha256、size、`N`、`format`、`preprocessor`、`count`、`stopword_count`、`sources` 缺項 → `ValueError`；刪 meta、刪 tsv → `FileNotFoundError`；竄改後真正的 index 仍可載入）；建置腳本 2 項（`--hw1-dir` 指向 `HW2/index` 拋 `ValueError` 且輸出目錄沒有新檔案；重新建置到 tempdir 的 tsv 與 `HW2/index` 的 byte 相同、沒有殘留 `.tmp`）。

**建置結果**（`uv run python HW2/src/build_surface_vocab.py`，本機 WSL2）：
| 項目 | 結果 |
| --- | --- |
| 總時間 | 4.41 s（測試中重建一次是 4.26 s） |
| 其中讀 HW1 lexicon + 來源檢查 | 0.22 s |
| 其中 `normalize_token` × 644,523 | 2.78 s（預先量測 2.7 s；測試中單獨再量一次 2.77 s） |
| 其中一致性檢查 | 1.06 s |
| 峰值 RSS | 351.7 MB（含 spaCy、`IndexReader` 的 lexicon；`ru_maxrss`） |
| `surface_vocab.tsv` | 14,191,438 bytes（13.5 MiB），644,523 列 + 表頭 |
| `surface_vocab.meta.json` | 1,206 bytes |
| stopword 列 | 189 |
| 一致性 | `stem_not_in_index` 0、`index_term_without_word` 0、`df_bound_violations` 0、`stopword_process_mismatch` 0 |
| 與 Preprocessor 一致（測試） | `Random(42)` 抽 5,000 個 + 189 個 stopword，共 5,186 個；`tokenize` 會改動而跳過 27 個；不一致 0 個 |

meta 的 `origin`：`HW1/output/lexicon.tsv` 15,550,484 bytes、sha256 `fbcb18ac…`；`sources`：`HW2/index/lexicon.tsv` 13,709,652 bytes、sha256 `db26f70a…`，與 §6.8.1 預先量到的值相同。

**`load_surface` 的成本**（`t4_surface.test.py` 第 6 節）：新的 reader、lexicon 已載入的情況下 0.54 s（3 次中位數：0.54、0.53、0.57 s），包含讀 tsv、核對兩個來源檔的 sha256、intern stem、建 `word → id`。`tracemalloc` 量到建置後 75.9 MiB、峰值 76.0 MiB（只算 Python 配置，不含 lexicon 本身）。這是 T7 第一次使用 wildcard／SOUNDEX／拼字建議時，在 k-gram（預先量測約 1 s）之外要多付的成本。

實作位置：
- `tokenizer.py`：`normalize_token` 第 94–104 行、`process` 第 106–112 行（原本 `:94-106`）、`from_config` 第 113–130 行（往下移 6 行）
- `surface.py`：`surface_stem` 第 34 行、`SurfaceVocab` 第 42 行（`df` 第 61 行、`stem` 第 66 行、`stem_of_any` 第 71 行）、`load_surface` 第 77 行
- `build_surface_vocab.py`：`check_sources` 第 64 行、`consistency` 第 88 行、`build_surface_vocab` 第 124 行

（`surface.py` 的行號在 §9.1.4 之後已改變，以 §9.1.4 為準。）

#### 9.1.4 T4c 拼字、wildcard、SOUNDEX（§6.8.2–§6.8.5）
**範圍**：改動 `HW2/src/parser.py`、`spelling.py`、`surface.py`，以及 `HW2/tests/t4_bonus.test.py`（依 §6.8.8 的修改表逐條改，再新增第 9–11 節）、`t4_surface.test.py`（新增第 6、7 節：k-gram index 與 Soundex 分組的資料結構）。`positional.py` 不必改。`writer.py`、`tokenizer.py`、`build_*` 腳本、`HW2/index/` 都沒有動。實作順序是 wildcard → SOUNDEX → 拼字，每完成一項都跑一次 `t4_bonus` 與 `t4_surface`。

**測試狀態**：
| 階段 | `t4_bonus.test.py` | `t4_surface.test.py` |
| --- | --- | --- |
| 改完測試、程式還沒改 | 100/162（62 項 FAIL，全部是 §6.8 新增或改變的行為） | 34/40（新增的 6 項 FAIL：`bigrams`、`pattern_bigrams`、`kgram`、`spelling` 殘留、`soundex_groups` ×2） |
| wildcard 之後 | 124/162 | 37/40 |
| SOUNDEX（含 `suggest_soundex`）之後 | 149/162 | 39/40 |
| 拼字（`suggest`、`did_you_mean`、`query_words`）之後 | **162/162** | **40/40** |

改測試前 100 項仍通過的原因：§6.8.8 的修改表中「數值不變」的項目（`a*`、`comput*` 的順序與巢狀、`_expand_copy`、`position_match` 全部），以及 `SOUNDEX(robert` 這類舊 parser 剛好也拋 `ValueError` 的輸入。

**回歸**（全部完成後，同一次執行）：
| 測試 | 結果 |
| --- | --- |
| `t1` ／ `t1_bonus` | **27/27** ／ 11/11 |
| `t2` ／ `t2_bonus` | 19/19 ／ 37/37 |
| `t3` ／ `t3_bonus` | 17/17 ／ 25/25 |
| `t4` | **48/48**（測試檔沒改） |
| `t4_bonus` ／ `t4_surface` | **162/162** ／ **40/40** |

`t4_bonus.test.py` 的 162 項：第 1 節 45、第 2 節 10、第 3 節（expand）10（`computing*` 拆成 `computing*` 與 `e-mail*` 兩項）、第 4 節（`position_match`）19、第 5 節（拼字，含 §6.8.8 第 8 節）15、第 6 節（Soundex）10、第 9 節（wildcard）22、第 10 節（SOUNDEX）30、第 11 節（新 process 的 `did_you_mean`）1。§6.8.8 第 7 節在 `t4_surface.test.py`（§9.2 T4c 資料層第 1 點）。

**與暴力做法對照的結果**（預期值都由測試內獨立的做法算出：直接讀 tsv、`fnmatchcase` 全掃、自己寫 Jaccard 與 OSA、自己分組）：
| 項目 | 結果 |
| --- | --- |
| wildcard 去重後的 stem 數 | `*mon` 276、`co*tion` 528、`*tion*` 7,482、`ab*ba` 3、`*x*` 22,129，集合與 `limit=100` 的順序都與暴力相同，和 §6.8.4 的預先量測一致 |
| `ab*ba` 的 post-filter | k-gram 候選 91 個，regex 後剩 3 個（`abba`、`ababa`、`abeba`）；`aba` 在候選中但被刷掉 |
| `computers*` ／ `computing*` ／ `e-mail*` | 6 個（第一個 `comput`）／ `T(['comput'])` ／ `None`（警告 1 次） |
| `SOUNDEX(robert)` | 214 個 stem，前 5 個 `report`、`refer`、`robert`、`repair`、`reproduc`；`robert` 第 3、`rupert` 第 20；警告 `SOUNDEX(robert) matched 214 terms; using the top 100 by df` |
| `smith`／`smyth`、`stephen`／`steven` | 互相包含對方的 stem（S530 396 個 stem、S315 185 個 stem） |
| Soundex 分組 | 6,361 種碼，最大一組 1,240 個原字，與暴力分組相同 |
| k-gram index | 35,235 種 bigram，共 6,311,830 個原字 id；7 個 bigram 的 posting 與暴力相同 |
| `suggest` | `retreival`、`kernal`、`computr` 的完整結果（`limit=10**9`）與前 5 名都與暴力相同 |

**拼字建議實際結果**（原字，括號內是原字 df）：
| 輸入 | `suggest` 前 5 名 | `did_you_mean` |
| --- | --- | --- |
| `retreival`（1） | `retrieval`（81）、`retrial`（2）、`retreat`（178）、`revival`（88）、`pretrial`（11） | `['retrieval', 'retrial', 'retreat']` |
| `retrieval`（81） | `retreival`、`retrial`、`retrievr`、`medieval`、`retreat` | `[]` |
| `linux`（997） | `linus`（28）、`linqx`、`linuq`、`lieux`、`linx` | `[]` |
| `kernal`（2） | `kernel`（266）、`kernan`、`bernal`、`vernal`、`kenal` | 觸發 |
| `computr`（0） | `computer`（5,223）、`computo`、`computar`、`computor`、`compete` | 觸發 |
| `recieve`（40）、`goverment`（53）、`informaton`（2） | 第一名 `receive`（4,456）、`government`（2,605）、`information`（11,168） | 都觸發 |
| `linus`（28） | `links`（9,251）、`lines`、`linux`、`minus`、`sinus` | 觸發（正確的人名也觸發，§10.4） |
| `teh`（292） | `ten`、`tech`、`th`、`te`、`tel` | `[]`（`the` 是 stopword，被排除） |

`stem` 為 `retriev` 的原字在去重前的順序是 `retrieval`（OSA 1）、`retrievals`（2）、`retrievable`（3），所以保留 `retrieval`；df 較高的 `retrieved`（140）距離更大，不會出現。`suggest_soundex('retreival')` = `retrieved`、`rutherford`、`retroberry`、`retribution`、`retrouver`（都是 R361）；`suggest_soundex('robert')` = `report`、`referred`、`reproduced`、`reproduction`、`roberto`，與 §6.8.5 的預先量測相同。

**計時**：本機 WSL2，回歸時那一次 `t4_bonus.test.py` 的執行，暖身一次後 5 次中位數（標明 s 的是單次）。
| 項目 | 時間 | 前提／對照 |
| --- | --- | --- |
| **`did_you_mean` 第一次呼叫（總成本）** | **1.59 s**（3 個新 process 的中位數：1.65、1.59、1.59 s） | 新 process，import 之後、lexicon 已載入（讀 lexicon 另需 0.39 s，不算在內）。包含 `load_surface` + 建原字 k-gram + 查詢；同一個 process 的第二次呼叫 27 ms。子 process 的峰值 RSS 503 MB（含 spaCy、lexicon、原字詞彙、k-gram） |
| 　拆開量（新 process，3 次中位數） | `load_surface` 0.54 s、建 k-gram 1.06 s、查詢 33 ms | 三段加起來與上一列一致 |
| 原字 k-gram index 建置 | 0.95 s（不開 tracemalloc）；4.01 s（開 tracemalloc） | 644,523 個原字；預先量測 1.05 s |
| 原字 k-gram index 記憶體 | 建置後仍占用 32.1 MiB，峰值 33.0 MiB | `tracemalloc`，不含原字詞彙本身（`load_surface` 75.9 MiB，§9.1.3）；與預先量測相同 |
| `suggest`（k-gram 已建好） | `retreival` 24.8 ms、`linux` 17.1 ms、`a` 9.0 ms、`computer` 45.2 ms | 主要是對 Jaccard 篩出的候選算 OSA；T4b 的 stem 版是 9.3–31.6 ms |
| 原字 Soundex 對照表建置（含第一次 `suggest_soundex`） | 0.45 s | 預先量測 0.44 s；T4b 的 stem 版 0.46 s |
| `suggest_soundex('retreival')`（快取後） | 0.002 ms | 查表、跳過同 stem |
| `expand(SOUNDEX(robert))` | 0.12 ms | 268 個原字 → 214 個 stem → 取前 100 |
| `expand(*mon)` ／ `expand(co*tion)` ／ `expand(*tion*)` | 2.3 ms ／ 4.6 ms ／ 12.8 ms | k-gram 交集 + regex post-filter；預先量測 `co*tion` 9.9 ms、`*tion*` 17.3 ms |
| `expand(*x*)`（沒有 bigram，全掃） | 81.3 ms | regex 掃過 644,523 個原字；預先量測 78 ms |
| `expand(comput*)` ／ `expand(a*)` | 1.53 ms ／ 30.0 ms | T4b 的 `prefix_terms` 版是 0.027 ms ／ 10–11 ms。變慢的原因：要對 `$c`、`co` 這類很長的 posting 取交集，`a*` 要對 `$a` 的全部原字跑 regex、轉 stem、對 31,236 個 stem 排序 |
| `load_surface`（`t4_surface`） | 0.52 s；75.9 MiB | 與 §9.1.3 相同 |
| `position_match` 各項 | `"open source"` 12.2 ms、`linux /5 kernel` 1.7 ms、`"lord of the rings"` 2.7 ms、`e-mail /5 server` 25.6 ms | 沒有改動，與 §9.1.2 相同 |

`build_surface_vocab.py` 這次沒有重建（§9.1.3 的 4.41 s，其中 `normalize_token` 2.78 s；`t4_surface` 單獨重量 `normalize_token` × 644,523 是 2.68 s）。

**實作位置**：
- `parser.py`：`Wildcard` 第 45 行、`Soundex` 第 50 行、`Node` 第 69 行、`_lex` 第 85 行、`_UNARY_START` 第 120 行、`parse_primary` 第 169 行、`parse_soundex` 第 203 行、`_prune` 第 261 行、`_needs_expand` 第 321 行、`parse` 第 332 行、`expand` 第 355 行（`_expand_node` 第 376 行、`_top_terms` 第 393 行）、`query_words` 第 415 行、`query_terms` 第 447 行
- `surface.py`：`bigrams` 第 45 行、`pattern_bigrams` 第 55 行、`pattern_regex` 第 66 行、`SurfaceVocab` 第 71 行（`kgram` 第 108 行、`wildcard_candidates` 第 121 行、`match_wildcard` 第 144 行、`soundex_groups` 第 150 行）、`load_surface` 第 167 行
- `spelling.py`：`_osa` 第 21 行、`suggest` 第 39 行、`did_you_mean` 第 82 行、`soundex` 第 106 行、`suggest_soundex` 第 131 行。`_bigrams`、`_kgram_index`、`_kgram_cache`、`_soundex_table`、`_soundex_cache` 都已刪除

### 9.2 與計畫的差異
1. **lexer 一開始就用 T4b 的 regex**：§4.1 原本寫核心用 `\S+`、T4b 再換 regex。實作直接用 §6.1 的 `"[^"]*"?|[()]|[^\s()"]+`，並分出全部 9 種 kind：`WORD`、`AND`、`OR`、`NOT`、`(`、`)`、`PHRASE`、`WILDCARD`（結尾是 `*`）、`NEAR`（整個 token 符合 `/\d+`）。T4b 不必改 `_lex`。§4.2 表中的 query 結果不受影響。
2. **lexer 不拋錯**：`PHRASE` 的 text 保留原本的引號（沒有結尾引號時也照樣切出），引號／括號配對、單獨的 `*`、`/0` 的 `ValueError` 都留給 T4b 的 parser 判斷，位置取自 token 的 `pos`。
3. **核心遇到加分語法拋 `NotImplementedError`**（計畫沒寫核心該怎麼處理這些符號）：在 `parse_unary`（`NOT`）、`parse_primary`（`(`、`PHRASE`、`WILDCARD`、`NEAR`）與最外層的「還有剩餘 token」（多出來的 `)`、`/k`）三處，訊息開頭都是 `T4b:`，並註明是哪種語法、token 與字元位置。所以 T4a 之後，`"`、`(`、`)`、`NOT`、`/k`、結尾的 `*` 就已經不是一般詞了（§4.3 原本寫 T4b 之後才會這樣），只是在 T4b 之前會拋錯。
4. **`parse_and` 已經是 `unary (["AND"] unary)*` 的形狀**：迴圈遇到 `AND` 或能開始 unary 的 token（`_UNARY_START`：`WORD`、`NOT`、`(`、`PHRASE`、`WILDCARD`）就繼續。T4a 中連續的 `WORD` 已在 `primary` 合併，所以實際只會碰到加分 token，再由 `parse_unary`／`parse_primary` 拋錯；T4b 把拋錯換成實作後就自動得到隱含 AND。
5. **測試內容**：
   - 多加三項：`_lex` 的 token 分類與字元位置、`expand` 不修改傳入的樹，以及「`parse` 不讀 index」的具體做法：直接 `Preprocessor(casefold=True, stopword=True, stem=True)` 建立，不經過 reader，再跑整張表。
   - 加分語法的 `NotImplementedError` **沒有**寫進 `t4.test.py`：T4b 合併後它們會變成正常結果或 `ValueError`，寫進去會違反「`t4.test.py` 必須照樣全過」，所以只用一次性腳本確認（§9.1）。
   - `_lex` 在 stub 中不存在，測試檔用 `try/except ImportError` 匯入，讓 stub 狀態也能跑完並記為 FAIL。
6. **`_prune` 的範圍**：實作了 Term、And／Or（移除、攤平、同類型合併）、`Not`（child 為空時移除）四種節點；`Not` 的規則雖然核心的 parser 產生不出 `Not`，但它是 §4.1 四條規則之一，而且很簡單，所以一起做了。`Phrase`、`Near`、`Wildcard` 原樣保留，留給 T4b。只有空的 `Term` 會警告；移除空的 `And`／`Or`／`Not` 不另外警告（與 §4.1 一致，`AND` 的 2 次警告來自兩個空的 `Term`）。`_prune` 回傳新的節點，不修改輸入。
7. **`expand` 原樣回傳同一個物件**（`expand(node) is node`），不複製；它不修改樹，所以符合「不修改傳入的樹」。判斷有沒有 `Wildcard` 用 `_contains_wildcard`，只往下走 `And`／`Or`／`Not`。
8. **`query_terms` 遇到未知的節點拋 `TypeError`**（計畫沒寫，防呆）。
9. **行號變動**：`parser.py` 開頭多 import 了 `re`、`warnings`，dataclass 本身沒有改，但都往下移了 3 行（`Term` 在 `:22-24`、`Phrase` `:27-30`、`Near` `:33-37`、`Wildcard` `:40-42`、`Not` `:45-47`、`And` `:50-52`、`Or` `:55-57`、`Node` `:60`）。§3.1、§3.2 的表還是舊行號；stub 函式的新位置見 §9.1。`positional.py:6`、`boolean.py:6` 只 import 名稱，不受影響。
10. 警告訊息是 `"empty operand removed from query (only stopwords or a missing operand)"`，類別 `UserWarning`、`stacklevel=2`。

**T4b 與計畫的差異**（以上 1–10 是 T4a 的紀錄）：
1. **`position_match` 沒有先用 `get_doc_tf` 取候選**（§6.2 寫的是選用做法）：改成依 `reader.df` 由小到大，每個不同的 token 呼叫一次 `get_postings`，邊讀邊取 doc 交集，交集變空就停，不再讀剩下的高 df 詞。這樣在一般情況下不必多付一次 `get_doc_tf` 的成本，交集為空時也能提早結束。Near 的兩側共用同一份 postings（`linux /5 linux`、`new new york` 都只讀一次），由測試的 spy 確認。
2. **Near 區間比對用 bisect**：同一側的區間長度固定，依 start 排序後 end 也遞增，所以對每個左區間各做兩次 `bisect_left`（右在後、左在後），不必兩層迴圈。正確性以暴力掃描對照（10 個 query 全部相同）。
3. **NEAR 缺少一側不是錯誤**（計畫只寫了 stopword 造成的空側）：NEAR 前面沒有可當 side 的運算元（query 開頭、`)` 之後、Wildcard 之後，或串接的 `a /5 b /5 c` 的第二個 `/5`）時，左側是空的 `Phrase`；NEAR 後面不是 `WORD`／`PHRASE`（`(`、運算子、Wildcard、結尾）時，右側是空的。之後套用 Near 退化規則並警告，與 T4a「缺少運算元產生空節點」一致。例：`/5 linux` → `T(['linux'])`（1 次警告）；`linux /5 kernel /5 window` → `And([Near(linux, kernel, 5), T(['window'])])`（1 次警告）；`(linux) /5 kernel`、`comput* /5 linux` 都退化成隱含 AND。為此 `_UNARY_START` 加入 `NEAR`。
4. **Near 兩側都空時警告 2 次**（每個空的一側各一次，與 `AND` 兩個空 Term 警告 2 次一致）；只有一側空時警告 1 次（計畫的規則）。
5. **Wildcard 的 prefix**：去掉結尾的所有 `*` 後 casefold，`comp**` 等於 `comp*`；`*`、`**` 拋 `ValueError`。prefix 中的非字母字元原樣保留（`e-mail*` → `Wildcard('e-mail')`），dictionary 中沒有含 `-` 的 term，所以展開成 0 個並警告。
6. **Phrase 的 positions 不重新編號**：直接取 `process` 的 position，開頭是 stopword 時不從 1 開始（`"the new york times"` → `Phrase(['new', 'york', 'time'], [2, 3, 4])`）。比對只用相對位移，所以結果不受影響。
7. **`expand` 在有 Wildcard 時先 `copy.deepcopy` 整棵樹**，回傳的樹與輸入不共用任何可變節點（測試會改動結果再檢查原樹）；沒有 Wildcard 時仍原樣回傳同一個物件（T4a 行為不變）。超過上限的警告訊息是 `wildcard a* matched 31236 terms; using the top 100 by df`；0 個時是 `wildcard computing* matched no term in the dictionary; removed from query`。`limit < 1` 時視同展開成 0 個並移除（計畫沒寫）。
8. **空運算元警告改由 helper `_warn_empty` 發出**，`stacklevel` 因此改成 3，讓警告指到的位置與 T4a 相同。類別仍是 `UserWarning`。
9. **錯誤訊息**：`unmatched '"' at position N`、`unmatched '(' at position N`、`unmatched ')' at position N`、`wildcard without a prefix '*' at position N`、`proximity distance must be at least 1: '/0' at position N`。`/00` 也算 `/0`。
10. **`position_match` 的防呆**（計畫沒寫）：不是 `Phrase`／`Near` 時拋 `TypeError`；手建的空 `Phrase` 或空的 Near 側回傳 `set()`（`parse` 不會產生這種節點）。
11. **`spelling.py` 的實作細節**：k-gram index 是 `gram → array('I')`（term id），另存每個 term 的 bigram 數（`array('H')`）算 Jaccard；快取用 `weakref.WeakKeyDictionary`，以 reader 為 key。Soundex 只看 ASCII 字母，沒有字母時回傳空字串；`suggest_soundex` 只收 `isascii() and isalpha()` 的 term，對照表在建置時就依 `(-df, term)` 排序。`limit < 1` 時兩個 suggest 都回傳 `[]`。沒有用 numpy（它只是 spacy 的間接依賴）。
12. **測試內容**：
    - §6.7 表之外多了 9 列語法補充、9 種 `ValueError`（計畫列 6 種，另加 `linux "open`、`((linux)`、`linux OR **`）、`expand` 的順序、`limit=3`、只展開成 1 個、巢狀 Wildcard、結果與原樹不共用節點、展開後的 `query_terms`；`position_match` 多了 `"open source" /3 "linux kernel"`、`linux /1 kernel`、`"step by step" /4 linux`、重疊不算、不在 dictionary 的 term、`get_postings` 呼叫次數；`suggest` 多了排序檢查（測試內自己寫 OSA 重算）；Soundex 多了 `Lee`、小寫 `tymczak`，以及 `suggest_soundex` 的排序。
    - 暴力掃描的寫法刻意和實作不同：對每篇文件建「位置 → term 集合」的表，掃過 1..最大位置的每個起點找 phrase 區間，再對兩側所有區間組合做兩層迴圈檢查間隔。
    - 原本列進對照的 `"new new york"` 在 index 中是 0 篇，對照沒有意義，所以換成 `"bye bye"`（37 篇）、`"step by step"`（181 篇）、`"the new york times"`（1,114 篇）；`"new new york"` 只留在呼叫次數的測試。stub 狀態跑的是換之前的版本（96 項），換完是 99 項。
    - 計時用 `timing()` 包起來，stub 狀態只記錄例外，不中斷；k-gram 建置量兩次（開與不開 tracemalloc），Soundex 對照表的建置時間在第一次 `suggest_soundex` 之前量。
13. **計畫 §3.1、§3.2 的行號已過時**：以 §9.1.2 的實作位置為準。`positional.py` 的 docstring 已改成 §6.3 的區間規則。

**T4c 資料層與計畫的差異**（§6.8.1；以上是 T4a、T4b 的紀錄）：
1. **測試放在新的 `HW2/tests/t4_surface.test.py`，不是 `t4_bonus.test.py` 的第 7 節**：這次的範圍不改 `t4_bonus.test.py`，而且第 8–10 節（拼字、wildcard、SOUNDEX）還沒實作，放進去會讓該檔失敗。§6.8.8 第 7 節的每一項都在新檔中，另外加了 `load_surface` 的行為與更多 meta 竄改的情況。之後實作 §6.8.2–§6.8.5 時，可以把它併入 `t4_bonus.test.py`，或保留成獨立的檔案。
2. **`surface.py` 只有資料層**：`surface_stem`、`load_surface`、`SurfaceVocab`（`words`、`dfs`、`stems`、`word_id`、`df`、`stem`、`stem_of_any`，另加 `__len__`、`__contains__`）。`kgram()`、`soundex_groups()` 與 wildcard 比對還沒做；`_bigrams` 也還沒從 `spelling.py` 搬過來，因為搬移要改 `spelling.py`，不在這次的範圍內。
3. **meta 的 `consistency` 多一個欄位 `stopword_process_mismatch`**：對應 §6.8.1 第 4 步的第 4 點（stopword 列用 `pre.process(word)` 也要得到 `[]`）。計畫的 meta 範例只列了前三個欄位。它和其他三項一樣，預設有例外就失敗。實測為 0。
4. **`load_surface` 多核對 `stopword_count`**：tsv 中 stem 是空字串的列數必須等於 `meta["stopword_count"]`，不符時拋 `ValueError`。計畫只列了 `count`。
5. **重新建置時先刪掉舊的 meta**：§6.8.1 第 5 步寫「先換 tsv，最後換 meta」。但是重新建置時，舊的 meta 在換 tsv 與換 meta 之間仍然存在，會形成「新 tsv + 舊 meta」的組合。所以在兩次 `os.replace` 之前，先刪除舊的 meta。不論成功或失敗，`.tmp` 都會在 `finally` 中清掉。
6. **`FileNotFoundError` 的訊息**寫出完整指令與前提：`... not found; run build_surface_vocab.py first (`uv run python HW2/src/build_surface_vocab.py`, needs HW1/output)`。
7. **來源檢查一次列出所有不符的項目**：例如 `--hw1-dir HW2/index` 的訊息是 `hw1-dir is not the unstemmed HW1 index: preprocessor.stopword is True, expected False; preprocessor.stem is True, expected False`，不是遇到第一項就停。另外檢查 HW1 lexicon 的每一列都是 4 欄。
8. **`df`、`stem` 只做精確比對**，不對輸入做 casefold；`stem_of_any` 對不在詞彙中的字呼叫 `normalize_token`，它本身會做 casefold。
9. **重構前的狀態**：§6.8.1 第 3 步預期重構前只有「呼叫計數」會失敗。實際上「組合關係」也會失敗，因為它也要呼叫 `normalize_token`（見 §9.1.3 的表）。golden 值在重構前後都通過。
10. **建置的峰值 RSS 是 351.7 MB**：計畫沒有估這個數字。主要來自 spaCy、HW2 lexicon 的 dict，以及 644,523 個原字的 list。只有建置時需要；查詢時的成本見 §9.1.3 的 `load_surface`（75.9 MiB）。

**T4c 拼字、wildcard、SOUNDEX 與計畫的差異**（§6.8.2–§6.8.5；以上是資料層的紀錄）：
1. **k-gram 與 Soundex 分組快取在 `SurfaceVocab` 物件上**（`_kgram`、`_soundex` 屬性），不另外用 `WeakKeyDictionary`。`SurfaceVocab` 本身已依 reader 快取（`load_surface`），所以壽命相同。§6.8.8 修改表中「清除 `surface.py` 的快取」在測試中寫成 `sv._kgram = None`／`sv._soundex = None`：只重建這一份結構，不重讀 tsv。
2. **`surface.py` 多了幾個公開名稱**：`pattern_bigrams(pattern)`（§6.8.4 第 1 步）、`pattern_regex(pattern)`（post-filter 的 regex），以及 `SurfaceVocab.wildcard_candidates(pattern)`（只做 k-gram 篩選）與 `match_wildcard(pattern)`（篩選 + post-filter）。拆成兩個方法，是為了讓測試能直接檢查「`ab*ba` 有 91 個候選，post-filter 後剩 3 個」。`soundex_groups()` 存的是原字 id（不是字串），每組已依 `(-原字 df, 原字)` 排序，呼叫端用 id 直接取 `words`、`stems`、`dfs`。
3. **k-gram 交集**：從最短的 posting 建 `set`，再對其他 posting 做 `intersection_update`，變空就回傳；pattern 中任何一個 bigram 不在 index 中時直接回傳空 list。沒有 bigram 時回傳 `range(len(words))`（全掃）。
4. **`SOUNDEX()` 參數的 ASCII 字母檢查直接呼叫 `spelling.soundex(word)`**（回傳空字串就拋錯），不另外寫 regex。這樣 parse 與 expand 用同一個函式判斷，不會出現 parse 接受、expand 卻算不出碼的情況。因此 `parser.py` 在模組層級 import `spelling.soundex` 與 `surface`；import 關係是 `parser → spelling → surface → tokenizer`，`surface.soundex_groups()` 在函式內才 import `spelling`，沒有循環。
5. **`SOUNDEX(` 的錯誤分類**（計畫只列了 `SOUNDEX(robert`）：`(` 後面沒有 token，或是只有一個 `WORD` 就結束（`SOUNDEX(`、`SOUNDEX(robert`），拋 `unmatched '(' at position N`（N 是 `(` 的位置）；其餘不是「恰好一個 `WORD` 接 `)`」的情況，都拋 `SOUNDEX() needs exactly one word at position N`（N 是 `SOUNDEX` 的位置）。另外測了 `SOUNDEX(SOUNDEX(x))`、`SOUNDEX(NOT x)`、`linux SOUNDEX(李)`（位置 6）。
6. **expand 的警告**：訊息是 `wildcard {pattern} matched N terms; using the top 100 by df`、`wildcard {pattern} matched no term in the dictionary; removed from query`；Soundex 把開頭換成 `SOUNDEX({word})`。兩者由同一個 helper `_top_terms` 發出，`stacklevel=4`：Wildcard／Soundex 是根節點時指到 `expand` 的呼叫端（T4b 的 `stacklevel=4` 是設在 `_expand_node` 裡，會多指一層）。`limit < 1` 時與 T4b 相同：超過上限的警告照發，節點移除。
7. **`expand` 經由模組屬性呼叫 `surface.load_surface`**，不是 `from surface import load_surface`，所以測試可以用 spy 換掉它，確認樹中沒有 Wildcard／Soundex 時一次都沒有呼叫（§6.8.8 第 9 節最後一項）。
8. **`suggest`、`did_you_mean`、`suggest_soundex` 會先對輸入做 casefold**：計畫寫輸入已經是 casefold 過的原字，這裡只是防呆，不影響 `query_words` 的輸出。`suggest` 的輸入 stem 用 `stem_of_any` 計算，所以輸入是 stopword 時，stem 是空字串，stopword 本來就會被排除。
9. **`query_words` 的細節**：`SOUNDEX` token 之後連同 `(` 與參數一起略過（共 3 個 token），`)` 照一般規則略過；沒有結尾引號的 `PHRASE` 只去掉開頭的引號；stopword 用 `pre.normalize_token(tok) is None` 判斷（與 `process` 同一段程式）；去重以 casefold 後的字為準（`linux linux LINUX` → `['linux']`）。
10. **測試的位置與編號**：k-gram index 與 Soundex 分組的資料結構測試放在 `t4_surface.test.py` 新的第 6、7 節。`t4_bonus.test.py` 的 §6.8.8 第 8 節（拼字）與舊的第 5 節合併，因為修改表本來就要改寫第 5 節的大部分項目；第 9、10 節照計畫的編號新增，另外加第 11 節，在全新的 process 中量 `did_you_mean` 第一次呼叫的成本（用 `subprocess` 執行，3 次）。修改表的 `_retreiv` 已刪除，改由第 5 節的 `stem('retrieval') == 'retriev'` 取代。
11. **測試比計畫多的項目**：`suggest` 與暴力的完整比對（全掃 644,523 個原字算 Jaccard、自己寫 OSA，對 `retreival`、`kernal`、`computr` 比完整結果與前 5 名）；`did_you_mean(show=1)`；`query_words` 5 項；`suggest_soundex` 與暴力的前 20 名；`SOUNDEX` 的 13 種 AST（含 `SOUNDEXES(x)`、`SOUNDEX(O'Brien)`、`NOT SOUNDEX(robert) linux`）與 `_lex`；`t4_surface` 的 `bigrams`、`pattern_bigrams`、`kgram` 結構、Soundex 分組結構。
12. **`expand(comput*)`、`expand(a*)` 比 T4b 慢**（0.027 → 1.5 ms、10 → 30 ms，§9.1.4）：計畫沒有估這兩項。`comput*` 要對 `$c`、`co`、`om` 這類很長的 posting 取交集；`a*` 的候選是 `$a` 的全部原字，要一一跑 regex、轉成 stem 再排序。仍在幾十 ms 以內，所以沒有另外為「只有結尾 `*`」的 pattern 寫 bisect 的快捷路徑。
13. **`positional.py` 不必改**：Phrase／Near 的比對沒有變，`position_match` 的計時也與 §9.1.2 相同。

### 9.3 需要回寫 00-overview.md
之後所有要回寫總規劃的項目一律記在這裡，不只在對話中列出。回寫完成後打勾，並註明回寫的位置。以下是本次一致性檢查（§4.4）找到的項目：
行號是回寫後 `00-overview.md` 的行號（項目標題中的舊行號是回寫前的位置）。
- [x] D1 第 139 行「查詢流程」：改成「`parse` 或 `expand` 回傳 `None` 時直接輸出空結果，後面的步驟都不呼叫」。**已回寫**：第 141 行（「查詢流程」說明）、第 143–144 行（程式碼區塊 `parse`、`expand` 的註解）；另在第 284 行（T7「T4b 語法」）補一句
- [x] D2 第 91、216、278 行：`parse` 的 `ValueError` 補上 `*`（prefix 為空）、`/0`，訊息同樣含字元位置。**已回寫**：第 91–92 行（「接口定義」`parse` 註解）、第 222 行（T4「輸出約定」，改名為「語法錯誤」）、第 284 行（T7「T4b 語法」）。原本一併回寫的「Near 一側超過一個 token」已依 D13 從這三處刪除
- [x] D13 Near 改成兩邊 `Phrase` 與新的距離定義。**已回寫**：第 83 行（AST 定義）、第 92 行（`parse` 註解：Near 兩邊可以有多個 token）、第 101 行（`position_match` 註解：區間間隔、不分順序、含 stopword 空洞）、第 211 行（單 token phrase 規則註明 Near 兩邊除外）、第 222 行（T4「語法錯誤」註明多 token 不是錯誤）、第 304 行（加分表第 2 項）。總規劃的總行數沒有變，D1–D6 記錄的行號仍然正確
- [x] D3 第 204–208 行空節點規則：補上同類型巢狀節點合併、單 token Phrase 簡化成 Term、Near 一側為空時退化並警告、Wildcard 展開成 0 個時移除並警告。**已回寫**：第 209、211–213 行（T4「注意」的空節點規則）
- [x] D4 第 93 行 `expand`：補上「依 `(-df, term)` 排序、警告訊息含總數、不修改傳入的樹」。**已回寫**：第 94–95 行（「接口定義」`expand` 註解，另補上整棵樹變空時回傳 `None`）、第 308 行（加分表第 6 項）
- [x] D5 第 123 行 `prefix_terms`：補上「空字串拋 `ValueError`」；第 122 行 `vocabulary` 已寫「不可修改」，不必改。**已回寫**：第 125 行（「加分項的接口」）
- [x] D6 第 281–283 行拼字觸發條件：補上「`s` 是空 list 時不觸發」。**已回寫**：第 287 行（T7「拼字建議」）、第 309 行（加分表第 7 項）
- [x] D12 第 196 行：「先用大寫 AND／OR 切成運算元」改寫成「lexer 切出 token 與字元位置，再以遞迴下降解析」（實作就是 lexer + 遞迴下降，見 §9.2 第 1、4 點）。**已回寫**：第 198 行（T4「做法」第 1 點）

T4b 實作後新增的項目，已與 §6.8 合併後一起回寫。以下行號是**回寫後** `00-overview.md` 的行號；項目原本記錄的舊行號已刪除。§6.8 尚未實作，所以總規劃中 T4c 的部分都標成「T4c（計畫中，見 `T4.md` §6.8）」；數字只寫預先量測的值，或寫「待實作後量測」：
- [x] E1 NEAR 缺少一側不是錯誤，視為空的一側並套用退化規則；兩側都空時每側各警告一次（§9.2 T4b 第 3、4 點，依下表加上 `SOUNDEX(...)`）。**已回寫**：
  - 第 100 行（`parse` 註解）
  - 第 233–234 行（T4「注意」的空節點規則）
  - 第 251 行（T4「語法錯誤」的「以下不是錯誤」）
- [x] E2 `position_match` 每個不同的 token 只呼叫一次 `get_postings`，依 df 由小到大讀，交集為空就提早結束，沒有用 `get_doc_tf`（§9.2 T4b 第 1 點）。**已回寫**：第 114 行
- [x] E3 `expand` 在有 Wildcard／Soundex 時回傳深拷貝，沒有時不讀檔（依下表改寫）。**已回寫**：第 105–106 行
- [x] E4 Soundex 只看 ASCII（依下表改寫成「只有一份原字詞彙的對照表」）。**已回寫**：
  - 第 150–151 行（`soundex`、`suggest_soundex` 的接口註解）
  - 第 345 行（加分表第 11 項）
- [x] E5 **作廢**。舊敘述「`expand(a*)` 約 10 ms，瓶頸在排序」沒有寫進總規劃（T4c 起 wildcard 不再用 `prefix_terms` 加排序），只寫進 §9.1 的歷史紀錄。加分表第 6 項（第 339 行）已改寫成原字 k-gram 的做法，只放預先量到的全掃時間（約 50–80 ms）。正式數字等 §6.8 實作後再補
- [x] E6 **作廢並改寫**。舊的 stem k-gram 數字（0.95 s、29 MiB）與「結果是 stem 形式」都已從總規劃刪除，改成原字版本。**已回寫**：
  - 第 340 行（加分表第 7 項：做法、去重保留距離最小的原字、預先量到的 1.05 s／32 MiB）
  - 第 316–322 行（T7「拼字建議」：`did_you_mean`、原字 df、顯示原字、第一次呼叫的成本）
  - 第 393 行（已知限制）

**E1–E6 與 §6.8 合併檢查**（已依此表回寫；數字以實作後的 §9.1 為準，實作後再更新）：
| 項目 | 是否受 §6.8 影響 | 處理 |
| --- | --- | --- |
| E1 NEAR 缺少一側 | 小幅 | 照原內容回寫；舉例時把「`)` 或 Wildcard 之後」改成「`)`、Wildcard 或 `SOUNDEX(...)` 之後」 |
| E2 `position_match` 讀取方式 | 否 | 照原內容回寫 |
| E3 `expand` 深拷貝 | 是 | 改成「樹中有 Wildcard **或 Soundex** 時回傳深拷貝」；另外補上「沒有時不讀 `surface_vocab.*`」 |
| E4 Soundex 只看 ASCII | 是 | 改寫成：「只維護一份原字詞彙的 Soundex 對照表，只收 `isascii() and isalpha()` 的原字；`SOUNDEX()` 運算子與 `suggest_soundex` 共用。`suggest_soundex` 輸入與回傳都是原字，依 stem 去重」（§8 G6） |
| E5 `expand(a*)` 約 10 ms | **作廢** | wildcard 不再用 `prefix_terms` 加排序。改成回寫 §6.8 實作後的量測（k-gram 篩選、全掃的情況、`a*`），併入 F11 |
| E6 拼字的 k-gram 數字與規格 | **作廢並改寫** | stem 的 k-gram index 已刪除。第 309 行的做法改成「原字的 bigram 篩選 → 排除同 stem 與 stopword → (OSA, -原字 df, 原字) 排序 → 依 stem 去重」；觸發條件改用原字 df；刪除「dictionary 是 stem 後的形式」。數字改用原字 k-gram（預先量到約 1.05 s、約 32 MiB，正式數字以 §9.1 為準）。「T7 第一次呼叫要付建置成本」的注意事項保留，另外加上讀 tsv 的成本。併入 F10、F11 |

§6.8 新增的回寫項目。項目標題中的行號是回寫**前**的位置；「已回寫」後面的是回寫**後**的行號。總規劃中這些內容都標成 T4c（計畫中）：
- [x] F1 第 84 行 AST：`Wildcard(prefix: str)` 改成 `Wildcard(pattern: str)  # co*tion、*mon；只做 casefold，pattern 含 *`；新增 `Soundex(word: str)  # SOUNDEX(robert)；只做 casefold`；第 86 行的 `Node` 加入 `Soundex`。**已回寫**：第 87–88、90 行
- [x] F2 第 88–92 行 `parse` 註解。**已回寫**：第 95–98 行（第 100 行是 E1）：
  - `*` 可以出現在任何位置
  - 只有大寫的 `SOUNDEX` 緊接著 `(` 才是運算子
  - `ValueError` 的情況加上「wildcard 只有 `*`」與 `SOUNDEX()` 的參數錯誤（§6.8.5 的表），並刪除「prefix 為空」的說法
- [x] F3 第 93–95 行 `expand` 註解。**已回寫**：第 102–107 行：
  - Wildcard 與 Soundex 都在原字詞彙上比對，比對到的原字轉成 stem 後去重
  - 依 stem 的 `(-df, term)` 排序；總數是去重後的 stem 數
  - 需要 `surface_vocab.*`：不存在時拋 `FileNotFoundError`，meta 不符時拋 `ValueError`
  - 沒有 Wildcard／Soundex 時原樣回傳，不讀檔
- [x] F4 第 97 行 `query_terms`：遇到 Wildcard **或 Soundex** 拋 `ValueError`。**已回寫**：第 109 行
- [x] F5 第 105 行 T5 `evaluate`：輸入一定已經 expand 過，遇到 Wildcard 或 Soundex 拋 `ValueError`（`boolean.py` 本身不改，只更新說明）。**已回寫**：
  - 第 118 行（接口定義）
  - 第 263 行（T5「配合 T4b 加分」）
  - 另在第 295 行（T6「配合加分項」）補上 Soundex
- [x] F6 第 120–138 行「加分項的接口」。**已回寫**：
  - 第 80–81 行（`normalize_token`，放在 T1 `Preprocessor` 的接口中）
  - 第 138 行（`prefix_terms`）
  - 第 147–157 行（spelling、`query_words`、`load_surface`、`SurfaceVocab`、CLI）：
  - T4b `spelling.py` 的 `suggest` 與 `suggest_soundex` 都改成「輸入原字、回傳原字」，`suggest_soundex` 依 stem 去重；新增 `did_you_mean`
  - T1 `tokenizer.py` 新增 `Preprocessor.normalize_token(tok) -> str | None`（`process` 對單一 token 做的步驟，`process` 改成呼叫它；stopword 時回傳 `None`）
  - 新增「T4c — `surface.py`」：`load_surface(reader) -> SurfaceVocab`（`df`、`stem`），以及 `build_surface_vocab.py` 的 CLI
  - 新增 `parser.query_words(query, pre)`
  - `prefix_terms` 的註解補上「T4 已不使用，保留為 T1 接口」
- [x] F7 第 140–150 行「查詢流程」。**已回寫**：第 161 行（例子與 `surface_vocab.*`）、第 164 行（`expand` 註解）：
  - `computing*` 的例子改成 `e-mail*`（`computing*` 現在會展開成 `comput`）
  - `expand` 的註解改成「沒有 Wildcard／Soundex 時原樣回傳」
  - 補一句：「有 Wildcard／Soundex 時需要 `surface_vocab.*`」
- [x] F8（**已回寫**：第 30 行檔案配置、第 35 行 `tokenizer.py` 重構說明、第 184 行 T1「注意」）第 24–34 行「檔案配置」：加入 `surface.py`、`build_surface_vocab.py`（T4c）。第 158、162 行（T1「注意」）補充：「`HW1/output`（未 stem 版）**只**供 `build_surface_vocab.py` 讀原字詞彙，不能當查詢用的 index，也不能把它的檔案複製進 `HW2/index`（檔名相同）；建置腳本會核對 `N` 與 preprocessor，防止它被 `main.test.py` 覆蓋成小 index 之後還照樣建置」
- [x] F9 第 194–224 行 T4 一節，以及第 362 行「已知限制」。**已回寫**：
  - 第 235 行（`e-mail*` 的例子）
  - 第 237–240 行（T4a／T4b／T4c 列表）
  - 第 245–251 行（語法錯誤）
  - 第 394–395 行（已知限制：Wildcard、Soundex）：
  - 「注意」的空節點規則中（第 213 行），`computing*` 的例子改成 `e-mail*`
  - 第 362 行「Wildcard 的 prefix 不做 stem：`computing*` 對不到 `comput`」改成：「wildcard 在原字上比對，比對到的原字再轉成 stem；prefix 超出 stem 的部分時，結果會比只看 stem 時多（`computi*` 包含 `comput`）」
  - 「語法錯誤」改成與 F2 相同
  - 「只有一個 parser」的列表加上 T4c：任意位置的 `*`、`SOUNDEX()`、原字詞彙層
- [x] F10 第 284–291 行 T7。**已回寫**：第 313 行（語法與 `expand` 的錯誤）、第 316–322 行（拼字建議）：
  - 「T4b 語法」的 `ValueError` 清單與 F2 相同；另外要處理 `expand` 的 `FileNotFoundError`、`ValueError`（印出訊息、以非 0 結束）
  - 「拼字建議」改成：「對 `query_words(query, pre)` 的每個原字呼叫 `did_you_mean`（或依 §6.8.3 的原字 df 條件自行判斷），顯示原字」
  - 刪除「結果是 stem 形式」
  - 加上第一次呼叫的成本（讀 tsv + 建 k-gram）
- [x] F11 第 308、309、314 行加分表。**已回寫**：第 339、340、345 行。另外第 402 行（「待確認」中的拼字觸發條件）補上「T4c 起用原字 df」：
  - 第 6 項 Wildcard：做法改成「原字的 k-gram 篩選 + regex post-filter → stem 去重 → 依 df 取前 100」；可重用的接口改成 `surface.py`；「注意」改成「不支援 `?`／`[...]`；沒有 bigram 的 pattern（`*x*`）會掃過全部原字」；刪除「prefix 要對 stem 後的字串比對」
  - 第 7 項拼字：同 E6
  - 第 11 項 Soundex：補上 `SOUNDEX(x)` 運算子（同碼原字全部擴展成 OR，依 df 取前 100），並註明「Soundex 是為人名設計的，用在一般詞上會被高 df 的同碼詞主導（`SOUNDEX(robert)` 的第一名是 `report`）」
- [x] F12 第 330、342、371 行（驗證與繳交）：zip 是否附 `surface_vocab.*`（§8 G8）；不附的話，README 要寫 `uv run python HW2/src/build_surface_vocab.py`，以及它需要 `HW1/output`（未 stem 的 index）。**已回寫**（依 G8「附上」）：
  - 第 361 行（乾淨環境測試要靠附上的檔案）
  - 第 374 行（zip 內容新增一項：附上 `surface_vocab.*`，README 寫重建指令與前提）

  第 404 行「待確認：zip 是否附 index」不變，`surface_vocab.*` 已另外決定附上

**§6.8 實作後回寫**（§6.8.2–§6.8.5 完成後已回寫；行號是回寫後的位置）：
- [x] 總規劃中 T4c 的「計畫中」字樣與預先量測的數字：已拿掉「計畫中」，改成實測數字（§9.1.3、§9.1.4）。**已回寫**（`00-overview.md`）：
  - 第 30 行（檔案配置：T4c 已完成）、第 35 行（`normalize_token` 重構已完成，`t1.test.py` 27/27）、第 81 行（`normalize_token` 的接口註解）
  - 第 147、152 行（接口區塊的標題）、第 156 行（`load_surface` 0.54 s、75.9 MiB）、第 158–159 行（新增 `kgram`、`match_wildcard`、`soundex_groups`：0.95 s、32 MiB、0.45 s）、第 161 行（CLI：建置 4.41 s、`normalize_token` 2.78 s、tsv 14,191,438 bytes、一致性例外 0）
  - 第 244 行（T4「只有一個 parser」的 T4c：已完成）
  - 第 326 行（T7「拼字建議」：第一次呼叫的成本改成實測 1.6 s，`load_surface` 0.54 s + k-gram 1.06 s + 查詢約 30 ms；並補一句「**`did_you_mean` 首次呼叫有約 1.6 s 成本，建議只在結果很少時呼叫**」）
  - 第 343 行（加分表第 6 項：`*x*` 全掃實測 81 ms，一般 pattern 2–30 ms）、第 344 行（第 7 項：k-gram 實測 0.95 s、32.1 MiB，`did_you_mean` 第一次約 1.6 s）
  - 第 397 行（已知限制「拼字建議」：補上第一次呼叫約 1.6 s）
  - 已用 `grep` 確認總規劃中不再有「計畫中」「預先量」「待實作」「待量」字樣
- [x] `done.T1.md` 的實作紀錄（§9）新增一點：「T4c 在 `tokenizer.py` 抽出 `Preprocessor.normalize_token`，`process` 改成呼叫它，行為不變（`t1.test.py` 的 golden 值與呼叫計數證明）；`indexer.py` 不必改，index 不必重建」。**已回寫**：`done.T1.md` §9.1 第 121–124 行（另含重構前後的測試狀態 19/27 → 27/27）；§3 接口（第 30 行）補上 `normalize_token`
- [x] `done.T1.md` 與本計畫 §2、§3 中 `Preprocessor.process` 的行號（`tokenizer.py:94-106`）：重構後改成實際的行號。實際行號：`Preprocessor.normalize_token` 是 `tokenizer.py:94-104`，`Preprocessor.process` 是 `tokenizer.py:106-112`，`from_config` 往下移 6 行，變成 `tokenizer.py:113-130`（原本 `:107-124`）。**已回寫**：
  - 本計畫第 17–18 行（§2 表格的 `process`、`from_config`）、第 316 行（§6.8.1 第 3 步，註明是重構前的舊行號）、第 547 行（§6.8.6）
  - `done.T1.md` 第 48 行（§4 `from_config`）、第 57 行（§4 與總規劃的差異）、第 132 行（§9.2 行號位移）。T1 當時的舊行號保留，旁邊註明重構後的行號
- [x] 總規劃與 `done.T1.md` 補上資料層的量測：建置 4.41 s（`normalize_token` 2.78 s）、`surface_vocab.tsv` 14,191,438 bytes、`load_surface` 0.54 s／75.9 MiB、一致性例外全部是 0（§9.1.3）。**已回寫**：`00-overview.md` 第 156、161 行；`done.T1.md` 第 124 行

`done.T1.md` 的敘述（§6.8.6 列的前三項）：
- [x] §6.1 第 74 行的評分面向。**已改**：`done.T1.md` 第 74 行
- [x] §10.1 第 3 點。**已改**：`done.T1.md` 第 147 行
- [x] §10.4 第 4 點。**已改**：`done.T1.md` 第 169 行

## 10. 一頁文件素材
只根據第 9 節實作紀錄與本文件已決定的事項整理，沒有新增未量測的數字。計時都在本機 WSL2 上量測，取暖身一次後 5 次的中位數，不設門檻；「第一次呼叫」是在全新的 process 中量的單次時間（3 個 process 的中位數）。

### 10.1 主要特色
1. **一個遞迴下降 parser 支援全部語法**：單一關鍵字、自由文字、`AND`／`OR`／`NOT`、括號、`"phrase"`、`a /k b`、任意位置的 `*`（`co*tion`、`*mon`）、`SOUNDEX(robert)`，優先序 NOT > AND > OR，相鄰的運算元是隱含 AND（`linux NOT windows`）。語法錯誤（引號或括號沒有配對、只有 `*` 的 wildcard、`/0`、`SOUNDEX()` 的參數不是恰好一個含 ASCII 字母的字）拋 `ValueError` 並指出字元位置；只有 stopword 或少了運算元的地方會被移除並警告，不會讓整個 query 失敗。
2. **Phrase 與 proximity 共用「位置區間」**：phrase 的每次出現是一段區間（含 stopword 空洞，`"lord of the rings"` 是 `[p, p+3]`）；`a /k b` 的兩邊都可以是多詞 phrase（`e-mail /5 server`、`"open source" /3 "linux kernel"`），距離是兩段區間之間的間隔，不分先後，重疊不算。
3. **原字詞彙層**：index 存的是 stem 過的詞（`retriev`），使用者看不懂也打不出來。另建一份 644,523 個原字的詞彙（原字 → df、stem），stem 由 Preprocessor 自己的 `normalize_token` 算出，與 index 的一致性例外是 0。wildcard、拼字建議、Soundex 都在原字上比對，比對到的原字再轉成 stem 去查 index。
4. **Wildcard 支援任意位置的 `*`**：pattern 的固定片段（含邊界 `$`）在原字的 bigram k-gram index 上取交集篩選，再用 regex 做 post-filter（`ab*ba` 有 91 個候選，只有 3 個真的符合）；結果轉成 stem 去重，依 df 取前 100 個。`computing*` 對得到 `comput`，`*mon`、`co*tion`、`*tion*` 都可以用。
5. **拼字建議顯示原字**：`retreival` → **`retrieval`**（不是 stem `retriev`）。bigram Jaccard 篩候選、Damerau（OSA）距離排序，依 stem 去重時保留距離最小的原字（所以不會顯示 df 較高、但距離較遠的 `retrieved`）；以原字 df 判斷是否觸發「Did you mean」。只提供建議，不自動替換。
6. **SOUNDEX(x) 運算子**：把同一個 Soundex 碼的所有原字一起擴展進 query（`SOUNDEX(smith)` 同時找 `smith`、`smyth`）；`suggest_soundex` 與它共用同一份對照表。
7. **結果以暴力做法驗證**：phrase／proximity 的 10 個 query 與測試內的暴力掃描完全相同；wildcard 的 5 個 pattern 與 `fnmatch` 全掃相同；拼字建議的完整排序與測試內自己寫的 Jaccard + OSA 相同；Soundex 分組與暴力分組相同。

### 10.2 量測數據

| 數據 | 前提條件 | 比較對象 |
| --- | --- | --- |
| 測試：t4 48/48、t4_bonus 162/162、t4_surface 40/40；t1 27/27、t1_bonus 11/11、t2 19/19、t2_bonus 37/37、t3 17/17、t3_bonus 25/25 | 先寫測試再實作。T4c 改完測試、還沒改程式時，t4_bonus 是 100/162、t4_surface 34/40 | T4b 時 t4_bonus 是 99/99 |
| `"open source"` 572 篇、`"lord of the rings"` 82 篇、`e-mail /5 server` 27 篇、`linux /5 kernel` 192 篇 | stop+stem index，N = 34,786 | 每個結果都與測試內的暴力掃描相同；`"open source"` 是 `open /1 source`（603 篇）的子集 |
| `linux /5 kernel` 中 3 篇只靠「kernel 在 linux 前面」命中 | 由暴力掃描分別算正、反方向找出 | 若只比對單一方向，這 3 篇會漏掉 |
| `position_match("open source")` 12.2 ms；`linux /5 kernel` 1.7 ms；`e-mail /5 server` 25.6 ms | 已暖身；每個 token 只讀一次 postings | `get_postings` × 2 分別是 10.1 ms、1.3 ms；高 df 時建 doc → positions 對照的成本與讀 postings 相當 |
| 原字詞彙：644,523 個原字、stopword 189 個；tsv 14,191,438 bytes；建置 4.41 s（其中 `normalize_token` 2.78 s） | 來源是未 stem 的 HW1 index | 一致性例外 0（stem 都在 index、index 的 573,233 個 term 都有原字、df 上下界） |
| **`did_you_mean` 第一次呼叫約 1.6 s**（`load_surface` 0.54 s + 建原字 k-gram 1.06 s + 查詢約 30 ms） | 新 process，lexicon 已載入（讀 lexicon 另需 0.39 s）；峰值 RSS 503 MB | 同一個 process 的第二次呼叫 27 ms |
| 原字 k-gram index 建置 0.95 s，32.1 MiB（峰值 33.0 MiB）；`load_surface` 75.9 MiB | 每個 reader 一次；`tracemalloc` 只算 Python 配置 | T4b 的 stem 版 k-gram：0.95 s、28.8 MiB（已刪除，不會同時存在兩份） |
| `suggest` 9.0–45.2 ms（`a`、`linux`、`retreival`、`computer`） | k-gram 已建好 | T4b 的 stem 版 9.3–31.6 ms |
| `suggest('retreival')` 前三名 `retrieval`（81）、`retrial`（2）、`retreat`（178）；觸發（81 ≥ 1 × 10） | 原字 df；同 stem 的 `retrieved`（140）、`retrieve`（138）因距離較大被去重 | T4b 的 stem 版前三名是 `retreiv`、`retrial`、`retriev`（stem 形式） |
| `linux`（997）的第一名 `linus`（28）不觸發；`kernal` → `kernel`、`computr` → `computer`、`recieve` → `receive`、`goverment` → `government`、`informaton` → `information` 都觸發 | 原字 df | — |
| wildcard：`*mon` 2.3 ms（276 個 stem）、`co*tion` 4.6 ms（528）、`*tion*` 12.8 ms（7,482）、`a*` 30.0 ms（31,236）、`comput*` 1.5 ms（64） | 已暖身，k-gram 已建好；取前 100 | T4b 的 `prefix_terms` 版：`comput*` 0.027 ms、`a*` 10–11 ms，但只支援結尾的 `*` |
| `*x*`（沒有 bigram）81.3 ms | regex 掃過全部 644,523 個原字 | — |
| Soundex：6,361 種碼，最大一組 1,240 個原字；對照表建置 0.45 s；`expand(SOUNDEX(robert))` 0.12 ms；`suggest_soundex` 0.002 ms | 只收純 ASCII 字母的原字；每個 reader 建一次 | T4b 的 stem 版對照表 0.46 s（已刪除） |

### 10.3 遇到的困難與解法
- **proximity 的兩邊可能是多詞**：`e-mail` 經過 `process` 會變成 `e`、`mail` 兩個 token，原本「兩個位置差 ≤ k」的定義不適用。解法：兩邊都視為 phrase，先各自找出位置區間，再算兩段區間之間的間隔；單一 token 是長度為 0 的區間，所以舊定義是新定義的特例。
- **方向**：`a /5 b` 很容易只寫成「b 在 a 後面」。解法：兩個方向都比，並在測試中用暴力掃描分別找出只靠反方向命中的文件（`e-mail /5 server` 的 doc 1400、`linux /5 kernel` 的 3 篇），確認它們都在結果中。
- **讀 postings 很貴**：`get_postings` 每次都重新開檔並解出全部 positions。解法：每個不同的 token 只讀一次（Near 兩側、`"new new york"` 中重複的 token 共用），依 df 由小到大讀，交集一變空就停；測試用 spy 檢查呼叫次數。
- **stopword 會讓運算元消失**：`the /3 linux`、`"open source" /3 the` 的一側是空的。解法：退化成另一側並警告；另一側是多詞時保留 phrase，不轉成一般的 AND，以免失去相鄰條件。
- **index 只有 stem，使用者看到的卻是原字**：T4b 的拼字建議是 `retriev`，`computing*` 也對不到 `comput`。解法：另建原字詞彙層，所有「和使用者的字比對」的功能都在原字上做，最後才轉成 stem 查 index。原字的 stem 一定要和 index 用同一段程式算：直接對單一原字呼叫 `process` 會因為 spaCy 重新切字而有 631 個不一致，所以把 `process` 的單 token 步驟抽成 `normalize_token`，並用 golden 值證明 `process` 的行為不變。
- **同一個 stem 的原字會擠滿建議清單**：`retreival` 的候選有 `retrieval`、`retrieved`、`retrieve`，改哪一個 query 都一樣。解法：依 stem 去重，保留距離最小的原字；與輸入同 stem 的候選（`retreived`）直接排除，因為改了也不會改變結果。
- **k-gram 只是篩選**：`ab*ba` 的 bigram 也全部出現在 `aba` 中。解法：k-gram 交集之後一定再用 regex 完整比對；regex 只把 `*` 當萬用字元（不用 `fnmatch`，它會把 `?`、`[...]` 也當萬用字元）。
- **測試的預期值不能來自被測程式**：解法：測試內另寫暴力版本，寫法刻意和實作不同（phrase：每篇文件建「位置 → term」表、掃過每個起點；wildcard：`fnmatch` 全掃；拼字：全掃算 Jaccard、完整 DP 表算 OSA；Soundex：自己分組）。

### 10.4 限制
- **Soundex 是為人名設計的，用在一般檢索中效果有限**：它只看第一個字母加上前三個子音的類別。這套編碼原本用來把拼法不同的同音人名歸成一組（`robert`／`rupert`、`smith`／`smyth`、`stephen`／`steven` 同碼，實測 `SOUNDEX()` 都能互相找到），但一般詞的碰撞非常多：原字詞彙只有 6,361 種碼，最大的一組有 1,240 個原字。`SOUNDEX(robert)` 展開成 214 個 stem，df 最高的是 `report`、`refer`，`robert` 只排第 3，`rupert` 排第 20，結果會被一般詞主導；`suggest_soundex('robert')` 的前 5 名是 `report`、`referred`、`reproduced`、`reproduction`、`roberto`，只依 df 排序，沒有判斷「像不像」。反過來，同音但第一個字母不同（`catherine` C365／`kathryn` K365），或子音類別不同（`thompson` T512／`thomson` T525）時，也對不到。而且只處理 ASCII 字母。所以 Soundex 只能當輔助功能。
- **`did_you_mean` 第一次呼叫的成本**：第一次呼叫要讀 `surface_vocab.tsv`（0.54 s）並建原字 k-gram index（1.06 s），在新的 process 中約 **1.6 s**（lexicon 已載入的情況；之後每次約 10–45 ms），記憶體約 76 + 32 MiB。單次 CLI 查詢每次都要付這個成本，所以建議 T7 只在結果很少時才呼叫。第一次使用 wildcard 或 `SOUNDEX()` 也要付 `load_surface` 的 0.54 s（wildcard 另加 k-gram 的 1 s，SOUNDEX 另加對照表的 0.45 s）。
- **拼字建議不認識語意**：正確的罕見詞也可能觸發，例如人名 `linus`（28）會被建議成 `links`（9,251）。短字的對調（`teh` → `the`）在 bigram Jaccard 下篩不進候選，而且 `the` 是 stopword，本來就會被排除。語料中的錯字本身也在詞彙裡（`retreival` 的 df 是 1），所以觸發條件除了「df == 0」還要比較 df 差距。只提供建議，不自動替換。
- **wildcard 會截斷**：超過 100 個 stem 時只取 df 最高的 100 個（`a*` 的 31,236 個只用 100 個），df 低的 term 不會被比對到；會發出警告，但結果不完整。
- **wildcard 在原字上比對、在 stem 上檢索**：比對到的原字再轉成 stem，所以結果可能包含形式上不符合 pattern 的 stem（`computers*` 包含 `comput`，因為 `computers` 被 stem 成 `comput`），而 `comput` 又會比對到 `computing`、`computation` 等文件。只有 `*` 是萬用字元，不支援 `?`、`[...]`。沒有任何 bigram 的 pattern（`*x*`）要掃過全部原字（約 81 ms）。
- **原字詞彙需要另外建置**：`surface_vocab.*` 由未 stem 的 HW1 index 建出，TA 手上不一定有，所以繳交時附上（13.5 MiB）。檔案不存在時，含 wildcard／SOUNDEX 的 query 會拋 `FileNotFoundError`；一般 query 不受影響（`expand` 不讀檔）。
- **選用功能的性質**：T4b／T4c 的語法都是加法，一般文字的 query 結果與 T4a 相同（t4 48/48）。champion list（T2／T3 建置、T6 選用、預設關閉）不屬於 T4，T4 不使用也不依賴它；champion 是不精確的 top-k，它和 Phrase／Near 一起使用時的排序品質沒有量測，是否開放由 T6 決定。拼字建議、Soundex 也一樣是選用的輔助功能。
- **proximity 的距離定義要寫在文件中**：距離以 index 的 token 位置計算，含 stopword 空洞（`linux the kernel` 的間隔是 2），所以使用者看到的距離和「中間隔了幾個有意義的詞」不同；兩段區間重疊不算命中，`a /5 b /5 c` 這種串接不支援（第二個 `/5` 的左側視為空的，退化並警告）。`SOUNDEX(x)` 不能當 Near 的一側。
- **計時只代表本機的單次呼叫**：高 df 詞（`e-mail /5 server`）的時間在不同次執行間波動很大（T4b 時量到 25–66 ms），沒有量冷磁碟，也沒有量整個 CLI 查詢的時間。
