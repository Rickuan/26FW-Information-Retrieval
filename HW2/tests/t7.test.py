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

from search import build_arg_parser, format_hits, main as search_main, search_query
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

    # 2. 正常查詢與排序
    total += 1
    passed += run("真實索引: 'Microsoft' 排序與分數健全性", lambda: (
        len(hits := search_query("Microsoft", reader, pre)) > 2000 and
        hits[0][0] == 28281 and
        0 < hits[0][1] <= 1.0 and
        all(hits[i][1] >= hits[i + 1][1] for i in range(len(hits) - 1)),
        f"命中 {len(hits)} 篇，top-1 doc={hits[0][0]}, score={hits[0][1]:.6f}"
    ))

    total += 1
    passed += run("複合查詢: 'open source AND Linux'", lambda: (
        len(hits := search_query("open source AND Linux", reader, pre)) == 294 and
        all(hits[i][1] >= hits[i + 1][1] for i in range(len(hits) - 1)),
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
    print(f"Test Summary: {passed}/{total} passed")
    print("=" * 60)
    if passed == total:
        print("\n✔ ALL STEP 7.2 & 7.3 TESTS PASSED!\n")
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


if __name__ == "__main__":
    sys.exit(main())
