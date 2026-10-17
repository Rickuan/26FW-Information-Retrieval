"""skip_builder.test.py — M5 Skip Builder & AND Query 測試

包含兩大部分：
  Part 1：單元測試 — 邊界長度 (P < 9, P >= 9)、SkipPointer 目標正確性、物件引用不複製、
                     基本與 skip 交集結果完全一致性、比較次數驗證、Preprocessor 正規化。
  Part 2：整合測試 — 載入 WARC 資料建置 Indexer，量測 Peak RSS 與建置時間，
                     執行 5 組代表性 Query Pair，輸出 Markdown 格式比較表格。

執行方式：
  uv run python HW1/src/skip_builder.test.py                      # 執行 Part 1 單元測試 + 快速整合 (預設 500 篇)
  uv run python HW1/src/skip_builder.test.py ../dataset/04.warc 1000 # 指定 WARC 與篇數
  uv run python HW1/src/skip_builder.test.py ../dataset/04.warc 0    # 全量 35,000 篇
"""
from __future__ import annotations

import math
import os
import random
import sys
import time
from array import array
from pathlib import Path

# 加入模組路徑
sys.path.insert(0, str(Path(__file__).parent))

from indexer import Indexer, Posting
from skip_builder import (
    MIN_SKIP_LEN,
    PostingWithSkip,
    SkipBuilder,
    SkipPointer,
    and_query,
    build_skip_list,
    intersect_basic,
    intersect_with_skips,
)
from tokenizer import Preprocessor

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


def check(name: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))
    if not condition:
        raise AssertionError(f"Check failed: {name} ({detail})")
    return condition


# ---------------------------------------------------------------------------
# Part 1: 單元測試
# ---------------------------------------------------------------------------

def test_unit_build_skip_list():
    print("\n=== Part 1.1: build_skip_list 結構與規則驗證 ===")

    # 1. P < 9 (邊界測試: P=0, 1, 8)
    for p_len in [0, 1, 5, 8]:
        dummy_postings = [Posting(doc_num=i * 2 + 1, tf=1, positions=array("I", [i])) for i in range(p_len)]
        res = build_skip_list(dummy_postings)
        check(f"P={p_len} (< 9) 全部節點 skip is None", all(p.skip is None for p in res))
        check(f"P={p_len} 長度維持不變", len(res) == p_len)

    # 2. P = 9 (L = 3)
    p9 = [Posting(doc_num=i * 10, tf=1, positions=array("I", [i])) for i in range(9)]
    res9 = build_skip_list(p9)
    # L=3, indices with skip: 0 (-> 3), 3 (-> 6). Index 6 + 3 = 9 not < 9
    # count == floor((9 - 1) / 3) = 2
    skips_count_9 = sum(1 for p in res9 if p.skip is not None)
    expected_count_9 = (9 - 1) // math.isqrt(9)
    check("P=9 時帶 skip 節點數 == floor((P-1)/L)", skips_count_9 == expected_count_9 == 2)
    check("P=9 index 0 的 skip 指向 index 3", res9[0].skip.target_index == 3 and res9[0].skip.target_doc_num == p9[3].doc_num)
    check("P=9 index 3 的 skip 指向 index 6", res9[3].skip.target_index == 6 and res9[3].skip.target_doc_num == p9[6].doc_num)
    check("P=9 index 6 的 skip 為 None（6+3 不小於 9）", res9[6].skip is None)
    check("P=9 其他非倍數節點 skip 為 None", all(res9[i].skip is None for i in [1, 2, 4, 5, 7, 8]))

    # 3. P = 10 (L = 3) -> floor((10-1)/3) = 3 (0->3, 3->6, 6->9)
    p10 = [Posting(doc_num=i * 10, tf=1, positions=array("I", [i])) for i in range(10)]
    res10 = build_skip_list(p10)
    skips_count_10 = sum(1 for p in res10 if p.skip is not None)
    check("P=10 時帶 skip 節點數 == floor((P-1)/L) == 3", skips_count_10 == 3)
    check("P=10 index 6 skip 指向 index 9", res10[6].skip.target_index == 9 and res10[6].skip.target_doc_num == p10[9].doc_num)

    # 4. 任意長度通用公式驗證 (P=16, 25, 100, 105)
    for p_len in [16, 25, 100, 105]:
        plist = [Posting(doc_num=i * 3 + 1, tf=1, positions=array("I", [i])) for i in range(p_len)]
        res = build_skip_list(plist)
        l_val = math.isqrt(p_len)
        expected_cnt = (p_len - 1) // l_val
        actual_cnt = sum(1 for p in res if p.skip is not None)
        check(f"P={p_len} (L={l_val}) skip 節點數 == {expected_cnt}", actual_cnt == expected_cnt)

        # 驗證每個 skip 指標目標正確性
        for i, p in enumerate(res):
            if p.skip is not None:
                target_idx = i + l_val
                assert p.skip.target_index == target_idx
                assert p.skip.target_doc_num == plist[target_idx].doc_num

    # 5. 記憶體優化 AC：positions 物件未複製（identity check）
    p_orig = [Posting(doc_num=1, tf=2, positions=array("I", [10, 20]))]
    res_orig = build_skip_list(p_orig)
    check("positions 引用原始 array，未產生新物件 (is 運算子)", res_orig[0].positions is p_orig[0].positions)


def test_unit_intersection():
    print("\n=== Part 1.2: intersect_basic vs intersect_with_skips 交集驗證 ===")

    # 測試多種情境：
    # a. 完全相同串列
    list_a = [Posting(doc_num=i * 2, tf=1, positions=array("I")) for i in range(50)]
    skips_a = build_skip_list(list_a)
    docs_basic, comp_basic = intersect_basic(skips_a, skips_a)
    docs_skip, comp_skip = intersect_with_skips(skips_a, skips_a)
    check("完全相同串列：交集結果一致", docs_basic == docs_skip == [p.doc_num for p in list_a])
    check("完全相同串列：skip 比較次數 <= basic", comp_skip <= comp_basic, f"skip={comp_skip}, basic={comp_basic}")

    # b. 完全無交集串列
    list_b1 = [Posting(doc_num=i * 4, tf=1, positions=array("I")) for i in range(50)]
    list_b2 = [Posting(doc_num=i * 4 + 1, tf=1, positions=array("I")) for i in range(50)]
    skips_b1 = build_skip_list(list_b1)
    skips_b2 = build_skip_list(list_b2)
    docs_basic, comp_basic = intersect_basic(skips_b1, skips_b2)
    docs_skip, comp_skip = intersect_with_skips(skips_b1, skips_b2)
    check("無交集串列：交集結果均為空", docs_basic == docs_skip == [])
    check("無交集串列：skip 比較次數 <= basic", comp_skip <= comp_basic, f"skip={comp_skip}, basic={comp_basic}")

    # c. 長串列 + 短串列（差距懸殊，Skip 發揮顯著優勢）
    list_long = [Posting(doc_num=i * 2, tf=1, positions=array("I")) for i in range(1000)]
    list_short = [Posting(doc_num=500, tf=1, positions=array("I")), Posting(doc_num=1500, tf=1, positions=array("I"))]
    skips_long = build_skip_list(list_long)
    skips_short = build_skip_list(list_short)
    docs_basic, comp_basic = intersect_basic(skips_long, skips_short)
    docs_skip, comp_skip = intersect_with_skips(skips_long, skips_short)
    check("長短串列：交集結果一致", docs_basic == docs_skip == [500, 1500])
    check("長短串列：skip 比較次數大幅低於 basic", comp_skip < comp_basic * 0.2, f"skip={comp_skip}, basic={comp_basic} (省去 {(1 - comp_skip/comp_basic)*100:.1f}%)")

    # d. 隨機隨機取樣 20 組驗證正確性與比較次數保證
    for seed in range(20):
        rng = random.Random(seed)
        set1 = sorted(rng.sample(range(1000), rng.randint(10, 200)))
        set2 = sorted(rng.sample(range(1000), rng.randint(10, 200)))
        p1 = build_skip_list([Posting(d, 1, array("I")) for d in set1])
        p2 = build_skip_list([Posting(d, 1, array("I")) for d in set2])

        expected = sorted(set(set1) & set(set2))
        res_basic, c_basic = intersect_basic(p1, p2)
        res_skip, c_skip = intersect_with_skips(p1, p2)

        assert res_basic == expected, f"Basic failed on seed {seed}"
        assert res_skip == expected, f"Skip failed on seed {seed}"
        assert c_skip <= c_basic, f"Skip comparisons ({c_skip}) > Basic ({c_basic}) on seed {seed}"
    check("隨機 20 組不同分佈串列：交集結果皆 100% 正確且 skip 比對次數 <= basic", True)


def test_unit_and_query_and_preprocessor():
    print("\n=== Part 1.3: and_query 與 Preprocessor 整合驗證 ===")
    prep = Preprocessor(casefold=True, stopword=True, stem=True)

    # 模擬 skips 倒排字典
    skips = {
        "game": build_skip_list([Posting(1, 1, array("I")), Posting(3, 1, array("I")), Posting(5, 1, array("I"))]),
        "play": build_skip_list([Posting(2, 1, array("I")), Posting(3, 1, array("I")), Posting(5, 1, array("I"))]),
    }

    # 大小寫 + 字幹還原: "Games" -> "game", "Playing" -> "play"
    docs, comp = and_query(skips, prep, "Games", "Playing")
    check("casefold + stem: 'Games' AND 'Playing' 成功對齊 'game' AND 'play'", docs == [3, 5])

    # 停用詞處理: "the" -> []
    docs_stop, comp_stop = and_query(skips, prep, "the", "Games")
    check("停用詞自動回傳空交集", docs_stop == [] and comp_stop == 0)

    # 未登錄詞彙
    docs_missing, comp_missing = and_query(skips, prep, "nonexistent", "Games")
    check("未登錄詞彙自動回傳空交集", docs_missing == [] and comp_missing == 0)


# ---------------------------------------------------------------------------
# Part 2: 整合測試（WARC 語料）
# ---------------------------------------------------------------------------

def test_integration(warc_path: str, limit: int = 500):
    print(f"\n=== Part 2: 整合測試 (WARC: {warc_path}, limit: {limit or 'ALL'}) ===")
    if not os.path.exists(warc_path):
        print(f"找不到語料檔案 {warc_path}，略過整合測試。")
        return

    prep = Preprocessor(casefold=True, stopword=True, stem=True)
    print("1. 建置全記憶體 Indexer...")
    t0 = time.time()
    indexer = Indexer().build(warc_path, prep, limit=limit or None)
    t_idx = time.time() - t0
    print(f"   Indexer 建置完成：{indexer.stats['N']:,} 篇文件，{indexer.stats['vocab_size']:,} 個詞彙，耗時 {t_idx:.2f} s")

    print("\n2. 建置 SkipBuilder...")
    builder = SkipBuilder()
    t1 = time.time()
    skips = builder.build(indexer)
    t_skip = time.time() - t1

    # AC 驗證：有 skip 的 term 數 == df >= 9 的 term 數
    expected_skip_terms = sum(1 for term in indexer.index if indexer.df(term) >= MIN_SKIP_LEN)
    actual_skip_terms = sum(1 for term, plist in skips.items() if any(p.skip is not None for p in plist))
    check(
        f"有 skip 的 term 數 ({actual_skip_terms:,}) == df >= {MIN_SKIP_LEN} 的 term 數 ({expected_skip_terms:,})",
        actual_skip_terms == expected_skip_terms,
    )
    check("SkipBuilder 建置耗時 < 30 s", t_skip < 30.0, f"{t_skip:.2f} s")

    # 挑選 5 組具代表性的 query pair 進行評測：
    # 涵蓋：高頻+高頻、長串列+短串列、無交集、df < 9、典型詞組 ("game" AND "play")
    terms_by_df = sorted(indexer.index.keys(), key=lambda t: indexer.df(t), reverse=True)

    high_terms = [t for t in terms_by_df if indexer.df(t) >= 50]
    low_terms = [t for t in terms_by_df if 1 <= indexer.df(t) < MIN_SKIP_LEN]

    # 1. 高頻 + 高頻（挑選兩個高頻詞）
    q_pair1 = (high_terms[0], high_terms[1]) if len(high_terms) >= 2 else ("inform", "servic")
    # 2. 長串列 + 短串列（高頻 + 低頻，Skip 發揮顯著優勢）
    q_pair2 = (high_terms[0], low_terms[0]) if high_terms and low_terms else ("inform", "rare")
    # 3. 無交集詞組（尋找無共同文件的詞組）
    disjoint_pair = None
    for t_a in high_terms[:20]:
        for t_b in low_terms[:50]:
            docs_a = set(p.doc_num for p in indexer.get_postings(t_a))
            docs_b = set(p.doc_num for p in indexer.get_postings(t_b))
            if not (docs_a & docs_b):
                disjoint_pair = (t_a, t_b)
                break
        if disjoint_pair:
            break
    q_pair3 = disjoint_pair if disjoint_pair else ("game", "zzzznonexistent")
    # 4. df < 9 邊界詞組（無 skip pointer，正確退化為一般比較）
    q_pair4 = (low_terms[0], low_terms[1]) if len(low_terms) >= 2 else ("rare1", "rare2")
    # 5. 典型作業範例詞組 ("game" AND "play"，若無則 fallback)
    w_game = "game" if "game" in indexer.index else high_terms[2]
    w_play = "play" if "play" in indexer.index else high_terms[3]
    q_pair5 = (w_game, w_play)

    test_pairs = [
        ("高頻 + 高頻", q_pair1[0], q_pair1[1]),
        ("長串列 + 短串列", q_pair2[0], q_pair2[1]),
        ("無交集 (Disjoint)", q_pair3[0], q_pair3[1]),
        ("低頻邊界 (df < 9)", q_pair4[0], q_pair4[1]),
        ("典型詞組 (game & play)", q_pair5[0], q_pair5[1]),
    ]

    print("\n3. 執行 5 組查詢比對評測...")
    results_table = []
    max_reduction = 0.0

    for cat, w1, w2 in test_pairs:
        p1 = skips.get(w1, [])
        p2 = skips.get(w2, [])
        df1 = len(p1)
        df2 = len(p2)

        res_basic, comp_basic = intersect_basic(p1, p2)
        res_skip, comp_skip = intersect_with_skips(p1, p2)

        # 驗證結果集完全一致
        assert res_basic == res_skip, f"Mismatch in {w1} AND {w2}: basic={res_basic}, skip={res_skip}"
        # 驗證比較次數
        assert comp_skip <= comp_basic, f"Skip ({comp_skip}) > Basic ({comp_basic}) in {w1} AND {w2}"

        reduction = ((comp_basic - comp_skip) / comp_basic * 100.0) if comp_basic > 0 else 0.0
        speedup = (comp_basic / comp_skip) if comp_skip > 0 else 1.0

        if reduction > max_reduction:
            max_reduction = reduction

        results_table.append({
            "category": cat,
            "q1": w1,
            "df1": df1,
            "q2": w2,
            "df2": df2,
            "inter_len": len(res_basic),
            "basic_comp": comp_basic,
            "skip_comp": comp_skip,
            "reduction": reduction,
            "speedup": speedup,
        })

    # AC 驗證：
    # 1. 所有測試組 skip 比較次數均 <= basic
    check("所有測試案例 Skip 比較次數均 <= Basic 次數", all(r["skip_comp"] <= r["basic_comp"] for r in results_table))
    # 2. Skip 顯著發揮效果 (至少一組典型或長短差距詞組比較次數減少 > 20%)
    check("Skip 指標顯著減少比對次數（最大減少率 > 20%）", max_reduction > 20.0, f"最大減少：{max_reduction:.1f}%")

    # 輸出 Markdown 報告表格
    print("\n" + "=" * 95)
    print("### M5 Skip Pointer 效能評測報告")
    print(f"> **Preprocessor 設定**：`casefold=True, stopword=True, stem=True` | **文件數**：{indexer.stats['N']:,}\n")
    print("| 類別 | Query Pair | df(q1) | df(q2) | 交集文件數 | Basic 比較次數 | Skip 比較次數 | 比較減少率 (%) | 加速比 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in results_table:
        print(
            f"| {r['category']} | `{r['q1']}` AND `{r['q2']}` | {r['df1']:,} | {r['df2']:,} | "
            f"{r['inter_len']:,} | {r['basic_comp']:,} | {r['skip_comp']:,} | "
            f"{r['reduction']:.1f}% | {r['speedup']:.2f}x |"
        )
    print("=" * 95)


def main():
    test_unit_build_skip_list()
    test_unit_intersection()
    test_unit_and_query_and_preprocessor()
    print("\n\033[32m✔ Part 1 單元測試全部通過！\033[0m")

    warc = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent.parent / "dataset" / "04.warc")
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 500
    test_integration(warc, limit=limit)


if __name__ == "__main__":
    main()
