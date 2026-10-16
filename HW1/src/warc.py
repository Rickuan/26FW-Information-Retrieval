"""WARC 0.18（ClueWeb09）解析。

不使用 warcio：ClueWeb09 有大量錯誤的 Content-Length，warcio 會在第一筆之後
讀錯位置。改為逐行讀取，以 b"WARC/0.18" 開頭的行作為紀錄邊界。
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass

RECORD_START = b"WARC/0.18"
HEADER_END = re.compile(rb"\r?\n\r?\n")
TREC_ID_RE = re.compile(r"^(?P<prefix>.+)-(?P<num>\d+)$")

NO_CONTENT_TYPE = "(none)"
NO_STATUS = "(no status)"


@dataclass(frozen=True, slots=True)
class WarcResponse:
    trec_id: str        # e.g. clueweb09-en0000-04-00000
    doc_num: int        # TREC-ID 尾碼整數，作為 postings 的 docID
    url: str
    content_type: str   # 小寫、去掉參數；缺少時為 NO_CONTENT_TYPE
    http_status: str    # HTTP 狀態行；缺少時為 NO_STATUS
    body: bytes


def iter_records(path) -> Iterator[bytes]:
    """逐行讀取，以 WARC/0.18 開頭的行切分紀錄，不信任 Content-Length。"""
    with open(path, "rb") as f:
        buf: list[bytes] = []
        for line in f:
            if line.startswith(RECORD_START) and buf:
                yield b"".join(buf)
                buf = []
            buf.append(line)
        if buf:
            yield b"".join(buf)


def split_headers(block: bytes) -> tuple[bytes, bytes]:
    """以第一個空行切成 (標頭, 其餘)。"""
    parts = HEADER_END.split(block, maxsplit=1)
    return (parts[0], parts[1]) if len(parts) == 2 else (parts[0], b"")


def parse_header_lines(head: bytes) -> tuple[str, dict[str, str]]:
    """回傳 (第一行, {小寫欄位名: 值})。latin-1 解碼不會失敗。"""
    lines = head.decode("latin-1").splitlines()
    first = lines[0].strip() if lines else ""
    headers: dict[str, str] = {}
    for line in lines[1:]:
        k, sep, v = line.partition(":")
        if sep:
            headers[k.strip().lower()] = v.strip()
    return first, headers


def parse_content_type(http_headers: dict[str, str]) -> str:
    value = http_headers.get("content-type", "")
    return value.split(";", 1)[0].strip().lower() or NO_CONTENT_TYPE


def parse_trec_id(trec_id: str) -> tuple[str, int]:
    """'clueweb09-en0000-04-00123' -> ('clueweb09-en0000-04', 123)"""
    m = TREC_ID_RE.match(trec_id)
    if not m:
        raise ValueError(f"無法解析的 TREC-ID: {trec_id!r}")
    return m["prefix"], int(m["num"])


def split_http(rest: bytes) -> tuple[str, dict[str, str], bytes]:
    """切出 HTTP 狀態行、標頭與內文；缺少 HTTP 狀態行時整段視為內文。"""
    rest = rest.lstrip(b"\r\n")
    if rest.startswith(b"HTTP/"):
        http_head, body = split_headers(rest)
        status, headers = parse_header_lines(http_head)
        return status, headers, body
    return NO_STATUS, {}, rest


def read_warcinfo(path) -> tuple[dict[str, str], str]:
    """讀第一筆紀錄；若為 warcinfo 回傳 (標頭, 內容)，否則回傳空值。"""
    for raw in iter_records(path):
        head, rest = split_headers(raw)
        _, wh = parse_header_lines(head)
        if wh.get("warc-type") == "warcinfo":
            return wh, rest.decode("latin-1").strip()
        break
    return {}, ""


def iter_responses(path, record_types: Counter | None = None) -> Iterator[WarcResponse]:
    """產出所有 response 紀錄。record_types 若有給，會統計每種 WARC-Type 的筆數
    （出現 '(none)' 代表紀錄邊界切錯，例如內文中有一行剛好以 WARC/0.18 開頭）。"""
    for raw in iter_records(path):
        head, rest = split_headers(raw)
        _, wh = parse_header_lines(head)
        wtype = wh.get("warc-type", "(none)")
        if record_types is not None:
            record_types[wtype] += 1
        if wtype != "response":
            continue
        trec_id = wh.get("warc-trec-id", "")
        _, doc_num = parse_trec_id(trec_id)          # 缺 ID 直接報錯，不默默跳過
        status, http_headers, body = split_http(rest)
        yield WarcResponse(
            trec_id=trec_id,
            doc_num=doc_num,
            url=wh.get("warc-target-uri", ""),
            content_type=parse_content_type(http_headers),
            http_status=status,
            body=body,
        )