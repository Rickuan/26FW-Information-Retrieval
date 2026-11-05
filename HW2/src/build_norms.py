"""T2：預算文件 norm |d|，寫出 norm 檔與 meta。

執行：uv run python HW2/src/build_norms.py --index-dir HW2/index [--scheme ltc]
  預設 ltc → doc_norms.bin + doc_norms.meta.json；
  其他 scheme（加分）→ doc_norms.<scheme>.bin + doc_norms.<scheme>.meta.json（檔名見 weighting.norm_filenames）。
"""
from __future__ import annotations

import argparse
import json
import math
import resource
import time
from array import array
from pathlib import Path

from weighting import DEFAULT_SCHEME, LOG_BASE, formula, norm_filenames, weight
from writer import _NORM_SOURCES, IndexReader, _fingerprint, decode_postings_block


def build_norms(index_dir: str | Path, scheme: str = "ltc") -> None:
    """一次掃過整個 index，計算每篇文件的 |d|（array('d')，下標 = doc_num）並寫出 meta。

    meta 記錄 log_base、formula、scheme、N、count，以及 lexicon.tsv、postings.bin、
    metadata.json 的 size 與 sha256。結束時印出建置時間與峰值記憶體。
    """
    index_dir = Path(index_dir)
    bin_name, meta_name = norm_filenames(scheme)
    t0 = time.perf_counter()

    reader = IndexReader(index_dir)
    N = reader.N
    norm2 = array("d", bytes(8 * N))
    with (index_dir / "postings.bin").open("rb") as f:
        for term, (df, offset, length) in reader._load_lexicon().items():
            f.seek(offset)
            for p in decode_postings_block(f.read(length)):
                norm2[p.doc_num] += weight(p.tf, df, N, scheme) ** 2
    norms = array("d", (math.sqrt(v) for v in norm2))

    with (index_dir / bin_name).open("wb") as f:
        norms.tofile(f)
    meta = {
        "log_base": LOG_BASE,
        "formula": formula(scheme),
        "scheme": scheme,
        "N": N,
        "count": N,
        "sources": {name: _fingerprint(index_dir / name) for name in _NORM_SOURCES},
    }
    with (index_dir / meta_name).open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")

    elapsed = time.perf_counter() - t0
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Linux: KB
    print(f"build_norms({scheme}): {elapsed:.2f} s, peak RSS {peak_mb:.1f} MB, "
          f"{bin_name} {8 * N} bytes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Precompute document norms |d|.")
    parser.add_argument("--index-dir", required=True)
    parser.add_argument("--scheme", default=DEFAULT_SCHEME)
    args = parser.parse_args()
    build_norms(args.index_dir, args.scheme)
