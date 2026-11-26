"""HW3 硬體試跑工具：量測本機 Ollama 上 embedding 模型與 LLM 的速度。

用途
  在不同組員的機器（Linux/WSL + NVIDIA、macOS Apple Silicon）上以相同流程
  量測 HW3（LLM + RAG）會用到的模型效能，輸出標準化 JSON 以便互相比較。

  - Embedding：以 batch 呼叫 embed_documents，第 1 批暖機，計時其餘批次，
    並推估全量 passage 所需時間。
  - LLM：暖機 1 次 + 正式 N 次；每次（含暖機）使用不同 seed 產生的文件，
    確保 Ollama 必須完整讀取 prompt（避免 prompt cache 使數字失真）。
  - 測 embedding 前卸載 LLM、測 LLM 前卸載 embedding 模型，避免搶 VRAM；
    測 LLM 前也先卸載 LLM 本身，清掉前一次執行殘留的 prompt cache。

需要
  - Ollama ≥ 0.11.10，服務已啟動，且已 `ollama pull` 所需模型
  - Python 套件（以 uv 臨時載入，不寫入 pyproject）：
      langchain-core langchain-ollama numpy

執行範例
  uv run --no-project --with langchain-core --with langchain-ollama --with numpy \\
      python HW3/tools/bench.py --owner <名字>

  只測其中一項：加上 --skip-llm 或 --skip-embed
  所有參數說明：python HW3/tools/bench.py --help

輸出
  - stdout：Markdown 表格 + 最後一行 RESULT
  - stderr：進度訊息
  - <output-dir>/bench_<owner>_<llm-model>.json（預設 HW3/tools/bench_results/）
  - <output-dir>/bench_<owner>_<llm-model>.stderr.log（stderr 進度訊息副本）
    模型名稱中不適合檔名的字元（如 :）會換成底線，例如 qwen3:8b → qwen3_8b
  JSON 不含 hostname、使用者名稱或家目錄路徑。
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import re
import resource
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
NA = "N/A"

# 測試內容與判讀門檻屬於「基準定義」而非執行參數，刻意保留為常數，
# 讓所有組員量的是同一份工作負載、用同一把尺判讀。
CMD_TIMEOUT_SEC = 60
MEM_SAMPLE_INTERVAL_SEC = 0.5
EMBED_RATING_MIN = (60, 180)      # 分鐘：< 60 良好、60–180 可接受、> 180 偏慢
LLM_RATING_SEC = (30, 90)         # 秒：< 30 良好、30–90 可接受、> 90 偏慢
RAM_WARN_GB = 16


_LOG_FH = None  # 進度訊息同時寫入 <output-dir>/<result_stem>.stderr.log


def log(msg: str) -> None:
    line = f"[bench] {msg}"
    print(line, file=sys.stderr, flush=True)
    if _LOG_FH is not None:
        _LOG_FH.write(line + "\n")
        _LOG_FH.flush()


def sh(cmd: list[str], timeout: int = CMD_TIMEOUT_SEC,
       env: dict | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env=env)
        return p.returncode, (p.stdout + p.stderr).strip()
    except FileNotFoundError:
        return -2, f"command not found: {cmd[0]}"
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- args
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="量測本機 Ollama 上 embedding 模型與 LLM 的速度（HW3 RAG 用）。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--owner", required=True,
                    help="執行者名稱（必填），用於 JSON 的 owner 欄位與輸出檔名 "
                         "bench_<owner>_<llm-model>.json")
    g = ap.add_argument_group("模型與連線")
    g.add_argument("--llm-model", default="qwen3:8b", help="要測速的 LLM 模型")
    g.add_argument("--embed-model", default="embeddinggemma",
                   help="要測速的 embedding 模型")
    g.add_argument("--ollama-url", default="http://localhost:11434",
                   help="Ollama 服務位址；HTTP 檢查、LangChain 用戶端與 ollama CLI"
                        "（透過 OLLAMA_HOST）都使用這個值")
    g.add_argument("--num-ctx", type=int, default=8192, help="LLM 的 context 長度")
    g.add_argument("--temperature", type=float, default=0.0, help="LLM 的 temperature")
    g = ap.add_argument_group("Embedding 測試")
    g.add_argument("--doc-prefix", default="title: none | text: ",
                   help="每段 passage 的前綴（含結尾空白）")
    g.add_argument("--query-prefix", default="task: search result | query: ",
                   help="查詢前綴（含結尾空白）；本工具不嵌入查詢，只記錄在 params 供 HW3 對照")
    g.add_argument("--n-passages", type=int, default=256, help="測試 passage 數量")
    g.add_argument("--passage-words", type=int, default=300,
                   help="每段 passage 的英文單字數；LLM 每份文件也用這個長度")
    g.add_argument("--batch-size", type=int, default=64,
                   help="embed_documents 每批數量（第 1 批為暖機不計時）")
    g.add_argument("--expected-dim", type=int, default=768,
                   help="預期向量維度，不符時寫入 errors")
    g.add_argument("--embed-seed", type=int, default=42, help="產生 passage 的 random seed")
    g.add_argument("--est-total-passages", type=int, default=120000,
                   help="推估全量所需時間時使用的 passage 總數")
    g = ap.add_argument_group("LLM 測試")
    g.add_argument("--llm-runs", type=int, default=3, help="正式執行次數（另加 1 次暖機）")
    g.add_argument("--llm-seed-base", type=int, default=1000,
                   help="LLM 文件 seed 起點：暖機用 base，第 i 次用 base+i")
    g = ap.add_argument_group("輸出與開關")
    g.add_argument("--output-dir", default="bench_results",
                   help="結果 JSON 目錄；相對路徑以本腳本所在資料夾為基準"
                        "（預設即 HW3/tools/bench_results）")
    g.add_argument("--skip-embed", action="store_true", help="跳過 embedding 測速")
    g.add_argument("--skip-llm", action="store_true", help="跳過 LLM 測速")
    args = ap.parse_args(argv)
    if args.skip_embed and args.skip_llm:
        ap.error("--skip-embed 與 --skip-llm 不能同時使用")
    for name in ("n_passages", "passage_words", "batch_size", "llm_runs",
                 "est_total_passages", "num_ctx"):
        if getattr(args, name) <= 0:
            ap.error(f"--{name.replace('_', '-')} 必須 > 0")
    if args.n_passages <= args.batch_size:
        ap.error("--n-passages 必須大於 --batch-size（第 1 批為暖機，至少需要 2 批）")
    if not re.fullmatch(r"[\w.-]+", args.owner):
        ap.error("--owner 只能包含英數、底線、點與連字號（會用於檔名）")
    args.ollama_url = args.ollama_url.rstrip("/")
    return args


def resolve_output_dir(raw: str) -> Path:
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (SCRIPT_DIR / p).resolve()


def result_stem(args: argparse.Namespace) -> str:
    """bench_<owner>_<llm-model>；模型名稱中不適合檔名的字元（如 : /）換成底線。"""
    model = re.sub(r"[^\w.-]", "_", args.llm_model)
    return f"bench_{args.owner}_{model}"


def params_for_json(args: argparse.Namespace) -> dict:
    """記錄本次所有參數；output_dir 只記錄相對於腳本的路徑，避免洩漏家目錄。"""
    d = {k: v for k, v in vars(args).items() if k != "owner"}
    out = resolve_output_dir(args.output_dir)
    try:
        d["output_dir"] = out.relative_to(SCRIPT_DIR).as_posix()
    except ValueError:
        d["output_dir"] = "<custom path outside HW3/tools>"
    return d


# ---------------------------------------------------------------- ollama
class Ollama:
    """包裝 ollama CLI 與 HTTP API；CLI 透過 OLLAMA_HOST 指向 --ollama-url。"""

    def __init__(self, url: str, errors: list[str], embed_model: str = ""):
        self.url = url
        self.embed_model = embed_model
        self.errors = errors
        self.cli = shutil.which("ollama")
        self.env = {**os.environ, "OLLAMA_HOST": url}
        if self.cli is None:
            errors.append("ollama CLI not found in PATH: cannot run `ollama ps` / "
                          "`ollama stop` (processor mode = N/A; models are unloaded "
                          "via HTTP API instead)")

    def server_version(self) -> str | None:
        try:
            with urllib.request.urlopen(f"{self.url}/api/version", timeout=10) as r:
                return json.loads(r.read().decode()).get("version")
        except (urllib.error.URLError, OSError, ValueError) as e:
            self.errors.append(f"ollama: cannot reach {self.url}/api/version: {e}")
            return None

    def stop(self, model: str) -> None:
        """卸載模型；無 CLI 時改用 HTTP API（keep_alive=0）卸載。"""
        if self.cli is not None:
            rc, out = sh([self.cli, "stop", model], env=self.env)
            log(f"ollama stop {model} -> rc={rc} {_strip_ansi(out)}")
            return
        endpoint = "embed" if model == self.embed_model else "generate"
        body = json.dumps({"model": model, "keep_alive": 0}).encode()
        req = urllib.request.Request(f"{self.url}/api/{endpoint}", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=CMD_TIMEOUT_SEC):
                pass
            log(f"unload {model} via {endpoint} API (keep_alive=0)")
        except (urllib.error.URLError, OSError) as e:
            self.errors.append(f"ollama: cannot unload {model} via API: {e}")

    def ps(self, model: str) -> tuple[str | None, list[str]]:
        """回傳 (model 的 PROCESSOR 欄位, 目前載入的所有模型名稱)。"""
        if self.cli is None:
            return None, []
        rc, out = sh([self.cli, "ps"], env=self.env)
        out = _strip_ansi(out)
        log(f"ollama ps:\n{out}")
        if rc != 0:
            self.errors.append(f"`ollama ps` failed (rc={rc}): {out}")
            return None, []
        lines = out.splitlines()
        if not lines:
            return None, []
        header = lines[0]
        start = header.find("PROCESSOR")
        end = header.find("CONTEXT") if "CONTEXT" in header else header.find("UNTIL")
        loaded, proc = [], None
        for line in lines[1:]:
            if not line.strip():
                continue
            name = line.split()[0]
            loaded.append(name)
            if _same_model(name, model):
                field = line[start:end].strip() if start >= 0 and end > start else ""
                if not field:  # 欄位對不齊時退回 regex
                    m = re.search(r"\d+%(?:/\d+%)?\s+(?:CPU/GPU|GPU|CPU)", line)
                    field = m.group(0) if m else ""
                proc = re.sub(r"\s+", " ", field)
        return proc, loaded


def _same_model(loaded_name: str, model: str) -> bool:
    want = model if ":" in model else f"{model}:latest"
    have = loaded_name if ":" in loaded_name else f"{loaded_name}:latest"
    return want == have


def _strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", s).strip()


# ---------------------------------------------------------------- A. hardware
def hardware_info(errors: list[str]) -> dict:
    system = platform.system()
    info = {"os": NA, "cpu": NA, "cores": os.cpu_count() or NA, "ram_gb": NA,
            "gpu": "none", "vram_gb": "none"}

    def fail(what: str, detail: str) -> None:
        errors.append(f"hardware: cannot detect {what}: {detail}")

    if system == "Linux":
        rel = platform.release()
        wsl = "microsoft" in rel.lower() or "wsl" in rel.lower()
        distro = "Linux"
        try:
            for line in Path("/etc/os-release").read_text().splitlines():
                if line.startswith("PRETTY_NAME="):
                    distro = line.split("=", 1)[1].strip('"')
        except OSError:
            pass
        info["os"] = f"{'WSL2 ' if wsl else ''}{distro} (kernel {rel})"
        try:
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    info["cpu"] = line.split(":", 1)[1].strip()
                    break
            else:
                fail("cpu", "no 'model name' in /proc/cpuinfo")
        except OSError as e:
            fail("cpu", str(e))
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal"):
                    info["ram_gb"] = round(int(line.split()[1]) / 1024**2, 1)
        except (OSError, ValueError) as e:
            fail("ram", str(e))
        if shutil.which("nvidia-smi"):
            rc, out = sh(["nvidia-smi", "--query-gpu=name,memory.total",
                          "--format=csv,noheader,nounits"])
            try:
                if rc != 0 or not out:
                    raise ValueError(out or f"rc={rc}")
                name, mem = [s.strip() for s in out.splitlines()[0].split(",")]
                info["gpu"], info["vram_gb"] = name, round(int(mem) / 1024, 1)
            except ValueError as e:
                info["gpu"] = info["vram_gb"] = NA
                fail("gpu (nvidia-smi)", str(e))
        # 沒有 nvidia-smi：視為沒有 NVIDIA GPU，gpu = "none"
    elif system == "Darwin":
        info["os"] = f"macOS {platform.mac_ver()[0] or '?'}"
        rc, brand = sh(["sysctl", "-n", "machdep.cpu.brand_string"])
        if rc == 0 and brand:
            info["cpu"] = brand
        else:
            fail("cpu", brand)
        rc, mem = sh(["sysctl", "-n", "hw.memsize"])
        if rc == 0 and mem.isdigit():
            info["ram_gb"] = round(int(mem) / 1024**3, 1)
        else:
            fail("ram", mem)
        rc, ncpu = sh(["sysctl", "-n", "hw.ncpu"])
        if rc == 0 and ncpu.isdigit():
            info["cores"] = int(ncpu)
        if platform.machine() == "arm64":
            chip = _mac_chip_name() or (brand if info["cpu"] != NA else None)
            if chip:
                info["gpu"] = f"Apple Silicon ({chip})"
            else:
                info["gpu"] = NA
                fail("gpu", "system_profiler returned no chip name")
            info["vram_gb"] = "unified"
    else:
        info["os"] = f"{system} {platform.release()}"
        info["cpu"] = platform.processor() or NA
        errors.append(f"hardware: unsupported OS {system}, partial info only")
    return info


def _mac_chip_name() -> str | None:
    rc, out = sh(["system_profiler", "SPHardwareDataType", "-json"])
    if rc == 0:
        try:
            hw = json.loads(out)["SPHardwareDataType"][0]
            return hw.get("chip_type") or hw.get("cpu_type")
        except (ValueError, KeyError, IndexError):
            pass
    rc, out = sh(["system_profiler", "SPDisplaysDataType"])
    m = re.search(r"Chipset Model:\s*(.+)", out) if rc == 0 else None
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------- D. memory
class MemSampler:
    """背景執行緒定期取樣 Ollama 相關程序的 RSS 總和（ps）。"""

    def __init__(self, interval: float = MEM_SAMPLE_INTERVAL_SEC):
        self.interval = interval
        self.peak_ollama_kb = 0
        self.ok = False
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _sample(self) -> None:
        rc, out = sh(["ps", "-axo", "rss=,args="], timeout=10)
        if rc != 0:
            return
        total = 0
        for line in out.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0].isdigit() and "ollama" in parts[1].lower():
                total += int(parts[0])
        if total > 0:
            self.ok = True
            self.peak_ollama_kb = max(self.peak_ollama_kb, total)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._sample()
            self._stop.wait(self.interval)

    def start(self) -> None:
        self._t.start()

    def stop(self) -> None:
        self._stop.set()
        self._t.join(timeout=5)


def python_peak_gb() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / 1024**3 if platform.system() == "Darwin" else r / 1024**2


# ---------------------------------------------------------------- test text
VOCAB = (
    "retrieval index query document corpus ranking model vector embedding "
    "passage relevance score search engine user information system language "
    "network data training evaluation result method approach analysis study "
    "research paper experiment performance accuracy precision recall metric "
    "the of and to in a is that for on with as by this are be from at an "
    "which it or have has was were can will would could should may also "
    "between within across under over after before during while because "
    "neural semantic lexical dense sparse token context answer question "
    "large small fast slow simple complex robust efficient effective new"
).split()


def make_passage(rng: random.Random, n_words: int) -> str:
    words, sent = [], []
    for _ in range(n_words):
        sent.append(rng.choice(VOCAB))
        if len(sent) >= rng.randint(8, 18):
            sent[0] = sent[0].capitalize()
            words.append(" ".join(sent) + ".")
            sent = []
    if sent:
        sent[0] = sent[0].capitalize()
        words.append(" ".join(sent) + ".")
    return " ".join(words)


# ---------------------------------------------------------------- B. embed
def bench_embed(args: argparse.Namespace, ol: Ollama, errors: list[str]) -> dict:
    import numpy as np
    from langchain_ollama import OllamaEmbeddings

    res = {}
    ol.stop(args.llm_model)
    rng = random.Random(args.embed_seed)
    texts = [args.doc_prefix + make_passage(rng, args.passage_words)
             for _ in range(args.n_passages)]
    bs = args.batch_size
    batches = [texts[i:i + bs] for i in range(0, len(texts), bs)]
    emb = OllamaEmbeddings(model=args.embed_model, base_url=args.ollama_url)

    log(f"embed warmup batch (n={len(batches[0])})")
    emb.embed_documents(batches[0])  # 暖機，丟棄
    proc, loaded = ol.ps(args.embed_model)
    res["embed_processor_mode"] = proc
    if proc is None and ol.cli is not None:
        errors.append(f"embed: {args.embed_model} not found in `ollama ps` "
                      f"(loaded={loaded})")

    vecs, n_timed = [], 0
    t0 = time.perf_counter()
    for i, b in enumerate(batches[1:], start=2):
        log(f"embed batch {i}/{len(batches)}")
        vecs.extend(emb.embed_documents(b))
        n_timed += len(b)
    dt = time.perf_counter() - t0

    arr = np.asarray(vecs, dtype=np.float64)
    pps = n_timed / dt
    res["embed_passages_per_sec"] = round(pps, 2)
    res["embed_dim"] = int(arr.shape[1])
    res["embed_norm_mean"] = round(float(np.linalg.norm(arr, axis=1).mean()), 4)
    res["embed_est_total_min_for_120k"] = round(args.est_total_passages / pps / 60, 1)
    if res["embed_dim"] != args.expected_dim:
        errors.append(f"embed: unexpected dim {res['embed_dim']} "
                      f"(expected {args.expected_dim})")
    log(f"embed: {n_timed} passages in {dt:.2f}s -> {pps:.2f} p/s")
    return res


# ---------------------------------------------------------------- C. LLM
LLM_DOCS = [
    ("Harbor Library", "The Harbor Library opened in 1987 and holds about "
     "forty thousand volumes on maritime history, shipbuilding and navigation."),
    ("Northfield Rail", "The Northfield rail line was extended in 2004 and now "
     "connects six towns with a travel time of roughly fifty minutes."),
    ("Lakeside Festival", "The Lakeside Music Festival takes place every July; "
     "in 2019 it attracted a record attendance of 23,500 visitors."),
    ("Old Mill Museum", "The Old Mill Museum is housed in a restored grain "
     "mill built in 1862 and is closed every Monday for maintenance."),
    ("City Orchard", "The City Orchard project planted 1,200 apple and pear "
     "trees between 2015 and 2018 on former industrial land."),
]
LLM_QUESTION = ("How many visitors attended the Lakeside Music Festival in its "
                "record year, and in which year was that?")
LLM_SYSTEM = ("You are a helpful assistant. Answer ONLY based on the provided "
              "documents. If the documents do not contain the answer, say you "
              "do not know. Cite the document number you used.")


def build_llm_user_prompt(seed: int, doc_words: int) -> str:
    """每個 seed 產生不同的文件內容，避免 Ollama prompt cache 重用前次結果。"""
    rng = random.Random(seed)
    parts = []
    for i, (title, fact) in enumerate(LLM_DOCS, start=1):
        uid = f"Ref-{seed}-{i}-{rng.randrange(10**8):08d}."
        filler = make_passage(rng, max(1, doc_words - len(fact.split()) - 1))
        parts.append(f"[Document {i}] {title}\n{uid} {fact} {filler}")
    return "\n\n".join(parts) + f"\n\nQuestion: {LLM_QUESTION}"


def bench_llm(args: argparse.Namespace, ol: Ollama, errors: list[str]) -> dict:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_ollama import ChatOllama

    res = {"_runs": [], "_warmup_load_sec": None}
    model = args.llm_model
    ol.stop(args.embed_model)
    # 也卸載 LLM 本身：seed 固定，若模型仍駐留（例如剛跑完上一次 bench），
    # 前次的 prompt cache 會讓 prompt 讀取速度嚴重失真。
    ol.stop(model)
    _, loaded = ol.ps(model)
    others = [m for m in loaded if not _same_model(m, model)]
    if others:
        errors.append(f"llm: other models still loaded before LLM bench: {others}")

    llm = ChatOllama(model=model, base_url=args.ollama_url,
                     temperature=args.temperature, num_ctx=args.num_ctx,
                     reasoning=False)

    def make_msgs(seed: int) -> list:
        return [SystemMessage(content=LLM_SYSTEM),
                HumanMessage(content=build_llm_user_prompt(seed, args.passage_words))]

    log(f"llm warmup (seed={args.llm_seed_base})")
    w = llm.invoke(make_msgs(args.llm_seed_base))
    wl = w.response_metadata.get("load_duration")
    res["_warmup_load_sec"] = round(wl / 1e9, 3) if wl is not None else None
    proc, loaded = ol.ps(model)
    res["llm_processor_mode"] = proc
    if proc is None and ol.cli is not None:
        errors.append(f"llm: {model} not found in `ollama ps` (loaded={loaded})")
    others = [m for m in loaded if not _same_model(m, model)]
    if others:
        errors.append(f"llm: other models loaded during LLM bench: {others}")

    runs = []
    for i in range(1, args.llm_runs + 1):
        seed = args.llm_seed_base + i  # 每次正式執行使用不同文件內容
        log(f"llm run {i}/{args.llm_runs} (seed={seed})")
        msgs = make_msgs(seed)
        t0 = time.perf_counter()
        r = llm.invoke(msgs)
        total = time.perf_counter() - t0
        md = r.response_metadata
        pec, ped = md.get("prompt_eval_count"), md.get("prompt_eval_duration")
        ec, ed = md.get("eval_count"), md.get("eval_duration")
        content = r.content if isinstance(r.content, str) else str(r.content)
        run = {
            "seed": seed,
            "total_sec": round(total, 3),
            "load_sec": round(md["load_duration"] / 1e9, 3)
            if md.get("load_duration") is not None else None,
            "prompt_eval_count": pec,
            "prompt_eval_sec": round(ped / 1e9, 3) if ped else None,
            "prompt_tokens_per_sec": round(pec / (ped / 1e9), 2) if pec and ped else None,
            "eval_count": ec,
            "eval_sec": round(ed / 1e9, 3) if ed else None,
            "tokens_per_sec": round(ec / (ed / 1e9), 2) if ec and ed else None,
            "think_leak": "<think>" in content,
            "answer_preview": content[:200],
        }
        log(f"llm run {i}: {json.dumps(run, ensure_ascii=False)}")
        runs.append(run)

    def avg(key):
        vals = [r[key] for r in runs if r[key] is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    res["_runs"] = runs
    res["llm_avg_total_sec"] = avg("total_sec")
    res["llm_avg_prompt_tokens_per_sec"] = avg("prompt_tokens_per_sec")
    res["llm_avg_tokens_per_sec"] = avg("tokens_per_sec")
    res["llm_load_sec"] = avg("load_sec")
    res["llm_think_leak"] = any(r["think_leak"] for r in runs)
    if res["llm_think_leak"]:
        errors.append("llm: '<think>' found in answer despite reasoning=False")
    return res


# ---------------------------------------------------------------- report
EMBED_KEYS = ("embed_processor_mode", "embed_passages_per_sec", "embed_dim",
              "embed_norm_mean", "embed_est_total_min_for_120k")
LLM_KEYS = ("llm_processor_mode", "llm_avg_total_sec", "llm_avg_prompt_tokens_per_sec",
            "llm_avg_tokens_per_sec", "llm_load_sec", "llm_think_leak")


def rate_embed(m):
    if not isinstance(m, (int, float)):
        return NA
    lo, hi = EMBED_RATING_MIN
    return "良好" if m < lo else "可接受" if m <= hi else "偏慢（建議減少 passage 數）"


def rate_llm(s):
    if not isinstance(s, (int, float)):
        return NA
    lo, hi = LLM_RATING_SEC
    return "良好" if s < lo else "可接受" if s <= hi else "偏慢（建議改用較小模型）"


def main(argv: list[str] | None = None) -> int:
    global _LOG_FH
    args = parse_args(argv)
    errors: list[str] = []
    out_dir = resolve_output_dir(args.output_dir)
    stem = result_stem(args)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        _LOG_FH = open(out_dir / f"{stem}.stderr.log", "w", encoding="utf-8")
    except OSError as e:
        errors.append(f"output: cannot open stderr log: {e}")
    out: dict = {"owner": args.owner}
    log("collecting hardware info")
    out.update(hardware_info(errors))

    ol = Ollama(args.ollama_url, errors, embed_model=args.embed_model)
    out["ollama_version"] = ol.server_version() or NA

    sampler = MemSampler()
    sampler.start()
    embed, llm = {}, {}
    if args.skip_embed:
        log("embed: skipped (--skip-embed)")
    else:
        try:
            embed = bench_embed(args, ol, errors)
        except Exception as e:  # noqa: BLE001
            errors.append(f"embed: {type(e).__name__}: {e}")
    if args.skip_llm:
        log("llm: skipped (--skip-llm)")
    else:
        try:
            llm = bench_llm(args, ol, errors)
        except Exception as e:  # noqa: BLE001
            errors.append(f"llm: {type(e).__name__}: {e}")
    sampler.stop()

    skip_val = "skipped"
    for k in EMBED_KEYS:
        out[k] = skip_val if args.skip_embed else embed.get(k, NA if k.endswith("mode") else None)
    for k in LLM_KEYS:
        out[k] = skip_val if args.skip_llm else llm.get(k, NA if k.endswith("mode") else None)
    if out["embed_processor_mode"] is None:
        out["embed_processor_mode"] = NA
    if out["llm_processor_mode"] is None:
        out["llm_processor_mode"] = NA

    py_gb = python_peak_gb()
    if sampler.ok:
        out["peak_mem_gb"] = round(sampler.peak_ollama_kb / 1024**2 + py_gb, 2)
        mem_note = (f"ollama RSS {sampler.peak_ollama_kb / 1024**2:.2f} GB + "
                    f"python {py_gb:.2f} GB（不含 VRAM）")
    else:
        out["peak_mem_gb"] = NA
        mem_note = "無法取得 Ollama 程序記憶體（Ollama 可能不在本機或 ps 無法讀取）"

    # 獨立 GPU 規則：非 100% GPU 則數字無效（Apple Silicon 不適用）
    gpu = str(out["gpu"])
    discrete = gpu not in ("none", NA) and not gpu.startswith("Apple Silicon")
    embed_invalid = llm_invalid = False
    if discrete:
        if not args.skip_embed and out["embed_processor_mode"] != "100% GPU":
            embed_invalid = True
            errors.append(f"embed_processor_mode is '{out['embed_processor_mode']}', "
                          "not 100% GPU -> embed numbers INVALID")
        if not args.skip_llm and out["llm_processor_mode"] != "100% GPU":
            llm_invalid = True
            errors.append(f"llm_processor_mode is '{out['llm_processor_mode']}', "
                          "not 100% GPU -> LLM numbers INVALID")
    out["errors"] = errors
    out["params"] = params_for_json(args)

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / f"{stem}.json"
        json_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
        log(f"wrote {json_path}")
    except OSError as e:
        errors.append(f"output: cannot write JSON: {e}")
        log(f"ERROR: cannot write JSON: {e}")

    inv_e = "（無效）" if embed_invalid else ""
    inv_l = "（無效）" if llm_invalid else ""
    print("| 項目 | 數值 |\n|---|---|")
    for k, v in out.items():
        if k in ("errors", "params"):
            continue
        suffix = inv_e if k.startswith("embed_") else inv_l if k.startswith("llm_") else ""
        print(f"| {k} | {v}{suffix} |")
    for i, r in enumerate(llm.get("_runs", []), start=1):
        print(f"| llm_run{i} | total {r['total_sec']}s, load {r['load_sec']}s, "
              f"prompt {r['prompt_eval_count']} tok @ {r['prompt_tokens_per_sec']} tok/s, "
              f"gen {r['eval_count']} tok @ {r['tokens_per_sec']} tok/s, "
              f"think={r['think_leak']} |")
    if llm.get("_warmup_load_sec") is not None:
        print(f"| llm_warmup_load_sec（冷載入） | {llm['_warmup_load_sec']} |")
    print(f"| peak_mem 說明 | {mem_note} |")
    print(f"| errors | {'; '.join(errors) if errors else '(none)'} |")
    print(f"| 判讀：embed {args.est_total_passages} 段 | "
          f"{rate_embed(out['embed_est_total_min_for_120k'])}{inv_e} |")
    print(f"| 判讀：LLM 每題 | {rate_llm(out['llm_avg_total_sec'])}{inv_l} |")
    ram = out["ram_gb"]
    ram_msg = (f"< {RAM_WARN_GB} GB，跑 {args.llm_model} 可能吃緊"
               if isinstance(ram, (int, float)) and ram < RAM_WARN_GB
               else "足夠" if isinstance(ram, (int, float)) else NA)
    print(f"| 判讀：RAM | {ram_msg} |")

    has_gpu = "有" if gpu not in ("none", NA) else "無"
    print(f"\nRESULT | {args.owner} | embed 120k 約 {out['embed_est_total_min_for_120k']} 分鐘 | "
          f"LLM 每題約 {out['llm_avg_total_sec']} 秒"
          f"（讀 prompt {out['llm_avg_prompt_tokens_per_sec']} tok/s） | "
          f"GPU: {has_gpu}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
