"""HW3 統一入口：`uv run python src/main.py <子指令> [選項]`（在 HW3/ 下執行）。

子指令註冊方式：在下方 COMMANDS 對應的模組中實作三項即可，不需要修改本檔或其他子指令：
- `HELP: str`：一行說明
- `add_arguments(parser: argparse.ArgumentParser) -> None`：加入自己的選項
- `run(args: argparse.Namespace) -> int`：執行並回傳 exit code

只匯入被選中的子指令模組（build 不載入 LLM，query 不載入建置路徑）；模組尚不存在時，
只有呼叫該子指令會報「尚未實作」。說明與錯誤訊息一律寫到 stderr（規格 1.6-6）。
"""
from __future__ import annotations

import argparse
import importlib
import sys

COMMANDS = {
    "build": "rag.build",      # A（規格 2.8）
    "query": "rag.cli",        # B（規格 3.4）
    "eval": "rag.evaluate",    # B（規格 3.5）
}


class _Parser(argparse.ArgumentParser):
    """說明寫到 stderr；參數錯誤時附上 epilog 中的範例。"""

    def print_help(self, file=None) -> None:
        super().print_help(file or sys.stderr)

    def error(self, message: str):
        self.print_usage(sys.stderr)
        extra = f"\n{self.epilog}" if self.epilog else ""
        self.exit(2, f"{self.prog}: error: {message}{extra}\n")


def _usage() -> str:
    names = "、".join(COMMANDS)
    return (f"用法：uv run python src/main.py <子指令> [選項]\n子指令：{names}\n"
            "各子指令的選項：uv run python src/main.py <子指令> -h")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(_usage(), file=sys.stderr)
        return 0 if argv else 2
    name = argv[0]
    if name not in COMMANDS:
        print(f"未知的子指令 {name!r}\n{_usage()}", file=sys.stderr)
        return 2
    module_name = COMMANDS[name]
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        if e.name != module_name:
            raise
        print(f"子指令 {name!r} 尚未實作（找不到模組 {module_name}）", file=sys.stderr)
        return 2
    parser = _Parser(prog=f"main.py {name}", description=getattr(module, "HELP", None))
    module.add_arguments(parser)
    return int(module.run(parser.parse_args(argv[1:])))


if __name__ == "__main__":
    sys.exit(main())
