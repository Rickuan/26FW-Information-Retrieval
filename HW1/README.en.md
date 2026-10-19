# Inverted Index & Boolean Retrieval System (HW1)

> **Corpus**: ClueWeb09 English Dataset (`HW1/dataset/04.warc`, approx. 1.05 GB, 34,786 Web documents in total)  
> **Environment**: Python 3.12+ / `uv` package manager

## 0. Team Member Responsibilities & Contributions

> **Division of Work**:
> 1. **115598022 Yen, Rui-Kuan (顏睿寬)**: Index Writer, Skip Builder, Query Engine, Main (CLI)
> 2. **115598067 Shih, You-Cheng (施宥丞)**: Loader & HTML Cleaner, Tokenizer & Preprocessor, Inverted Indexer (SPIMI)
> 3. **Joint Responsibilities**: Experiment design and analysis, report writing, system integration
> 4. **GitHub repo**: https://github.com/Rickuan/26FW-Information-Retrieval

---

## 1. System Overview

Designed specifically for large-scale web corpora (ClueWeb09), this system provides high-performance inverted indexing and Boolean retrieval capabilities. The processing pipeline consists of:
1. **Loader & Cleaner**: Streams and parses the WARC 0.18 format, repairs character encodings, and strips HTML tags.
2. **Tokenizer & Preprocessor**: Performs character cleaning, acronym/negation preservation, position-preserving stopword filtering, case folding, and stemming.
3. **Inverted Indexer**: Utilizes a custom columnar integer array (`array('I')`), supporting both in-memory indexing and SPIMI (Single-Pass In-Memory Indexing) block-based external merge sort.
4. **Index Writer**: Simultaneously exports assignment-compliant text files (`dictionary.txt`, `postings.txt`) and binary index files (`lexicon.tsv`, `postings.bin`).
5. **Skip Builder & Query Engine**: Dynamically constructs skip pointers ($L = \lfloor\sqrt{P}\rfloor$) to provide skip-accelerated Boolean AND retrieval.

---

## 2. Dependencies & Quick Start

Requires Python 3.12+. Install dependencies from the project root using `uv`:
```bash
uv sync
```
Key packages include: `spacy`, `nltk`, `beautifulsoup4`, `lxml`, `ftfy`, `psutil`, and `tqdm`. Please ensure the corpus is located at `HW1/dataset/04.warc`.

---

## 3. Command Line Interface (CLI) & Usage

The unified entry point is `HW1/src/main.py`:

```bash
# 1. Full-scale build with one command (Artifacts output to HW1/output/; optional flags: --mode spimi, --no-casefold, --no-stopword, --no-stem, --lemma, --limit N)
uv run python HW1/src/main.py build

# 2. Boolean AND retrieval (Skip pointer acceleration enabled by default; add --no-skips to switch to linear comparison for validation)
uv run python HW1/src/main.py query "information" "retrieval" --show-docs 5
```

---

## 4. Key System Features

- **Large-Scale Corpus Support & Low-Memory Architecture**:
  - **Columnar Arrays**: Inverted postings are stored using contiguous `array('I')`, reducing peak memory usage from 3.7 GB to 1.1 GB (a 70% memory reduction).
  - **SPIMI External Merge Sort**: Features automatic memory-threshold-based block splitting and multi-way streaming merge, stably completing full builds under a strict 604 MB memory limit.
- **Ultra-Low Storage Overhead & Compression**:
  - **VByte + Delta Gap (d-gap)**: Compresses binary postings from 177+ MB down to 62.97 MB (compression ratio: 35.5%, saving 64.5% storage space).
  - **Random Seek**: Enables rapid retrieval based on byte offsets in `lexicon.tsv`, executing 1,000 random term lookups in just 0.03 seconds.
- **Skip Pointer Query Acceleration**:
  - Dynamically calculates skip intervals $L = \lfloor\sqrt{P}\rfloor$ (for $P \ge 9$), reducing comparison operations by 94.8% for unbalanced postings lists (achieving a 19.14x speedup), while smoothly falling back to linear comparison during dense intersections.
- **Text Preprocessing Pipeline**:
  - **Character Sanitization**: Replaces invisible and control characters with whitespace; normalizes various quote encodings to standard ASCII single quote `'`.
  - **Semantic Preservation & Fine-Grained Tokenization**: Preserves negation suffixes (`n't`); aggregates acronyms by stripping periods (`U.S.A.` $\to$ `USA`); fully retains domain names and email addresses; intelligently splits slash-separated compounds (`client/server`); trims leading/trailing non-alphanumeric noise; strips clitics (`'s`, `'ve`, etc.); enforces `MAX_LEN = 64` to eliminate meaningless excessively long tokens.
  - **Morphology & Position Fidelity**: Tracks absolute token positions; strictly maintains monotonically increasing position indices during stopword removal (e.g., in "lord of the rings", "lord" is pos 1 and "rings" is pos 4) to preserve true word distances for accurate phrase queries; enforces thorough case folding; applies stemming and lemmatization exclusively to purely alphabetic tokens.
- **Auxiliary Prefix Search & Multiple Artifact Formats**:
  - **Radix Trie Prefix Search**: Delivers ultra-fast prefix search across tens of thousands of terms in 0.01 seconds.
  - **Dual Artifact Outputs**: Generates both homework-compliant plain-text files (`dictionary.txt`, `postings.txt`) and optimized binary index files (`lexicon.tsv`, `postings.bin`) in a single pass.

---

## 5. Core Experiments & Ablation Studies

### Experiment 1: Preprocessing Ablation Study (First 5,000 Documents Benchmark)

| Experimental Group | Parameter Settings | Vocab Size ($Vocab$) | Total Tokens | Index Size (`postings.bin`) | Impact & Benefit Analysis |
|---|---|---|---|---|---|
| **Baseline Control** | **Default (All Enabled)** | **94,820** | **2,410,812** | **6.81 MB** | **Optimal configuration (most compact vocabulary and lowest storage overhead)** |
| Disable Case Folding | `--no-casefold` | 124,310 (+31.1%) | 2,410,812 | 7.92 MB (+16.3%) | Case variations unmerged, leading to significant dictionary bloat |
| Disable Stopwords | `--no-stopword` | 94,999 (+0.2%) | 3,921,405 (+62.7%) | 11.95 MB (+75.5%) | High-frequency function words indexed, causing postings size to surge by 75.5% |
| Disable Stemming | `--no-stem` | 124,131 (+30.9%) | 2,410,812 | 7.92 MB (+16.3%) | Inflected forms not conflated (e.g., `retrieval` vs. `retrieving`) |
| Enable Lemmatization | `--lemma` | 108,450 (+14.4%) | 2,410,812 | 7.35 MB (+7.9%) | Preserves semantic word forms without stem distortion; vocabulary size sits between baseline and unstemmed |

### Experiment 2: Skip Pointer Query Acceleration Comparison (Full 34,786 Documents)

| Test Scenario | Query Terms (q1 AND q2) | Basic Comparisons | Skip Comparisons | Comparison Reduction (%) | Speedup Ratio |
|---|---|---|---|---|---|
| **Unbalanced Lists (Vastly Different Lengths)** | `home` AND `hallyday` | 19,145 | **1,000** | **-94.8%** | **19.14x** |
| **Typical Co-occurring Terms** | `game` AND `play` | 9,225 | **8,399** | **-9.0%** | **1.10x** |
| **High-Frequency Dense Intersection** | `home` AND `new` | 27,946 | 27,946 | 0.0% (smooth fallback) | 1.00x |

> **Conclusion**: For lists of vastly differing lengths, the sparsity of the shorter list allows skip pointers to leap ahead continuously, slashing comparisons by 94.8%. In dense intersections, the algorithm gracefully falls back to linear scanning without redundant overhead.

---

## 6. Challenges & Solutions

1. **WARC Header Defects & Deprecating `warcio`**: Inaccurate `Content-Length` values in certain headers caused third-party libraries to desynchronize byte offsets. Replaced with a custom streaming parser that segments records precisely by the boundary marker `b"WARC/0.18"`.
2. **HTML Encoding Conflicts & Silent Truncations**: Mismatches between HTTP header declarations and internal document encodings caused `lxml` to silently truncate documents. Resolved by decoding into Unicode strings via `UnicodeDammit` before parsing, combined with `ftfy` to repair Mojibake, reducing truncations down to just 1 document.
3. **Memory Explosion on Massive Corpus**: Native Python object overhead drove peak RSS up to 3.7 GB. Solved by engineering custom columnar contiguous arrays (`array('I')`), dropping peak memory to 1.1 GB (-70%), and employing SPIMI external merge sort to reliably build the full index within a 604 MB memory budget.
4. **Fairness in Skip Pointer Benchmarking & Boundary Conditions**: Omitting skip condition evaluations would underestimate comparison overhead, and building skips for short postings adds unnecessary cost. Enforced strict counting of skip comparisons and disabled skip pointers for short lists ($P < 9$) to ensure graceful fallback to linear traversal.
5. **Year/Numeric Fidelity & URL Truncation Protection**: Numeric years carry critical temporal semantics; stemming is strictly restricted to purely alphabetic tokens to prevent numeric degradation. URLs carry strong topic relevance; enforced `MAX_LEN = 64` to retain core domain structures while discarding unresolved Base64 noise and overly long parameters.
