#!/usr/bin/env python3
"""
public-names.py —— 本 skill 仓库自己的「能不能公开」闸门（**不属于 skill 本体**，用 skill 的项目不需要它）。

思路：不维护「敏感词黑名单」（没人列得全自己不知道的东西），反过来维护**公开名白名单**
`release/public-names.allow`：仓库里每个「像专有名词」的词，必须在白名单里，否则报出来、退出码 1。
白名单只收**确认可以公开**的词（公开平台 / 通用技术词 / skill 自己定义的名字 / 占位符），
归 CODEOWNERS 管，**改它要仓库所有者批**——agent 不能自己往里加词来消红。

判断一个词能不能公开：陌生人看到它，能不能猜出你在哪工作、测过什么目标、你的电脑怎么找？三样都不能 ⇒ 可以。
拿不准的，**换成占位符**，不要加白名单。

「像专有名词」的认法（只认 ASCII；**认不出的必须靠人看**）：
    · 路径里的每一段、文件名去掉扩展名后的主干        `dir-a/sub_b/Thing.java` ⇒ dir-a, sub_b, Thing
    · 驼峰 / 小驼峰                                  `OrderMapping`, `getUser`
    · 大写缩写（≥3 个字符、≥2 个大写字母）            `PROJ-RUNTIME`, `AAIF`
    · 字母数字混写（≥4 个字符）                       `Abc123x`, `adr007`
    · 下划线 / 连字符连起来的词（**只在非代码文件里认**；代码里的标识符太多）
    ⚠️ 认不出：全小写的普通单词形态的代号、中文的项目名 / 客户名、写成句子的经历。这些靠人工复核。

用法
    python release/public-names.py                 # 扫仓库根（本文件上一级）
    python release/public-names.py --root <dir>
    python release/public-names.py --self-test     # 红样本：临时副本里塞一个白名单外的假代号，必须被拦
    python release/public-names.py --list          # 打印全部候选词（制白名单 / 复核用）
    python release/public-names.py --root pr --allow release/public-names.allow
                                                   # CI：脚本和白名单取基线那份，PR 的内容只当数据扫

退出码（只是提示，以哨兵行为准）
    0 = 全部候选词都在白名单里
    1 = 有白名单外的词
    2 = 拒绝给结论：白名单缺失 / 根目录无效 / 扫到的文件太少 / 红样本没被拦

哨兵行
    ###PUBLIC stamp=<VERIFY_RUN_STAMP|-> unknown=<n> allow=<n> dead=<n> files=<n> sha=<本脚本 12 位>
    · dead = 白名单里一次都没出现的词条数（不判红，但应定期清掉：死条目是给以后的真实名字留的门）
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ALLOW_REL = "release/public-names.allow"
RED_SAMPLE = "Zephyr" + "Q7"      # 假代号：**永远不许进白名单**；拆开写，免得本文件自己命中
MIN_FILES = 5
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".pytest_cache"}
CODE_SUFFIXES = {".py", ".js", ".mjs", ".ts", ".ps1", ".sh", ".java"}
TEXT_LIMIT = 2_000_000

TOKEN_RE = re.compile(r"[A-Za-z0-9_.\-/]+")
EXT_RE = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,5}$")
CAMEL_RE = re.compile(r"[a-z][A-Z]|[A-Z]{2,}[a-z]")
LETTER_RE = re.compile(r"[A-Za-z]")


def word_candidates(word: str, code: bool) -> list[str]:
    """一个不含 / 的词 ⇒ 0 或 1 个候选。"""
    w = word.strip(".-_")
    if len(LETTER_RE.findall(w)) < 2:
        return []
    m = EXT_RE.search(w)
    if m and m.start() > 0:
        w = w[: m.start()].strip(".-_")
        if len(LETTER_RE.findall(w)) < 2:
            return []
        return [w]                                   # 文件名主干一律算
    if CAMEL_RE.search(w):
        return [w]
    if len(w) >= 3 and sum(c.isupper() for c in w) >= 2 and not any(c.islower() for c in w):
        return [w]
    if len(w) >= 4 and any(c.isdigit() for c in w) and any(c.isalpha() for c in w):
        return [w]
    if not code and re.search(r"[A-Za-z][_-][A-Za-z]", w):
        return [w]
    return []


def candidates_in_line(line: str, code: bool) -> list[str]:
    out: list[str] = []
    for tok in TOKEN_RE.findall(line):
        tok = tok.strip(".,:;")
        if not tok:
            continue
        if "/" in tok and not tok.startswith(("http://", "https://")) and "//" not in tok:
            for seg in tok.split("/"):
                if not seg or seg in (".", ".."):
                    continue
                s = seg.strip(".-_")
                m = EXT_RE.search(s)
                stem = s[: m.start()] if (m and m.start() > 0) else s
                stem = stem.strip(".-_")
                if len(LETTER_RE.findall(stem)) >= 2:
                    out.append(stem)                 # 路径段一律算
        elif "/" not in tok:
            out.extend(word_candidates(tok, code))
    return out


def iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            rel = p.relative_to(root).as_posix()
            if rel == ALLOW_REL or fn == ".git":          # worktree 里的 .git 是指针文件，含本机路径
                continue
            yield p


def scan(root: Path):
    """⇒ (候选词 -> [(文件, 行号)], 扫描文件数, 读不了的文件)"""
    hits: dict[str, list[tuple[str, int]]] = {}
    files = 0
    skipped: list[str] = []
    for p in iter_files(root):
        rel = p.relative_to(root).as_posix()
        try:
            if p.stat().st_size > TEXT_LIMIT:
                skipped.append(rel)
                continue
            text = p.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            skipped.append(rel)
            continue
        files += 1
        code = p.suffix.lower() in CODE_SUFFIXES
        for c in candidates_in_line(rel, False):     # 文件名 / 目录名本身也是要公开的
            hits.setdefault(c, []).append((rel, 0))
        for i, line in enumerate(text.splitlines(), 1):
            for c in candidates_in_line(line, code):
                hits.setdefault(c, []).append((rel, i))
    return hits, files, skipped


def load_allow(path: Path) -> list[str]:
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.split("#", 1)[0].strip()
        if ln:
            out.append(ln)
    return out


def script_sha() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]


def run(root: Path, list_only: bool = False, quiet: bool = False,
        allow_path: Path | None = None) -> tuple[int, set[str]]:
    allow_path = allow_path or root / ALLOW_REL
    if not allow_path.is_file():
        print(f"🛑 拒绝给结论：找不到白名单 {allow_path}")
        return 2, set()
    allow = load_allow(allow_path)
    if RED_SAMPLE in allow:
        print(f"🛑 拒绝给结论：红样本 {RED_SAMPLE} 进了白名单（它必须永远被拦）")
        return 2, set()
    hits, files, skipped = scan(root)
    if files < MIN_FILES:
        print(f"🛑 拒绝给结论：只扫到 {files} 个文件（< {MIN_FILES}），根目录多半不对：{root}")
        return 2, set()
    if list_only:
        for w in sorted(hits, key=str.lower):
            f, n = hits[w][0]
            print(f"{w}\t{len(hits[w])}\t{f}:{n}")
        return 0, set()
    allow_set = set(allow)
    unknown = sorted((w for w in hits if w not in allow_set), key=str.lower)
    dead = sorted(a for a in allow_set if a not in hits)
    if not quiet:
        print(f"public-names: 扫描 {files} 个文件，候选词 {len(hits)} 个，白名单 {len(allow_set)} 条")
        if skipped:
            print(f"  读不了 / 太大（未查，需人看）：{len(skipped)} 个 —— " + ", ".join(skipped[:10]))
        print(f"\n[白名单外的词 —— 能公开就请仓库所有者加白名单；拿不准就换成占位符] {len(unknown)}")
        for w in unknown:
            locs = ", ".join(f"{f}:{n}" for f, n in hits[w][:3])
            print(f"  {w}  ({len(hits[w])} 处：{locs})")
        if dead:
            print(f"\n[白名单死条目 —— 仓库里已不出现，建议删] {len(dead)}")
            for a in dead:
                print(f"  {a}")
    if quiet:                                        # 红样本自测不出哨兵行，免得和正式那次混淆
        return (1 if unknown else 0), set(unknown)
    print(f"###PUBLIC stamp={os.environ.get('VERIFY_RUN_STAMP', '-')} unknown={len(unknown)} "
          f"allow={len(allow_set)} dead={len(dead)} files={files} sha={script_sha()}")
    return (1 if unknown else 0), set(unknown)


def self_test(root: Path, allow_path: Path | None = None) -> int:
    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / "repo"
        shutil.copytree(root, dst, ignore=shutil.ignore_patterns(*SKIP_DIRS))
        (dst / "red-sample.md").write_text(f"see `{RED_SAMPLE}` in the example\n", encoding="utf-8")
        rc, unknown = run(dst, quiet=True, allow_path=allow_path)
    if rc == 1 and RED_SAMPLE in unknown:
        print(f"✅ 红样本 {RED_SAMPLE} 被拦住了")
        return 0
    print(f"🛑 红样本 {RED_SAMPLE} **没被拦住**（rc={rc}）—— 闸门失效，拒绝给结论")
    return 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--allow", help="白名单路径（默认 <root>/release/public-names.allow）；CI 里指向基线那份，PR 改白名单不影响本次判定")
    a = ap.parse_args()
    root = Path(a.root).resolve()
    if not root.is_dir():
        print(f"🛑 不是目录：{root}")
        return 2
    allow = Path(a.allow).resolve() if a.allow else None
    if a.self_test:
        return self_test(root, allow)
    return run(root, list_only=a.list, allow_path=allow)[0]


if __name__ == "__main__":
    sys.exit(main())
