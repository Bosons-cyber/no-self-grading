#!/usr/bin/env python3
"""<<脚本用途一句话>>

默认 dry-run：只打印将要做什么，不产生任何副作用。
确认无误后加 --write 才真正落盘。

用法：
    python <<script>>.py [--root .]            # 预览
    python <<script>>.py [--root .] --write    # 执行
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def plan(root: Path) -> list[tuple[str, Path]]:
    """只计算要做的动作，不执行。返回 (动作描述, 目标路径) 列表。"""
    actions: list[tuple[str, Path]] = []
    # <<在这里收集动作，例如：>>
    # for p in root.rglob("*.tmp"):
    #     actions.append(("delete", p))
    return actions


def execute(action: str, target: Path) -> None:
    """执行单个动作。只有 --write 时才会被调用。"""
    # <<在这里实现副作用>>
    raise NotImplementedError(action)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".", help="工作区根目录（默认当前目录）")
    ap.add_argument("--write", action="store_true", help="真正落盘；不加则只预览（dry-run）")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    actions = plan(root)
    mode = "WRITE" if args.write else "DRY-RUN"
    for action, target in actions:
        print(f"[{mode}] {action}: {target.relative_to(root)}")
        if args.write:
            execute(action, target)

    # 机器可读的最后一行：门禁 / 调用方只看这一行
    print(f"###DRYRUN mode={mode.lower()} actions={len(actions)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
