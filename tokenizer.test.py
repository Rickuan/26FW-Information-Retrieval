import sys
import time
from collections import Counter
from itertools import islice

from documents import iter_documents
from tokenizer import Preprocessor, tokenize

SAMPLE = ("0 Men's Lyrics: (Waiting For) Ain't It Strange? LyricsFans.com "
          "state-of-the-art U.S.A. 3.14 RMB500yuan 025-84791919 "
          "16099kefu@163.com www.16099.com set-up não")
EXPECTED = ["0", "Men", "Lyrics", "Waiting", "For", "Ain't", "It", "Strange",
            "LyricsFans.com", "state", "of", "the", "art", "USA", "3.14",
            "RMB500yuan", "025", "84791919", "16099kefu@163.com",
            "www.16099.com", "set", "up", "não"]

got = tokenize(SAMPLE)
print("got     :", got)
print("expected:", EXPECTED)
if got == EXPECTED:
    print("SAMPLE OK")
else:
    for i, (a, b) in enumerate(zip(got, EXPECTED)):
        if a != b:
            print(f"first diff at {i}: got {a!r} expected {b!r}")
            break
    print("len", len(got), "vs", len(EXPECTED))

print()
for kw in [{}, {"casefold": False}, {"stopword": True}, {"stopword": True, "stem": True}]:
    print(kw or "default", Preprocessor(**kw).process(SAMPLE))

EXTRA = ("Inc. Dr. conditions/ /code don’t copyright\u200bbeijing hy\xadphen 18/04/2007 "
         "it\x19s don\x19t support\x1abeijing and/or 1/2 "
         'type="text"')
EXTRA_EXP = ["Inc", "Dr", "conditions", "code", "don't", "copyright", "beijing", "hyphen",
             "18/04/2007", "it", "don't", "support", "beijing", "and", "or", "1/2",
             "type", "text"]
got2 = tokenize(EXTRA)
print("\nextra:", got2, "OK" if got2 == EXTRA_EXP else f"FAIL expected {EXTRA_EXP}")

path = sys.argv[1] if len(sys.argv) > 1 else "04.warc"
n = int(sys.argv[2]) if len(sys.argv) > 2 else 2000

pre = Preprocessor()
vocab = Counter()
weird = Counter()
ntok = 0
ndoc = 0
tok_time = 0.0
t0 = time.time()
for d in islice(iter_documents(path), n):
    s = time.time()
    terms = pre.process(d.text)
    tok_time += time.time() - s
    ndoc += 1
    ntok += len(terms)
    for _, t in terms:
        vocab[t] += 1
        if not t.isalnum():
            weird[t] += 1

total = time.time() - t0
print(f"\n{ndoc} docs, {ntok} tokens, vocab {len(vocab)}")
print(f"total {total:.1f}s (tokenize {tok_time:.1f}s)")
print(f"est. full 34786 docs: tokenize ~{tok_time / ndoc * 34786:.0f}s, all ~{total / ndoc * 34786:.0f}s")
print("tokens with U+FFFD:", sum(1 for t in vocab if "\ufffd" in t))
print("\ntop 30 terms:")
for t, c in vocab.most_common(30):
    print(f"{c:8d}  {t!r}")
print("\ntop 40 non-alnum terms:")
for t, c in weird.most_common(40):
    print(f"{c:8d}  {t!r}")


print("\nlongest 20 terms:")
for t in sorted(vocab, key=len, reverse=True)[:20]:
    print(f"{len(t):6d}  {vocab[t]:6d}  {t[:80]!r}")
print("terms len > 40:", sum(1 for t in vocab if len(t) > 40))
print("hapax (freq 1):", sum(1 for c in vocab.values() if c == 1))