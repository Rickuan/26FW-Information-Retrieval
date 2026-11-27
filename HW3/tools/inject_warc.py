"""埋入特殊 token：依 config.toml 的 [[inject.tokens]]，由 [corpus].source_warc（dataset/04.warc）
產生 [corpus].injected_warc（dataset/04_injected.warc）（規格 1.5、2.2）。

執行方式（在 HW3/ 下）：
    uv run python tools/inject_warc.py

- 唯一的設定來源是 config.toml 的 [[inject.tokens]]（student_id、sentence、target_trec_ids，
  每組恰好 3 篇）；設定不完整時不寫任何檔案，exit 2。
- 路徑一律以 HW3/ 為基準（由 rag.config 解析），與當下的工作目錄無關。
- 輸出是確定性的：同一份 04.warc 與 config 重跑會得到逐位元組相同的檔案。

做法：
- 以 hw_bridge.iter_raw_records() 逐筆讀取；非目標 record 原樣寫出。
- 目標 record：在 HTTP 內文中最後一個 </body>（不分大小寫）前插入 <p>{sentence}</p>（ASCII）；
  找不到 </body> 就停止，不自行改插入位置。
- WARC 標頭的 Content-Length 加上插入位元組數；HTTP 標頭若有 Content-Length 也一併加上。
  只替換數字本身，其餘位元組（含換行符號）不動。
- 寫到 <injected>.tmp，全部成功後 os.replace；失敗時刪除暫存檔。
- 寫完後執行 4 項驗收，結果印到 stderr；全部通過才 exit 0（驗收失敗 exit 1）：
  1. iter_documents 讀取新檔：34,786 篇，docid 連續
  2. inspect_targets：每篇目標的 cleaned_text 都包含該組的句子
  3. 非目標 record 新舊逐位元組相同
  4. 每篇目標的大小差 = 插入位元組數 + Content-Length 數字增加的位數
- 最後印出每組目標的 docid（供 eval/testset.jsonl 的 gold_docids）。
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))   # HW3/src，與工作目錄無關

from rag import config as C  # noqa: E402
from rag import hw_bridge  # noqa: E402

EXPECTED_DOCS = 34_786
TARGETS_PER_TOKEN = 3
HEADER_END = re.compile(rb"\r?\n\r?\n")
CONTENT_LENGTH = re.compile(rb"(?im)^(content-length[ \t]*:[ \t]*)(\d+)")
WARC_TYPE = re.compile(rb"(?im)^warc-type[ \t]*:[ \t]*(\S+)")
WARC_TREC_ID = re.compile(rb"(?im)^warc-trec-id[ \t]*:[ \t]*(\S+)")
BODY_CLOSE = b"</body>"


class InjectError(RuntimeError):
    pass


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

def load_targets(cfg: dict) -> dict[str, str]:
    """回傳 {trec_id: sentence}；設定不完整就 raise（不猜）。"""
    tokens = cfg.get("inject", {}).get("tokens", [])
    errors: list[str] = []
    targets: dict[str, str] = {}
    if not tokens:
        errors.append("沒有任何 [[inject.tokens]]")
    for i, tok in enumerate(tokens):
        sid, sentence, ids = tok.get("student_id", ""), tok.get("sentence", ""), tok.get("target_trec_ids", [])
        where = f"[[inject.tokens]] #{i + 1}（student_id={sid!r}）"
        if not re.fullmatch(r"\d+", str(sid)):
            errors.append(f"{where}：student_id 不是純數字（尚未填寫？）")
        if str(sid) not in sentence:
            errors.append(f"{where}：sentence 未包含 student_id")
        try:
            sentence.encode("ascii")
        except UnicodeEncodeError:
            errors.append(f"{where}：sentence 含非 ASCII 字元")
        if any(c in sentence for c in "<>&"):
            errors.append(f"{where}：sentence 含 HTML 特殊字元 < > &")
        if len(ids) != TARGETS_PER_TOKEN or len(set(ids)) != len(ids):
            errors.append(f"{where}：target_trec_ids 必須恰好 {TARGETS_PER_TOKEN} 篇且不重複，實際 {ids!r}")
        for t in ids:
            if t in targets:
                errors.append(f"{where}：{t} 與其他成員重複")
            targets[t] = sentence
    if errors:
        raise InjectError("config.toml 的 [[inject.tokens]] 不完整：\n  - " + "\n  - ".join(errors))
    return targets


# ---------------------------------------------------------------------------
# 單筆 record 的修改
# ---------------------------------------------------------------------------

def record_trec_id(raw: bytes) -> str | None:
    """response record 的 TREC-ID；其他 record 回傳 None。"""
    m = HEADER_END.search(raw)
    head = raw[: m.start()] if m else raw
    wt = WARC_TYPE.search(head)
    if not wt or wt.group(1).lower() != b"response":
        return None
    tid = WARC_TREC_ID.search(head)
    return tid.group(1).decode("latin-1") if tid else None


def _bump(header: bytes, delta: int, required: bool, label: str) -> bytes:
    """只把 Content-Length 的數字加上 delta；其他位元組不動。"""
    matches = list(CONTENT_LENGTH.finditer(header))
    if len(matches) > 1:
        raise InjectError(f"{label} 有 {len(matches)} 個 Content-Length")
    if not matches:
        if required:
            raise InjectError(f"{label} 缺少 Content-Length")
        return header
    m = matches[0]
    new_value = str(int(m.group(2)) + delta).encode("ascii")
    return header[: m.start(2)] + new_value + header[m.end(2):]


@dataclass(frozen=True)
class Injection:
    raw: bytes
    inserted: int
    warc_cl_digits_delta: int   # Content-Length 數字變長（例如 999 → 1070）造成的額外位元組
    http_cl_digits_delta: int
    has_http_cl: bool


def inject(raw: bytes, sentence: str, trec_id: str) -> Injection:
    snippet = f"<p>{sentence}</p>".encode("ascii")
    delta = len(snippet)

    m = HEADER_END.search(raw)
    if not m:
        raise InjectError(f"{trec_id}：找不到 WARC 標頭結尾")
    warc_head, sep1, rest = raw[: m.start()], raw[m.start(): m.end()], raw[m.end():]

    # 與 warc.split_http 相同：先略過開頭的換行，再判斷 HTTP 標頭
    lead_len = len(rest) - len(rest.lstrip(b"\r\n"))
    lead, payload = rest[:lead_len], rest[lead_len:]
    if payload.startswith(b"HTTP/"):
        m2 = HEADER_END.search(payload)
        if not m2:
            raise InjectError(f"{trec_id}：找不到 HTTP 標頭結尾")
        http_head, sep2, body = payload[: m2.start()], payload[m2.start(): m2.end()], payload[m2.end():]
    else:
        http_head, sep2, body = b"", b"", payload

    pos = body.lower().rfind(BODY_CLOSE)
    if pos < 0:
        raise InjectError(f"{trec_id}：HTTP 內文中找不到 </body>（依指示停止，不改插入位置）")
    new_body = body[:pos] + snippet + body[pos:]

    new_warc_head = _bump(warc_head, delta, True, f"{trec_id} WARC 標頭")
    new_http_head = _bump(http_head, delta, False, f"{trec_id} HTTP 標頭") if http_head else http_head
    new_raw = new_warc_head + sep1 + lead + new_http_head + sep2 + new_body

    # 自我檢查：移除插入片段並還原標頭後，必須與原 record 逐位元組相同
    restored_head = _bump(new_warc_head, -delta, True, "restore")
    restored_http = _bump(new_http_head, -delta, False, "restore") if new_http_head else new_http_head
    restored_body = new_body[:pos] + new_body[pos + delta:]
    if restored_head + sep1 + lead + restored_http + sep2 + restored_body != raw:
        raise InjectError(f"{trec_id}：還原檢查失敗")
    return Injection(
        raw=new_raw,
        inserted=delta,
        warc_cl_digits_delta=len(new_warc_head) - len(warc_head),
        http_cl_digits_delta=len(new_http_head) - len(http_head),
        has_http_cl=bool(CONTENT_LENGTH.search(http_head)),
    )


# ---------------------------------------------------------------------------
# 產生與驗收
# ---------------------------------------------------------------------------

def build(src: Path, dst: Path, targets: dict[str, str]) -> dict[str, Injection]:
    tmp = dst.with_name(dst.name + ".tmp")
    done: dict[str, Injection] = {}
    try:
        with open(tmp, "wb") as out:
            for raw in hw_bridge.iter_raw_records(src):
                tid = record_trec_id(raw)
                if tid in targets:
                    if tid in done:
                        raise InjectError(f"{tid} 在 WARC 中出現不只一次")
                    inj = inject(raw, targets[tid], tid)
                    done[tid] = inj
                    out.write(inj.raw)
                    log(f"injected {tid}: +{inj.inserted} B "
                        f"(HTTP Content-Length {'yes' if inj.has_http_cl else 'no'})")
                else:
                    out.write(raw)
        missing = sorted(set(targets) - set(done))
        if missing:
            raise InjectError(f"WARC 中找不到目標 record：{missing}")
        os.replace(tmp, dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return done


def verify(src: Path, dst: Path, targets: dict[str, str], done: dict[str, Injection]) -> bool:
    ok_all = True

    # 1. iter_documents：篇數與 docid 連續
    docids = [d for d, *_ in hw_bridge.iter_documents(dst)]
    contiguous = docids == list(range(docids[0], docids[0] + len(docids))) if docids else False
    ok1 = len(docids) == EXPECTED_DOCS and contiguous
    log(f"[1] iter_documents: n={len(docids):,} docid {docids[0] if docids else '-'}..{docids[-1] if docids else '-'} "
        f"contiguous={contiguous} -> {'PASS' if ok1 else 'FAIL'}")
    ok_all &= ok1

    # 2. inspect_targets：每篇 cleaned_text 含句子
    infos = hw_bridge.inspect_targets(dst, set(targets))
    ok2 = len(infos) == len(targets)
    for tid in sorted(targets):
        info = infos.get(tid)
        has = info is not None and info.cleaned_text is not None and targets[tid] in info.cleaned_text
        ok2 &= has
        log(f"[2] {tid} docid={info.docid if info else '-'} "
            f"content_type={info.content_type if info else '-'} contains_sentence={has}")
    log(f"[2] inspect_targets -> {'PASS' if ok2 else 'FAIL'}")
    ok_all &= ok2

    # 3 + 4. 逐筆比較
    n_rec = n_same = 0
    ok3 = ok4 = True
    seen: set[str] = set()
    sentinel = object()
    old_it, new_it = hw_bridge.iter_raw_records(src), hw_bridge.iter_raw_records(dst)
    while True:
        old, new = next(old_it, sentinel), next(new_it, sentinel)
        if old is sentinel or new is sentinel:
            if old is not new:
                log("[3] record 筆數不同")
                ok3 = False
            break
        n_rec += 1
        tid = record_trec_id(old)
        if tid in targets:
            seen.add(tid)
            diff = len(new) - len(old)
            inj = done[tid]
            extra = inj.warc_cl_digits_delta + inj.http_cl_digits_delta
            expected = inj.inserted + extra   # 插入位元組 + Content-Length 數字增加的位數
            exact = diff == expected
            ok4 &= exact
            log(f"[4] {tid}: size diff={diff} expected={expected} "
                f"(inserted={inj.inserted} + Content-Length digits={extra}) equal={exact}")
        elif old == new:
            n_same += 1
        else:
            ok3 = False
            log(f"[3] 非目標 record #{n_rec} ({tid}) 不相同")
    ok3 &= seen == set(targets) and n_same == n_rec - len(targets)
    log(f"[3] records={n_rec:,} non-target identical={n_same:,}/{n_rec - len(targets):,} -> {'PASS' if ok3 else 'FAIL'}")
    log(f"[4] size diff == inserted + Content-Length digit growth -> {'PASS' if ok4 else 'FAIL'}")
    ok_all &= ok3 and ok4

    log("\n目標 docid（gold_docids）：")
    for tok in C.get_config()["inject"]["tokens"]:
        ids = [infos[t].docid for t in tok["target_trec_ids"] if t in infos]
        log(f"  student_id={tok['student_id']}: {ids}  ({', '.join(tok['target_trec_ids'])})")
    log(f"\nALL_OK={ok_all}")
    return ok_all


def main() -> int:
    cfg = C.get_config()
    src, dst = cfg["corpus"]["source_warc"], cfg["corpus"]["injected_warc"]
    try:
        targets = load_targets(cfg)
        done = build(src, dst, targets)
    except InjectError as e:
        log(f"STOPPED: {e}")
        return 2
    log(f"wrote {dst}")
    return 0 if verify(src, dst, targets, done) else 1


if __name__ == "__main__":
    sys.exit(main())
