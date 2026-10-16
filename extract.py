"""原始 body（bytes）→ 正規化純文字。

設計決策（皆經 04.warc 驗證）：
- 先用 UnicodeDammit 解碼成 str 再交給 lxml；直接給 bytes 時，宣告編碼與內容
  不符會讓 lxml 默默截斷文件（空文件 163 → 1）。
- 只在偵測到典型 mojibake 時呼叫 ftfy.fix_encoding（不用 fix_text）。
- 不索引 script / style / noscript。
- XHTML 也用 HTML parser（XML parser 遇到壞 HTML 會失敗）。
"""
from __future__ import annotations

import logging
import re
import warnings

import ftfy
from bs4 import BeautifulSoup, UnicodeDammit, XMLParsedAsHTMLWarning

from warc import NO_CONTENT_TYPE

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
logging.getLogger("bs4.dammit").setLevel(logging.ERROR)

HTML_TYPES = frozenset({"text/html", "application/xhtml+xml", "application/xml"})
PLAIN_TYPES = frozenset({"text/plain"})
DROP_TAGS = ("script", "style", "noscript")
MOJIBAKE = re.compile(r"Ã[\u0080-\u00bf]|Â[\u00a0-\u00bf]|â€.")

BINARY_SNIFF_BYTES = 1024
BINARY_CTRL_RATIO = 0.10


def looks_binary(body: bytes) -> bool:
    """前 1KB 中控制字元比例過高即視為二進位（防止標頭標錯）。"""
    sample = body[:BINARY_SNIFF_BYTES]
    if not sample:
        return False
    ctrl = sum(1 for b in sample if b < 9 or 13 < b < 32)
    return ctrl / len(sample) > BINARY_CTRL_RATIO


def classify(content_type: str, body: bytes) -> tuple[str, str | None]:
    """回傳 (kind, 排除原因)。kind 為 'html' / 'plain' / 'exclude'。"""
    if looks_binary(body):
        return "exclude", "binary content (sniffed)"
    if content_type in HTML_TYPES or content_type == NO_CONTENT_TYPE:
        return "html", None
    if content_type in PLAIN_TYPES:
        return "plain", None
    return "exclude", f"type: {content_type}"


def decode_body(body: bytes) -> str:
    """先自己解碼成 str，避免 lxml 遇到壞位元組時默默截斷。"""
    dammit = UnicodeDammit(body, is_html=True)
    if dammit.unicode_markup is not None:
        return dammit.unicode_markup
    enc = dammit.declared_html_encoding or "utf-8"
    try:
        return body.decode(enc, errors="replace")
    except LookupError:                       # 宣告了不存在的編碼名稱
        return body.decode("utf-8", errors="replace")


def fix_mojibake(text: str) -> str:
    """只在偵測到典型亂碼模式時才修復，避免誤改正常文字。"""
    if MOJIBAKE.search(text):
        return ftfy.fix_encoding(text)
    return text


def normalize_ws(text: str) -> str:
    """合併所有連續空白（含 \\xa0 等 Unicode 空白）為單一空格。"""
    return " ".join(text.split())


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(DROP_TAGS):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def extract_text(body: bytes, kind: str) -> str:
    decoded = decode_body(body)
    if kind == "html":
        text = html_to_text(decoded)
    elif kind == "plain":
        text = decoded
    else:
        raise ValueError(f"unsupported kind: {kind!r}")
    # 先修亂碼再合併空白：ftfy 可能把 'Â\xa0' 修成 '\xa0'
    return normalize_ws(fix_mojibake(text))