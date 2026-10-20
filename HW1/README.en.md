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
  - **SPIMI External Merge Sort**: Flushes a sorted block to disk whenever the buffered position count reaches a threshold (default 3,000,000 positions), then merges all blocks with a streaming multi-way merge. Peak RSS on the full corpus is 604 MB (10 blocks, merge 6 s).
- **Ultra-Low Storage Overhead & Compression**:
  - **VByte + Delta Gap (d-gap)**: Encodes postings with d-gaps and VByte: `postings.txt` 221.3 MB → `postings.bin` 63.0 MB (28.5%) on the full corpus with default settings.
  - **Random Seek**: Enables rapid retrieval based on byte offsets in `lexicon.tsv`, executing 1,000 random term lookups in just 0.03 seconds.
- **Skip Pointer Query Acceleration**:
  - Dynamically calculates skip intervals $L = \lfloor\sqrt{P}\rfloor$ (for $P \ge 9$), reducing comparison operations by 94.8% for unbalanced postings lists (19.1× fewer comparisons), while smoothly falling back to linear comparison during dense intersections.
- **Text Preprocessing Pipeline**:
  - **Character Sanitization**: Replaces invisible and control characters with whitespace; normalizes various quote encodings to standard ASCII single quote `'`.
  - **Semantic Preservation & Fine-Grained Tokenization**: Preserves negation suffixes (`n't`); aggregates acronyms by stripping periods (`U.S.A.` $\to$ `USA`); fully retains domain names and email addresses; intelligently splits slash-separated compounds (`client/server`); trims leading/trailing non-alphanumeric noise; strips clitics (`'s`, `'ve`, etc.); enforces `MAX_LEN = 64` to eliminate meaningless excessively long tokens.
  - **Stopword filtering happens before stemming.** A non-stopword can therefore stem to a stopword, so 105 stopword entries still appear in the stop+stem dictionary, e.g. `thes` → `the` (df 214, vs. 31,836 without stopword removal). The largest cases come from content words such as `other` (df 3,298), `own` (df 1,204) and `will` (df 1,136), so we deliberately do not filter again after stemming.
  - **Morphology & Position Fidelity**: Tracks absolute token positions; strictly maintains monotonically increasing position indices during stopword removal (e.g., in "lord of the rings", "lord" is pos 1 and "rings" is pos 4) to preserve true word distances for accurate phrase queries; enforces thorough case folding; applies stemming and lemmatization exclusively to purely alphabetic tokens.
- **Auxiliary Prefix Search & Multiple Artifact Formats**:
  - **Radix Trie Prefix Search**: Delivers ultra-fast prefix search across tens of thousands of terms in 0.01 seconds.
  - **Dual Artifact Outputs**: Generates both homework-compliant plain-text files (`dictionary.txt`, `postings.txt`) and optimized binary index files (`lexicon.tsv`, `postings.bin`) in a single pass.

---

## 5. Core Experiments & Ablation Studies

### Experiment 1: Preprocessing Ablation (first 5,000 documents)

Baseline is the `main.py build` default (case folding + stopword removal + Porter stemming).
All counts are deterministic for a given code version; percentages are relative to the baseline.

| Setting | Flags | Vocab | Tokens | `postings.bin` |
|---|---|---|---|---|
| **Baseline** | (default) | **160,979** | **2,887,106** | **10.14 MB** |
| No case folding | `--no-casefold` | 186,458 (+15.8%) | 2,887,106 | 10.65 MB (+5.1%) |
| No stopword removal | `--no-stopword` | 161,051 (+0.04%) | 4,382,100 (+51.8%) | 12.70 MB (+25.3%) |
| No stemming | `--no-stem` | 189,123 (+17.5%) | 2,887,106 | 10.75 MB (+6.1%) |
| Lemmatization instead of stemming | `--lemma` | 181,353 (+12.7%) | 2,887,106 | 10.50 MB (+3.6%) |

- Stopwords add only 72 vocabulary entries but account for 34.1% of all tokens, so removing them mainly shrinks the postings, not the dictionary.
- Compared with no word-form normalization (`--no-stem`, 189,123 terms), Porter stemming reduces the vocabulary by 14.9%, while WordNet lemmatization reduces it by only 4.1%, since the lemmatizer without POS tags only normalizes nouns.
- Case folding, stemming and lemmatization only merge word forms and never change the token count.
- These numbers compare index size only. Without queries and relevance judgments, they do not show which setting retrieves better.

### Experiment 2: Skip Pointer Query Acceleration Comparison (Full 34,786 Documents)

| Test Scenario | Query Terms (q1 AND q2) | Basic Comparisons | Skip Comparisons | Comparison Reduction (%) | Comparison ratio |
|---|---|---|---|---|---|
| **Unbalanced Lists (Vastly Different Lengths)** | `home` AND `hallyday` | 19,145 | **1,000** | **-94.8%** | **19.14x** |
| **Typical Co-occurring Terms** | `game` AND `play` | 9,225 | **8,399** | **-9.0%** | **1.10x** |
| **High-Frequency Dense Intersection** | `home` AND `new` | 27,946 | 27,946 | 0.0% (smooth fallback) | 1.00x |

> **Conclusion**: For lists of vastly differing lengths, the sparsity of the shorter list allows skip pointers to leap ahead continuously, slashing comparisons by 94.8%. In dense intersections, the algorithm gracefully falls back to linear scanning without redundant overhead.

---

## 6. Challenges & Solutions

1. **WARC Header Defects & Deprecating `warcio`**: Inaccurate `Content-Length` values in certain headers caused third-party libraries to desynchronize byte offsets. Replaced with a custom streaming parser that segments records precisely by the boundary marker `b"WARC/0.18"`.
2. **HTML Encoding Conflicts & Silent Truncations**: Mismatches between HTTP header declarations and the actual document encoding caused `lxml` to silently truncate documents. Resolved by decoding into Unicode strings with `UnicodeDammit` before parsing, which reduced empty documents from 163 to 1 (a JavaScript redirect page). `ftfy.fix_encoding` is applied only when mojibake patterns are detected; 2 documents still contain residual mojibake.
3. **Memory Explosion on Massive Corpus**: Native Python object overhead drove peak RSS up to 3.7 GB. Solved by engineering custom columnar contiguous arrays (`array('I')`), dropping peak memory to 1.1 GB (-70%), and employing SPIMI to build the full index with a peak RSS of 604 MB.
4. **Fairness in Skip Pointer Benchmarking & Boundary Conditions**: Omitting skip condition evaluations would underestimate comparison overhead, and building skips for short postings adds unnecessary cost. Enforced strict counting of skip comparisons and disabled skip pointers for short lists ($P < 9$) to ensure graceful fallback to linear traversal.
5. **Year/Numeric Fidelity & Long-Token Filtering**: Numeric years carry critical temporal semantics; stemming is strictly restricted to purely alphabetic tokens to prevent numeric degradation. URLs carry strong topic relevance, so URLs and e-mail addresses up to 64 characters are kept whole; tokens longer than 64 characters (mostly Base64 strings and concatenated URLs) are dropped entirely rather than truncated.
