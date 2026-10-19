import re
import spacy
import nltk
from nltk.stem import PorterStemmer

nlp = spacy.blank("en")
nlp.max_length = 5_000_000

CLITICS = {"'s", "'re", "'ll", "'ve", "'m", "'d", "’s", "’re", "’ll", "’ve", "’m", "’d"}
NT = {"n't", "n’t"}
ACRONYM = re.compile(r"(?:[^\W\d_]\.){2,}|(?:[^\W\d_]\.)+[^\W\d_]")
SEP = re.compile(r'[-\u2010-\u2014"=<>|\[\]{}()\\]+')
MAX_LEN = 64
INVIS = {0x200b: " ", 0x2060: " ", 0xfeff: " ", 0xfffd: " ", 0xad: None, 0x200c: None, 0x200d: None}
for c in list(range(0x00, 0x09)) + list(range(0x0e, 0x20)) + list(range(0x7f, 0xa0)):
    INVIS[c] = " "
INVIS[0x19] = "'"
INVIS[0x91] = "'"
INVIS[0x92] = "'"


def clean(s):
    s = s.replace("’", "'")
    i, j = 0, len(s)
    while i < j and not s[i].isalnum():
        i += 1
    while j > i and not s[j - 1].isalnum():
        j -= 1
    return s[i:j]


def has_alnum(s):
    return any(c.isalnum() for c in s)


def tokenize(text):
    doc = nlp.make_doc(text.translate(INVIS))
    out = []
    last = -2
    for t in doc:
        low = t.lower_
        if low in NT:
            if out and last == t.i - 1 and not doc[t.i - 1].whitespace_:
                out[-1] += "n't"
                last = t.i
            continue
        if low in CLITICS or not has_alnum(t.text):
            continue
        if t.like_url or t.like_email:
            out.append(t.text)
        elif ACRONYM.fullmatch(t.text):
            out.append(t.text.replace(".", ""))
        else:
            for p in SEP.split(t.text):
                ps = p.split("/") if any(c.isalpha() for c in p) else [p]
                out.extend(clean(x) for x in ps if has_alnum(x))
        last = t.i
    return [t for t in out if len(t) <= MAX_LEN]


def load_stopwords():
    try:
        from nltk.corpus import stopwords
        return set(stopwords.words("english"))
    except LookupError:
        nltk.download("stopwords", quiet=True)
        from nltk.corpus import stopwords
        return set(stopwords.words("english"))


def load_lemmatizer():
    try:
        from nltk.stem import WordNetLemmatizer
        lemmatizer = WordNetLemmatizer()
        lemmatizer.lemmatize("test")
        return lemmatizer
    except LookupError:
        nltk.download("wordnet", quiet=True)
        nltk.download("omw-1.4", quiet=True)
        from nltk.stem import WordNetLemmatizer
        return WordNetLemmatizer()


class Preprocessor:
    def __init__(self, casefold: bool = True, stopword: bool = False, stem: bool = False, lemma: bool = False):
        self.casefold = casefold
        self.stopword = stopword
        self.stem = stem
        self.lemma = lemma
        self.stops = load_stopwords() if stopword else set()
        self.stemmer = PorterStemmer() if stem else None
        self.lemmatizer = load_lemmatizer() if lemma else None

    def process(self, text: str):
        res = []
        for pos, tok in enumerate(tokenize(text), start=1):
            if self.casefold:
                tok = tok.casefold()
            if self.stopword and tok.casefold() in self.stops:
                continue
            if self.lemma and tok.isalpha():
                tok = self.lemmatizer.lemmatize(tok)
            elif self.stem and tok.isalpha():
                tok = self.stemmer.stem(tok, to_lowercase=self.casefold)
            res.append((pos, tok))
        return res