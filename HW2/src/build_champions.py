"""T2 加分：建立 champion list（每個 term 的 tf 前 r 名文件）。

執行：uv run python HW2/src/build_champions.py --index-dir HW2/index [--r 50]
輸出（只收 df > r 的 term；df ≤ r 的 term 由 get_champions 直接回傳完整 postings）：
  champions.r<r>.bin       每個 term 一個 block：[n: uint32 BE] + n × [Δdoc: VByte][tf: VByte]，doc 遞增
  champions.r<r>.tsv       term TAB n TAB byte_offset TAB byte_length（字典序）
  champions.r<r>.meta.json r、選取規則、來源 lexicon.tsv／postings.bin 的 size 與 sha256
"""
from __future__ import annotations

import argparse
import csv
import json
import resource
import struct
import time
from pathlib import Path

from writer import IndexReader, _fingerprint, decode_postings_block, encode_vbyte


def build_champions(index_dir: str | Path, r: int = 50) -> None:
    """對每個 df > r 的 term，依 (-tf, doc_num) 取前 r 篇，再依 doc_num 遞增寫出。"""
    if r < 1:
        raise ValueError(f"r must be >= 1, got {r}")
    index_dir = Path(index_dir)
    bin_name, tsv_name, meta_name = (f"champions.r{r}.bin", f"champions.r{r}.tsv",
                                     f"champions.r{r}.meta.json")
    t0 = time.perf_counter()

    reader = IndexReader(index_dir)
    count = 0
    offset = 0
    with (index_dir / "postings.bin").open("rb") as src, \
            (index_dir / bin_name).open("wb") as out_bin, \
            (index_dir / tsv_name).open("w", encoding="utf-8", newline="") as out_tsv:
        writer = csv.writer(out_tsv, delimiter="\t", lineterminator="\n")
        for term, (df, term_offset, length) in reader._load_lexicon().items():
            if df <= r:
                continue
            src.seek(term_offset)
            pairs = [(p.doc_num, p.tf) for p in decode_postings_block(src.read(length))]
            top = sorted(sorted(pairs, key=lambda x: (-x[1], x[0]))[:r])
            block = bytearray(struct.pack(">I", r))
            prev_doc = 0
            for doc, tf in top:
                block += encode_vbyte(doc - prev_doc)
                block += encode_vbyte(tf)
                prev_doc = doc
            out_bin.write(block)
            writer.writerow([term, r, offset, len(block)])
            offset += len(block)
            count += 1

    meta = {
        "r": r,
        "rule": "(-tf, doc)",
        "format": "u32be n + n*(vbyte dgap, vbyte tf)",
        "count": count,
        "N": reader.N,
        "sources": {name: _fingerprint(index_dir / name) for name in ("lexicon.tsv", "postings.bin")},
    }
    with (index_dir / meta_name).open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")

    elapsed = time.perf_counter() - t0
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Linux: KB
    sizes = ", ".join(f"{n} {(index_dir / n).stat().st_size} bytes" for n in (bin_name, tsv_name))
    print(f"build_champions(r={r}): {elapsed:.2f} s, peak RSS {peak_mb:.1f} MB, "
          f"{count} terms, {sizes}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build champion lists.")
    parser.add_argument("--index-dir", required=True)
    parser.add_argument("--r", type=int, default=50)
    args = parser.parse_args()
    build_champions(args.index_dir, args.r)
