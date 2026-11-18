"""t7.test.py — T7 CLI 查詢介面與端到端搜尋引擎測試

執行：
  uv run python HW2/tests/t7.test.py
"""
from __future__ import annotations

import io
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
INDEX = ROOT / "index"
sys.path.insert(0, str(SRC))

from search import (
    build_arg_parser,
    format_hits,
    main as search_main,
    search_query,
    suggest_spelling_corrections,
)
from tokenizer import Preprocessor
from writer import IndexReader

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


def check(name: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))
    return condition


def run(name: str, fn) -> bool:
    try:
        cond, detail = fn()
    except Exception as e:
        return check(name, False, f"{type(e).__name__}: {e}")
    return check(name, cond, detail)


def main() -> int:
    total = passed = 0
    reader = IndexReader(str(INDEX))
    pre = Preprocessor.from_config(reader.get_metadata()["preprocessor"])

    print("=" * 60)
    print("T7 端到端 search_query() 測試")
    print("=" * 60)

    # 1. 空字串與邊界
    total += 1
    passed += run("空字串查詢回傳 []", lambda: (
        search_query("", reader, pre) == [],
        "search_query('') == []"
    ))

    total += 1
    passed += run("純空白查詢回傳 []", lambda: (
        search_query("   ", reader, pre) == [],
        "search_query('   ') == []"
    ))

    total += 1
    passed += run("純 NOT 查詢回傳 []", lambda: (
        search_query("NOT linux", reader, pre) == [],
        "search_query('NOT linux') == []"
    ))

    total += 1
    passed += run("不存在詞項回傳 []", lambda: (
        search_query("nonexistentwordxyz123", reader, pre) == [],
        "search_query('nonexistentwordxyz123') == []"
    ))

    def _is_sorted(hits):
        for i in range(len(hits) - 1):
            r_curr = round(hits[i][1], 6)
            r_next = round(hits[i + 1][1], 6)
            if r_curr < r_next or (r_curr == r_next and hits[i][0] >= hits[i + 1][0]):
                return False
        return True

    # 2. 正常查詢與排序
    total += 1
    passed += run("真實索引: 'Microsoft' 排序與分數健全性", lambda: (
        len(hits := search_query("Microsoft", reader, pre)) > 2000 and
        hits[0][0] == 28281 and
        0 < hits[0][1] <= 1.0 and
        _is_sorted(hits),
        f"命中 {len(hits)} 篇，top-1 doc={hits[0][0]}, score={hits[0][1]:.6f}"
    ))

    total += 1
    passed += run("複合查詢: 'open source AND Linux'", lambda: (
        len(hits := search_query("open source AND Linux", reader, pre)) == 294 and
        _is_sorted(hits),
        f"命中 {len(hits)} 篇，top-1 doc={hits[0][0]}, score={hits[0][1]:.6f}"
    ))

    # 3. top_k 截斷與參數驗證
    total += 1
    passed += run("top_k 截斷限制 (--top-k 5)", lambda: (
        len(hits := search_query("Microsoft", reader, pre, top_k=5)) == 5 and
        hits[0][0] == 28281,
        f"截斷後長度 {len(hits)} 筆"
    ))

    total += 1
    passed += run("top_k <= 0 拋出 ValueError", lambda: (
        _test_top_k_invalid(reader, pre)
    ))

    # 4. 語法錯誤拋出 ValueError
    total += 1
    passed += run("語法錯誤（未封閉引號）拋出 ValueError", lambda: (
        _test_syntax_error(reader, pre)
    ))

    # 5. SMART scheme 與加分參數
    total += 1
    passed += run("SMART 方案 'bnn.bnn' 查詢成功", lambda: (
        len(hits := search_query("Microsoft", reader, pre, scheme="bnn.bnn", top_k=3)) == 3,
        f"bnn.bnn top-1 score={hits[0][1]:.6f}"
    ))

    total += 1
    passed += run("Champion List 不精確 top-k (champion_r=50)", lambda: (
        0 < len(hits := search_query("Linux", reader, pre, champion_r=50)) <= 50,
        f"champion_r=50 命中 {len(hits)} 篇"
    ))

    print("\n" + "=" * 60)
    print("T7 CLI 介面與格式化輸出 (Step 7.3) 測試")
    print("=" * 60)

    # 6. format_hits 格式化
    total += 1
    passed += run("format_hits 空清單回傳空字串", lambda: (
        format_hits([]) == "",
        "format_hits([]) == ''"
    ))

    total += 1
    passed += run("format_hits 精準 6 位小數", lambda: (
        format_hits([(123, 0.5), (456, 0.12345678)]) == "123 0.500000\n456 0.123457",
        "format_hits 包含四捨五入與空白分隔"
    ))

    # 7. CLI main 執行與輸出捕獲
    total += 1
    passed += run("CLI main 單一查詢 stdout 輸出", lambda: (
        _test_cli_single(reader)
    ))

    total += 1
    passed += run("CLI main 寫入 -o 輸出檔", lambda: (
        _test_cli_output_file()
    ))

    total += 1
    passed += run("CLI main 批次 --queries 查詢", lambda: (
        _test_cli_batch_queries()
    ))

    total += 1
    passed += run("CLI main 非法索引目錄回傳 exit 1", lambda: (
        search_main(["--index-dir", "nonexistent_dir_xyz", "test"]) == 1,
        "nonexistent index dir returned 1"
    ))

    total += 1
    passed += run("CLI main 語法錯誤回傳 exit 1", lambda: (
        search_main(["--index-dir", str(INDEX), '"unclosed quote']) == 1,
        "syntax error returned 1"
    ))

    print("\n" + "=" * 60)
    print("T7 拼字建議與錯誤處理 (Step 7.4) 測試")
    print("=" * 60)

    total += 1
    passed += run("suggest_spelling_corrections 正確詞項回傳 []", lambda: (
        suggest_spelling_corrections("Microsoft", reader, pre) == [],
        "正確單詞無建議"
    ))

    total += 1
    passed += run("suggest_spelling_corrections 錯字回傳原字建議", lambda: (
        len(suggs := suggest_spelling_corrections("retreival", reader, pre)) == 1 and
        suggs[0][0] == "retreival" and
        "retrieval" in suggs[0][1],
        f"retreival -> {suggs[0][1]}"
    ))

    total += 1
    passed += run("CLI 錯字查詢觸發 stderr 拼字建議且 stdout 為空", lambda: (
        _test_cli_spelling_stderr()
    ))

    print("\n" + "=" * 60)
    print("T7 整合端到端與子行程 (Step 7.5) 測試")
    print("=" * 60)

    total += 1
    passed += run("CLI 參數防呆: 缺少 query 與 --queries 拋出 SystemExit", lambda: (
        _test_cli_missing_args()
    ))

    total += 1
    passed += run("CLI 參數防呆: 同時提供 query 與 --queries 拋出 SystemExit", lambda: (
        _test_cli_conflicting_args()
    ))

    total += 1
    passed += run("CLI 獨立 Subprocess 行程執行驗證", lambda: (
        _test_subprocess_cli()
    ))

    print("\n" + "=" * 60)
    print(f"Test Summary: {passed}/{total} passed")
    print("=" * 60)
    if passed == total:
        print("\n✔ ALL TESTS PASSED!\n")
        return 0
    else:
        print("\n❌ SOME TESTS FAILED!\n")
        return 1


def _test_top_k_invalid(reader: IndexReader, pre: Preprocessor) -> tuple[bool, str]:
    for invalid_k in [0, -1]:
        try:
            search_query("test", reader, pre, top_k=invalid_k)
            return False, f"top_k={invalid_k} did not raise ValueError"
        except ValueError:
            pass
    return True, "top_k <= 0 正確拋出 ValueError"


def _test_syntax_error(reader: IndexReader, pre: Preprocessor) -> tuple[bool, str]:
    try:
        search_query('"open source', reader, pre)
        return False, "Unclosed quote did not raise ValueError"
    except ValueError:
        return True, "未配對引號正確拋出 ValueError"


def _test_cli_single(reader: IndexReader) -> tuple[bool, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        ret = search_main(["--index-dir", str(INDEX), "--top-k", "3", "Microsoft"])
    out = buf.getvalue().strip().splitlines()
    if ret != 0:
        return False, f"main() returned {ret}"
    if len(out) != 3:
        return False, f"expected 3 lines, got {len(out)}"
    first_doc, first_score = out[0].split()
    if first_doc != "28281" or float(first_score) <= 0:
        return False, f"unexpected first line: {out[0]}"
    return True, f"stdout output {len(out)} lines, top-1={out[0]}"


def _test_cli_output_file() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "sub" / "result.txt"
        ret = search_main(["--index-dir", str(INDEX), "--top-k", "2", "-o", str(out_path), "Microsoft"])
        if ret != 0:
            return False, f"main() returned {ret}"
        if not out_path.is_file():
            return False, "output file was not created"
        lines = out_path.read_text(encoding="utf-8").strip().splitlines()
        if len(lines) != 2:
            return False, f"expected 2 lines in file, got {len(lines)}"
        return True, f"file created with {len(lines)} lines"


def _test_cli_batch_queries() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmpdir:
        q_file = Path(tmpdir) / "queries.txt"
        q_file.write_text("Microsoft\n\nNOT linux\nopen source AND Linux\n", encoding="utf-8")
        out_dir = Path(tmpdir) / "out_queries"

        ret = search_main([
            "--index-dir", str(INDEX),
            "--top-k", "3",
            "--queries", str(q_file),
            "--output-dir", str(out_dir),
        ])
        if ret != 0:
            return False, f"main() returned {ret}"

        # 應產生 query_1.txt, query_3.txt, query_4.txt (query 2 是空行跳過)
        q1 = out_dir / "query_1.txt"
        q3 = out_dir / "query_3.txt"
        q4 = out_dir / "query_4.txt"
        if not q1.is_file() or not q3.is_file() or not q4.is_file():
            return False, "one or more batch query files missing"

        q1_lines = q1.read_text(encoding="utf-8").strip().splitlines()
        q3_lines = q3.read_text(encoding="utf-8").strip()  # NOT linux 應為空
        q4_lines = q4.read_text(encoding="utf-8").strip().splitlines()

        if len(q1_lines) != 3:
            return False, f"q1 expected 3 lines, got {len(q1_lines)}"
        if q3_lines != "":
            return False, f"q3 expected empty, got {q3_lines!r}"
        if len(q4_lines) != 3:
            return False, f"q4 expected 3 lines, got {len(q4_lines)}"
        return True, f"batch files generated successfully (q1={len(q1_lines)}, q3=empty, q4={len(q4_lines)})"


def _test_cli_spelling_stderr() -> tuple[bool, str]:
    # 測試 1: 0 命中詞 computtr -> stdout 為空，stderr 提示建議
    buf_out = io.StringIO()
    buf_err = io.StringIO()
    with redirect_stdout(buf_out), redirect_stderr(buf_err):
        ret = search_main(["--index-dir", str(INDEX), "computtr"])
    if ret != 0:
        return False, f"expected ret=0, got {ret}"
    if buf_out.getvalue().strip() != "":
        return False, f"expected empty stdout for computtr, got {buf_out.getvalue()!r}"
    if "Did you mean for 'computtr':" not in buf_err.getvalue() or "computer" not in buf_err.getvalue():
        return False, f"expected suggestion for computtr in stderr, got {buf_err.getvalue()!r}"

    # 測試 2: 罕見錯字 retreival (< 20 命中) -> stdout 有 11 筆，stderr 仍提供建議
    buf_out2 = io.StringIO()
    buf_err2 = io.StringIO()
    with redirect_stdout(buf_out2), redirect_stderr(buf_err2):
        ret2 = search_main(["--index-dir", str(INDEX), "retreival"])
    if ret2 != 0:
        return False, f"expected ret2=0, got {ret2}"
    if len(buf_out2.getvalue().strip().splitlines()) != 11:
        return False, f"expected 11 results for retreival, got {len(buf_out2.getvalue().strip().splitlines())}"
    if "Did you mean for 'retreival':" not in buf_err2.getvalue() or "retrieval" not in buf_err2.getvalue():
        return False, f"expected suggestion for retreival in stderr, got {buf_err2.getvalue()!r}"

    return True, "0 命中 (computtr) 與罕見錯字 (retreival) 皆正確觸發 stderr 建議"


def _test_cli_missing_args() -> tuple[bool, str]:
    buf = io.StringIO()
    with redirect_stderr(buf):
        try:
            search_main(["--index-dir", str(INDEX)])
            return False, "did not exit when arguments missing"
        except SystemExit as e:
            if e.code == 0:
                return False, "exit code was 0 instead of non-zero"
    return True, "缺少參數正確引發 SystemExit(2)"


def _test_cli_conflicting_args() -> tuple[bool, str]:
    buf = io.StringIO()
    with redirect_stderr(buf):
        try:
            search_main(["--index-dir", str(INDEX), "--queries", "fake.txt", "Microsoft"])
            return False, "did not exit when conflicting arguments provided"
        except SystemExit as e:
            if e.code == 0:
                return False, "exit code was 0 instead of non-zero"
    return True, "衝突參數正確引發 SystemExit(2)"


def _test_subprocess_cli() -> tuple[bool, str]:
    import subprocess
    cmd = [
        sys.executable,
        str(SRC / "search.py"),
        "--index-dir", str(INDEX),
        "--top-k", "2",
        "Microsoft",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return False, f"returncode {res.returncode}, stderr: {res.stderr}"
    lines = res.stdout.strip().splitlines()
    if len(lines) != 2:
        return False, f"expected 2 lines, got {len(lines)}"
    return True, f"subprocess exit 0, output: {lines}"


if __name__ == "__main__":
    sys.exit(main())
