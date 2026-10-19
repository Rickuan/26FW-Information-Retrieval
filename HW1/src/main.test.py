"""main.test.py — Step 6 main.py CLI 管線整合測試

測試涵蓋：
  1. CLI 參數與說明解析（--help、未知指令、非法路徑防呆）
  2. Memory 模式端到端建置（--limit 100），驗證 6 項產物齊全與內容格式
  3. SPIMI 模式端到端建置（--limit 100），驗證記憶體與磁碟歸併正確性
  4. 磁碟布林檢索 query 指令（單詞、雙詞、多詞、停用詞、不存在詞、--no-skips）
  5. eval-skips 評測指令與報表產出（HW1/logs/skip_eval_report.md）

執行方式：
  uv run python HW1/src/main.test.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# 加入原始碼目錄
SRC_DIR = Path(__file__).parent
sys.path.insert(0, str(SRC_DIR))

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


def check(name: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))
    if not condition:
        raise AssertionError(f"Check failed: {name} ({detail})")
    return condition


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """執行 main.py CLI 並捕獲 stdout/stderr。"""
    cmd = [sys.executable, str(SRC_DIR / "main.py"), *args]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR)
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def test_cli_parsing():
    print("\n=== Part 1: CLI 說明與錯誤處理驗證 ===")
    
    # 1.1 --help
    res = run_cli("--help")
    check("main.py --help 正常回傳 0", res.returncode == 0)
    check("help 包含 build, query, eval-skips 子命令", all(cmd in res.stdout for cmd in ["build", "query", "eval-skips"]))

    # 1.2 build --help
    res_build = run_cli("build", "--help")
    check("build --help 包含必要選項", all(opt in res_build.stdout for opt in ["--input", "--output", "--mode", "--limit"]))

    # 1.3 query --help
    res_query = run_cli("query", "--help")
    check("query --help 包含 terms 與 options", "terms" in res_query.stdout and "--show-docs" in res_query.stdout)

    # 1.4 非法檔案路徑
    res_err = run_cli("build", "--input", "nonexistent_file.warc")
    check("非法 WARC 路徑優雅報錯（回傳 1）", res_err.returncode == 1)
    check("錯誤訊息友善無 Python Traceback", "錯誤：找不到輸入語料檔案" in res_err.stderr and "Traceback" not in res_err.stderr)


def test_build_and_outputs():
    print("\n=== Part 2: build 端到端索引建置與產物驗證 ===")
    tmp_out = Path(tempfile.mkdtemp(prefix="ir_test_build_"))
    try:
        # 2.1 全記憶體模式建置 (limit 100)
        res = run_cli("build", "--limit", "100", "--output", str(tmp_out))
        check("build (memory, limit=100) 成功執行", res.returncode == 0, f"code={res.returncode}")
        check("終端輸出包含摘要日誌 (Summary)", "索引建置完成摘要" in res.stdout and "Peak RSS" in res.stdout)

        # 2.2 驗證 6 項產物存在且大小非空
        expected_files = [
            "dictionary.txt",
            "postings.txt",
            "metadata.json",
            "doc_map.json",
            "lexicon.tsv",
            "postings.bin",
        ]
        for fname in expected_files:
            fpath = tmp_out / fname
            check(f"產物存在：{fname}", fpath.is_file() and fpath.stat().st_size > 0)

        # 2.3 檢查 metadata.json
        with (tmp_out / "metadata.json").open("r", encoding="utf-8") as f:
            meta = json.load(f)
        check("metadata.json 包含 N == 100", meta.get("N") == 100)
        check("metadata.json 包含 vocab_size > 0", meta.get("vocab_size", 0) > 0)
        check("metadata.json 包含 preprocessor 配置", "stem" in meta.get("preprocessor", {}))

        # 2.4 檢查 dictionary.txt 與 postings.txt 行數對齊
        with (tmp_out / "dictionary.txt").open("r", encoding="utf-8") as f:
            n_dict = sum(1 for _ in f)
        with (tmp_out / "postings.txt").open("r", encoding="utf-8") as f:
            n_post = sum(1 for _ in f)
        check("dictionary 行數 == postings 行數 == vocab_size", n_dict == n_post == meta["vocab_size"])

    finally:
        shutil.rmtree(tmp_out, ignore_errors=True)


def test_spimi_build():
    print("\n=== Part 3: SPIMI 外排序分塊模式建置驗證 ===")
    tmp_spimi = Path(tempfile.mkdtemp(prefix="ir_test_spimi_"))
    try:
        # 故意設定極小 block-size-mb 觸發多次分塊 flush 與多路歸併
        res = run_cli("build", "--limit", "100", "--mode", "spimi", "--block-size-mb", "1", "--output", str(tmp_spimi))
        check("build (spimi, limit=100) 成功執行", res.returncode == 0)
        check("輸出包含多路歸併日誌", "多路歸併" in res.stdout)

        for fname in ["dictionary.txt", "postings.txt", "metadata.json", "doc_map.json", "lexicon.tsv", "postings.bin"]:
            fpath = tmp_spimi / fname
            check(f"SPIMI 產物存在：{fname}", fpath.is_file() and fpath.stat().st_size > 0)

    finally:
        shutil.rmtree(tmp_spimi, ignore_errors=True)


def test_query_command():
    print("\n=== Part 4: query 磁碟索引檢索驗證 ===")
    tmp_out = Path(tempfile.mkdtemp(prefix="ir_test_query_"))
    try:
        # 先建置小索引供查詢
        run_cli("build", "--limit", "100", "--output", str(tmp_out))

        # 4.1 雙詞 AND 查詢 (預設 Skip)
        res_skip = run_cli("query", "game", "play", "--index-dir", str(tmp_out), "--show-docs", "5")
        check("query 雙詞成功回傳", res_skip.returncode == 0)
        check("使用 Skip Pointer 比對模式", "檢索結果 (Skip Pointer)" in res_skip.stdout)
        check("輸出前 K 篇文件表格", "TREC ID" in res_skip.stdout and "URL" in res_skip.stdout)

        # 4.2 雙詞 AND 查詢 (--no-skips)
        res_basic = run_cli("query", "game", "play", "--index-dir", str(tmp_out), "--no-skips")
        check("query --no-skips 成功執行", res_basic.returncode == 0)
        check("使用 Basic Linear Scan 比對模式", "檢索結果 (Basic Linear Scan)" in res_basic.stdout)

        # 4.3 多詞 AND 查詢 (3 詞)
        res_multi = run_cli("query", "game", "play", "home", "--index-dir", str(tmp_out))
        check("query 3 詞成功回傳", res_multi.returncode == 0)

        # 4.4 停用詞查詢防呆
        res_stop = run_cli("query", "the", "game", "--index-dir", str(tmp_out))
        check("停用詞自動提示並回傳 0 篇", "停用詞" in res_stop.stdout and "匹配文件數：0 篇" in res_stop.stdout)

        # 4.5 不存在詞彙防呆
        res_none = run_cli("query", "nonexistent123xyz", "game", "--index-dir", str(tmp_out))
        check("未登錄詞彙自動提示並回傳 0 篇", "不存在於索引中" in res_none.stdout and "匹配文件數：0 篇" in res_none.stdout)

    finally:
        shutil.rmtree(tmp_out, ignore_errors=True)


def test_eval_skips_command():
    print("\n=== Part 5: eval-skips 獨立評測命令驗證 ===")
    tmp_report = Path(tempfile.mktemp(suffix=".md", prefix="skip_eval_"))
    try:
        res = run_cli("eval-skips", "--limit", "100", "--output-report", str(tmp_report))
        check("eval-skips 指令成功執行", res.returncode == 0)
        check("終端輸出 Markdown 表格", "### M5 Skip Pointer 效能評測報告" in res.stdout)
        check("評測報告檔案正確產出", tmp_report.is_file() and tmp_report.stat().st_size > 0)
        
        content = tmp_report.read_text(encoding="utf-8")
        check("報表內容包含 5 組評測分類與加速比", "高頻 + 高頻" in content and "加速比" in content)

    finally:
        if tmp_report.exists():
            tmp_report.unlink()


def main():
    test_cli_parsing()
    test_build_and_outputs()
    test_spimi_build()
    test_query_command()
    test_eval_skips_command()
    print(f"\n\033[32m✔ Step 6 所有端到端整合測試全數通過！\033[0m\n")


if __name__ == "__main__":
    main()
