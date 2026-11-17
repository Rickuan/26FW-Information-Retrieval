"""t7.test.py — T7 CLI 查詢介面與端到端搜尋引擎測試

執行：
  uv run python HW2/tests/t7.test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
INDEX = ROOT / "index"
sys.path.insert(0, str(SRC))

from search import search_query
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
    print(f"Test Summary: {passed}/{total} passed")
    print("=" * 60)
    if passed == total:
        print("\n✔ ALL STEP 7.2 TESTS PASSED!\n")
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


if __name__ == "__main__":
    sys.exit(main())
