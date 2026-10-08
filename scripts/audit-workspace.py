#!/usr/bin/env python3
"""audit-workspace.py —— 工作区「agent 友好度」事实采集（只读，不做判断）。

定位
    它**不给建议、不打分**，只把评估所需的客观事实压成一份紧凑清单，
    让 agent 不必为了「有没有版本控制 / 哪些目录是外来大件 / 文档散在哪 / 有没有重复副本」
    去读几十个文件 —— 这正是本技能主张的 token 效率。

用法
    python audit-workspace.py                          # 人类可读
    python audit-workspace.py --root /path/to/repo
    python audit-workspace.py --json                   # 机器可读（喂给打分/修复流程）
    python audit-workspace.py --top 30                 # 各列表最多显示几条
    python audit-workspace.py --skip vendor --skip tmp # 追加跳过目录名

与 verify-refs.py 共享「agent 视野」
    若 `<root>/.agent-ready.json` 存在，本脚本会读取其中的 `skip_dirs` / `skip_prefixes`，
    与被检仓库的引用自检保持同一口径 —— 一个配置定义「哪些内容 agent 应该关心」。

输出章节
    0. 平台画像            探测仓库**已经**在用哪些 agent 平台的约定（AGENTS.md / .cursor/rules /
                          CLAUDE.md / Copilot instructions / …），含置信度与嵌套 AGENTS.md 计数。
                          只陈述事实；「该新建什么」的决策表在技能 references/platform-mapping.md。
    1. 仓库与版本控制      git 状态、.gitignore 覆盖情况
    2. 目录概览            顶层目录的文件数与**源码体积**（已排除 node_modules/dist/build 等）
    3. 大目录 / 敏感文件    体积超阈值者；私钥/凭据类文件及其 ignore 状态
    4. 入口与治理文档      入口文件、状态/规范/记忆/规则目录（根 + 两层子目录）；
                          **平台中立** —— 候选名覆盖 AGENTS.md / CLAUDE.md / GEMINI.md /
                          CODEBUDDY.md / Copilot instructions 等，任一存在即算「有」
    5. 文档库存            文档与代码数量分布
    6. 重复内容嫌疑        同名 + 同内容**跨目录组**出现 = SSOT 违规信号（已去噪）
    7. 交接缺口            多方向容器下缺失的状态文件
    8. 信号计数            把上述 ❌ 项汇总成计数，便于快速打分
    9. 概念碎片            公共符号里同一概念的多个名字：有 vocab.json 时按词表查别名 / 退役 id /
                          词表自身冲突；词表管不到的部分用内置近义词组报嫌疑。解析失败单独计数，不静默跳过
    10. 草稿区边界         草稿区（默认 scratch/，可在 .agent-ready.json 的 scratch_dirs 改）之外的代码
                          import 了草稿区 = 屎山顺着 import 流进来。先解析成仓库内路径再判断，解析失败单独计数

退出码：0 = 采集完成；2 = 路径无效。
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

CONFIG_NAME = ".agent-ready.json"

SKIP_DIR_PARTS = {
    "__pycache__", "node_modules", ".git", ".svn", ".hg", ".venv", "venv",
    ".idea", ".vscode", ".mypy_cache", ".pytest_cache", "dist", "build", "target",
}
DOC_SUFFIXES = {".md", ".txt", ".rst", ".adoc"}
CODE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".mjs", ".java", ".go", ".rs",
                 ".c", ".cpp", ".h", ".rb", ".php", ".cs", ".vue", ".kt", ".swift"}

# 强凭据特征：文件名本身就是凭据容器（不靠关键词猜）
SENSITIVE_STRONG = re.compile(
    r"^(id_(rsa|dsa|ecdsa|ed25519)(\.pub)?|\.env(\..+)?|"
    r"credentials?\.(ya?ml|json|ini|toml|conf)|secrets?\.(ya?ml|json|ini|toml)|"
    r".+\.(pem|p12|pfx|key|keystore|jks|ppk|asc)|.+_rsa|.+_ed25519)$",
    re.I,
)
# 弱特征：**整个文件名主体就是「凭据容器名」**才算（credentials.yaml / api_key.txt / db-password.conf）。
# 不用「包含关键词」——那会把 「YYYY-MM-DD-credential-handling-notes.md」这类描述性文档名全捞进来。
SENSITIVE_WEAK = re.compile(
    r"^(credentials?|secrets?|passwords?|passwd|api[_-]?keys?|apikeys?|tokens?|auth|"
    r"db[_-]?password|access[_-]?keys?)$",
    re.I,
)
TEXT_SUFFIXES = DOC_SUFFIXES | CODE_SUFFIXES

BIG_DIR_MB = 30
DUP_MIN_BYTES = 256          # 小于此体积的重复文件多为样板，不报
HASH_MAX_BYTES = 2 * 1024 * 1024

# 平台中立的候选清单：下列位置「有就用，没有就跳过」，不假设任何单一 agent 平台。
# 概念 → 各平台落点的完整对应关系见技能的 references/platform-mapping.md。
AGENT_ENTRY_CANDIDATES = (              # agent 入口文档（任一存在即算「有」）
    "AGENTS.md",                        # 跨工具通用，兼容性最好
    "CLAUDE.md",                        # Claude Code
    "GEMINI.md",                        # Gemini CLI
    "CODEBUDDY.md",                     # CodeBuddy
    ".github/copilot-instructions.md",  # GitHub Copilot
    ".cursorrules",                     # Cursor（旧写法）
    "CONVENTIONS.md",                   # Aider / 其他
)
HUMAN_ENTRY_CANDIDATES = ("README.md",)
GOV_CANDIDATES = ("STATUS.md", "STRUCTURE.md", "CONTRIBUTING.md", "ROADMAP.md")
MEMORY_CANDIDATES = (                   # 跨会话记忆的常见落点
    ".codebuddy/memory", ".claude/memory", ".agents/memory",
    "memory", "MEMORY.md", "docs/memory",
)
RULE_DIR_CANDIDATES = (                 # 「始终生效的规则」常见落点（多平台可共存）
    ".codebuddy/rules", ".cursor/rules", ".windsurf/rules",
    ".github/instructions", ".continue",
    ".claude", ".agents", ".rules",
)
# 点目录默认跳过，但这些是「平台治理目录」，属于 agent 视野 → 需要遍历
GOVERNANCE_DOT_DIRS = {
    ".codebuddy", ".cursor", ".claude", ".agents",
    ".windsurf", ".continue", ".github",
}
HANDOFF_CONTAINERS = ("teams", "streams", "directions", "workstreams", "modules", "packages")

# 平台签名：探测「目标仓库已经在用什么约定」。只做**事实探测**，不产出建议 ——
# 「该新建什么」的决策表在 references/platform-mapping.md（带来源 / 日期 / 置信度）。
PLATFORM_SIGNATURES: dict[str, dict] = {
    "agents-md": {
        "desc": "跨工具通用（官方站列 23 个工具支持，AAIF / Linux 基金会托管）",
        "confidence": "官方",
        "signatures": ("AGENTS.md", "AGENT.md"),
    },
    "cursor": {
        "desc": "Cursor 规则（.cursor/rules 下文件必须是 .mdc，否则被忽略）",
        "confidence": "官方",
        "signatures": (".cursor/rules", ".cursorrules"),
    },
    "claude-code": {
        "desc": "Claude Code",
        "confidence": "高可信二手",
        "signatures": ("CLAUDE.md", ".claude"),
    },
    "copilot": {
        "desc": "GitHub Copilot（仓库级 + 路径级 instructions）",
        "confidence": "官方",
        "signatures": (".github/copilot-instructions.md", ".github/instructions"),
    },
    "gemini-cli": {
        "desc": "Gemini CLI（默认 GEMINI.md，文件名可配置）",
        "confidence": "官方",
        "signatures": ("GEMINI.md", ".gemini/settings.json"),
    },
    "codebuddy": {
        "desc": "CodeBuddy",
        "confidence": "观察",
        "signatures": ("CODEBUDDY.md", ".codebuddy"),
    },
    "windsurf": {
        "desc": "Windsurf",
        "confidence": "未核实",
        "signatures": (".windsurf/rules", ".windsurfrules"),
    },
    "aider": {
        "desc": "Aider",
        "confidence": "官方",
        "signatures": (".aider.conf.yml", ".aider.conf.yaml"),
    },
    "continue": {
        "desc": "Continue",
        "confidence": "未核实",
        "signatures": (".continue",),
    },
}


# ---------------------------------------------------------------------------
def du(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def load_skip(root: Path, explicit: str | None) -> tuple[set[str], tuple[str, ...]]:
    path = Path(explicit) if explicit else (root / CONFIG_NAME)
    skip_dirs, skip_prefixes = set(), ()
    if path.is_file():
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            skip_dirs = set(d.get("skip_dirs") or ())
            skip_prefixes = tuple(d.get("skip_prefixes") or ())
        except (OSError, json.JSONDecodeError):
            pass
    return skip_dirs, skip_prefixes


def _prune(names, rel: str, skip_dirs: set[str], skip_prefixes: tuple[str, ...]):
    """过滤目录。

    点目录默认跳过，**但**平台治理目录（各 agent 平台的 rules / memory 落点）例外 ——
    它们是 agent 视野的一部分。集合见 GOVERNANCE_DOT_DIRS，不偏向任何单一平台。
    """
    kept = []
    for x in sorted(names):
        if x in skip_dirs:
            continue
        if x.startswith(".") and x not in GOVERNANCE_DOT_DIRS:
            continue
        child = f"{rel}/{x}/" if rel else f"{x}/"
        if any(child.startswith(p) for p in skip_prefixes):
            continue
        kept.append(x)
    return kept


def read_gitignore(root: Path) -> list[str]:
    f = root / ".gitignore"
    if not f.is_file():
        return []
    try:
        return [ln.strip() for ln in f.read_text(encoding="utf-8", errors="replace").splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
    except OSError:
        return []


def is_gitignored(rel: str, patterns: list[str]) -> bool:
    """best-effort：文件名 / 祖先目录 / glob 三种规则形态。"""
    segs = rel.split("/")
    for p in patterns:
        s = p.lstrip("/").rstrip("/")
        if s.startswith("**/"):
            s = s[3:]
        if not s:
            continue
        if s.endswith("/"):                      # 目录规则
            base = s.rstrip("/")
            if any("/".join(segs[: i + 1]) == base for i in range(len(segs))):
                return True
        elif "*" in s or "?" in s:
            if fnmatch.fnmatch(segs[-1], s) or fnmatch.fnmatch(rel, s):
                return True
        else:
            if rel == s or rel.startswith(s + "/") or segs[0] == s:
                return True
    return False


def run_git(root: Path) -> dict:
    def git(*a):
        try:
            r = subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True,
                               timeout=30, encoding="utf-8", errors="replace")
            return r.returncode, (r.stdout or "").strip()
        except (OSError, subprocess.SubprocessError):
            return 1, ""
    out = {"is_repo": False, "branch": None, "dirty_files": None, "tracked_files": None}
    if git("rev-parse", "--is-inside-work-tree")[0] != 0:
        return out
    out["is_repo"] = True
    out["branch"] = git("rev-parse", "--abbrev-ref", "HEAD")[1] or None
    rc, s = git("status", "--porcelain")
    out["dirty_files"] = len([x for x in s.splitlines() if x.strip()]) if rc == 0 else None
    rc, s = git("ls-files")
    out["tracked_files"] = len(s.splitlines()) if rc == 0 else None
    return out


def find_one_level(root: Path, names: tuple[str, ...], max_depth: int = 2,
                   skip_dirs: set[str] | None = None,
                   skip_prefixes: tuple[str, ...] = ()) -> dict:
    """在根 + 两层子目录里找这些文件，返回 {name: [相对路径...]}。

    平台中立：候选名由调用方给出，不假设任何单一平台的目录布局。
    含 `/` 的候选（如 `.github/copilot-instructions.md`）按**根相对存在性**直接判定。
    遵守配置的跳过规则 —— 否则会在「外部只读依赖」里误判为「本项目已有入口文档」。
    """
    found: dict[str, list[str]] = {n: [] for n in names}
    flat = tuple(n for n in names if "/" not in n)
    all_skip = SKIP_DIR_PARTS | (skip_dirs or set())
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        rel = d.relative_to(root).as_posix()
        rel = "" if rel == "." else rel
        if rel.count("/") >= max_depth:
            dirnames[:] = []
        else:
            dirnames[:] = _prune(dirnames, rel, all_skip, skip_prefixes)
        for n in flat:
            if n in filenames:
                found[n].append(f"{rel}/{n}" if rel else n)
    for n in names:
        if "/" in n and (root / n).is_file():
            found[n].append(n)
    return found


# ---------------------------------------------------------------------------
# 概念碎片（concept fragmentation）
#
# LLM 每次会话都没有记忆，同一个概念这次叫 user、下次叫 account、再下次叫 member。
# 文件级的重复（第 6 节）查不出这种分叉，因为每份代码内容都不同，只是「指同一个东西的名字」变多了。
#
# 口径：
#   - 有词表（vocab.json）时，词表是唯一判据：公共符号里用了别名、用了已退役的 id、
#     词表自身的冲突（同一别名挂两个概念、别名撞别人的正式名、退役 id 被复用、概念缺「不是什么」）都计数。
#   - 词表管不到的部分，用下面这组内置近义词做**嫌疑**提示，只报事实，不下结论。
#     项目可以在 .agent-ready.json 的 `concept_synonyms` 里追加组，或在 `concept_ignore` 里屏蔽组（按组内首词）。
#   - 只看公共符号（Python 顶层 / 类内不以 _ 开头的 def、class；其他语言按 export / pub / public / 首字母大写），
#     私有局部变量随便起名，不算碎片。
#   - 不静默跳过：枚举到的代码文件 == 解析成功 + 解析失败 + 不支持的后缀，三者分别计数并做自洽断言。
# ---------------------------------------------------------------------------
VOCAB_DEFAULT_PATHS = ("vocab.json", "docs/vocab.json")
VOCAB_SEMVER = re.compile(r"^\d+\.\d+(\.\d+)?$")

# 内置近义 / 缩写组：只放「在多数项目里确实常指同一个东西」的名词。
# 宁缺毋滥 —— 误报多了大家就不看了。item、task/job、error/exception 这类在很多项目里本来就是两个概念，故意不放。
BUILTIN_SYNONYMS: tuple[tuple[str, ...], ...] = (
    ("user", "account", "member", "customer", "usr"),
    ("organization", "organisation", "org", "tenant", "company"),
    ("config", "configuration", "setting", "option", "preference", "cfg", "conf"),
    ("product", "goods", "commodity", "sku"),
    ("order", "purchase"),
    ("message", "msg"),
    ("password", "passwd", "pwd"),
    ("request", "req"),
    ("response", "resp"),
    ("document", "doc"),
    ("employee", "staff", "worker"),
    ("invoice", "bill"),
)

PUBLIC_SYMBOL_PATTERNS: dict[str, tuple[re.Pattern, ...]] = {
    "js": (re.compile(r"^\s*export\s+(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?(?:async\s+)?"
                      r"(?:function\*?|class|interface|type|enum|const|let|var)\s+([A-Za-z_$][\w$]*)", re.M),),
    "go": (re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Z]\w*)", re.M),
           re.compile(r"^type\s+([A-Z]\w*)", re.M)),
    "rust": (re.compile(r"^\s*pub(?:\([^)]*\))?\s+(?:async\s+)?(?:fn|struct|enum|trait|type|const)\s+([A-Za-z_]\w*)", re.M),),
    "jvm": (re.compile(r"\bpublic\s+(?:(?:static|final|abstract|sealed|partial|data|open)\s+)*"
                       r"(?:class|interface|enum|record|object)\s+([A-Za-z_]\w*)", re.M),),
}
SUFFIX_LANG = {
    ".js": "js", ".mjs": "js", ".ts": "js", ".tsx": "js", ".vue": "js",
    ".go": "go", ".rs": "rust",
    ".java": "jvm", ".kt": "jvm", ".cs": "jvm", ".swift": "jvm",
}


def split_identifier(name: str) -> list[str]:
    """getUserAccount / get_user_account / GetUserAccount / HTTPRequest -> 小写、粗单数化的词元。"""
    parts = re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+", name)
    out = []
    for p in parts:
        t = p.lower()
        if len(t) > 4 and t.endswith("ies"):
            t = t[:-3] + "y"
        elif len(t) > 3 and t.endswith("s") and not t.endswith(("ss", "us", "is")):
            t = t[:-1]
        out.append(t)
    return out


def public_symbols(path: Path, suffix: str) -> tuple[str, list[str]]:
    """返回 (状态, 符号列表)。状态：parsed / failed / unsupported。"""
    if suffix == ".py":
        import ast
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            return "failed", []
        names = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                    and not node.name.startswith("_"):
                names.append(node.name)
                if isinstance(node, ast.ClassDef):
                    names += [n.name for n in node.body
                              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                              and not n.name.startswith("_")]
        return "parsed", names
    lang = SUFFIX_LANG.get(suffix)
    if not lang:
        return "unsupported", []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "failed", []
    names = []
    for pat in PUBLIC_SYMBOL_PATTERNS[lang]:
        names += pat.findall(text)
    return "parsed", names


def _contains_seq(tokens: list[str], seq: list[str]) -> bool:
    n = len(seq)
    return n > 0 and any(tokens[i:i + n] == seq for i in range(len(tokens) - n + 1))


def load_vocab(root: Path, cfg: dict) -> tuple[str | None, dict | None, str | None]:
    """返回 (相对路径, 内容, 读取错误)。路径优先取配置的 `vocab`，否则找默认位置。"""
    cands = [cfg["vocab"]] if cfg.get("vocab") else list(VOCAB_DEFAULT_PATHS)
    for rel in cands:
        p = root / rel
        if p.is_file():
            try:
                return rel, json.loads(p.read_text(encoding="utf-8")), None
            except (OSError, json.JSONDecodeError) as e:
                return rel, None, f"{type(e).__name__}: {e}"
    return None, None, None


def check_vocab(v: dict) -> list[str]:
    """词表自身的一致性问题（每条一句话）。"""
    issues = []
    if not VOCAB_SEMVER.match(str(v.get("version", ""))):
        issues.append(f"version 不是语义化版本号：{v.get('version')!r}")
    concepts = v.get("concepts") or []
    retired_ids = {str(r.get("id")) for r in (v.get("retired") or [])}
    seen_ids, label_owner, alias_owner = set(), {}, {}
    for c in concepts:
        cid = str(c.get("id") or "")
        if not cid:
            issues.append("有概念缺 id")
            continue
        if cid in seen_ids:
            issues.append(f"id 重复：{cid}")
        seen_ids.add(cid)
        if cid in retired_ids:
            issues.append(f"已退役的 id 被复用：{cid}（退役 id 永不复用）")
        if "<<" in json.dumps(c, ensure_ascii=False):
            issues.append(f"{cid}：还有没填的模板占位 <<…>>")
        if not str(c.get("definition") or "").strip():
            issues.append(f"{cid}：缺定义")
        if not c.get("not"):
            issues.append(f"{cid}：缺「不是什么」，边界没定")
        label = " ".join(split_identifier(str(c.get("label") or cid)))
        label_owner.setdefault(label, cid)
        for a in c.get("alt_labels") or []:
            key = " ".join(split_identifier(str(a)))
            if key in alias_owner and alias_owner[key] != cid:
                issues.append(f"别名 {a!r} 同时挂在 {alias_owner[key]} 和 {cid} 上")
            alias_owner.setdefault(key, cid)
    for key, cid in alias_owner.items():
        if key in label_owner and label_owner[key] != cid:
            issues.append(f"{cid} 的别名 {key!r} 撞上了 {label_owner[key]} 的正式名")
    return issues


def concept_scan(root: Path, code_files: list[tuple[Path, str, str]], cfg: dict, top: int) -> dict:
    status_count = {"parsed": 0, "failed": 0, "unsupported": 0}
    failed: list[str] = []
    symbols: list[tuple[str, str, list[str]]] = []      # (符号, 文件, 词元)
    for p, rel, suf in code_files:
        st, names = public_symbols(p, suf)
        status_count[st] += 1
        if st == "failed":
            failed.append(rel)
        symbols += [(n, rel, split_identifier(n)) for n in names]
    consistent = sum(status_count.values()) == len(code_files)

    vrel, vocab, verr = load_vocab(root, cfg)
    vocab_issues: list[str] = check_vocab(vocab) if vocab else []
    alias_hits: list[dict] = []
    retired_hits: list[dict] = []
    covered_tokens: set[str] = set()
    if vocab:
        for c in vocab.get("concepts") or []:
            cid = str(c.get("id") or "")
            label = str(c.get("label") or cid)
            covered_tokens.update(split_identifier(label))
            for a in c.get("alt_labels") or []:
                seq = split_identifier(str(a))
                covered_tokens.update(seq)
                hits = [f"{n}  ({rel})" for n, rel, toks in symbols if _contains_seq(toks, seq)]
                if hits:
                    alias_hits.append({"concept": cid, "canonical": label, "alias": a,
                                       "count": len(hits), "examples": hits[:5]})
        for r in vocab.get("retired") or []:
            seq = split_identifier(str(r.get("id") or ""))
            hits = [f"{n}  ({rel})" for n, rel, toks in symbols if _contains_seq(toks, seq)]
            if hits:
                retired_hits.append({"id": r.get("id"), "replaced_by": r.get("replaced_by"),
                                     "count": len(hits), "examples": hits[:5]})

    groups = [tuple(g) for g in BUILTIN_SYNONYMS] + [tuple(g) for g in (cfg.get("concept_synonyms") or [])]
    ignore = {str(x).lower() for x in (cfg.get("concept_ignore") or [])}
    forks, ignored_groups, covered_groups = [], [], []
    for g in groups:
        if not g:
            continue
        if g[0] in ignore:
            ignored_groups.append(g[0])  # 屏蔽是放宽：必须计数，体检时数目变多按放宽报
            continue
        if covered_tokens & set(g):
            covered_groups.append(g[0])
            continue                    # 词表已经管这个概念，交给上面的别名检查
        used = {}
        for term in g:
            hits = [f"{n}  ({rel})" for n, rel, toks in symbols if term in toks]
            if hits:
                used[term] = {"count": len(hits), "examples": hits[:3]}
        if len(used) >= 2:
            forks.append({"group": list(g), "used": used})
    forks.sort(key=lambda f: -len(f["used"]))

    return {
        "vocab_path": vrel,
        "vocab_version": (vocab or {}).get("version"),
        "vocab_read_error": verr,
        "vocab_issues": vocab_issues,
        "vocab_unapproved": [str(c.get("id")) for c in ((vocab or {}).get("concepts") or [])
                             if c.get("approved") is not True],
        "alias_in_code": alias_hits[:top],
        "retired_in_code": retired_hits[:top],
        "fork_suspects": forks[:top],
        "fork_total": len(forks),
        "groups": {"total": sum(1 for g in groups if g), "ignored": ignored_groups,
                   "covered_by_vocab": covered_groups,
                   "checked": sum(1 for g in groups if g) - len(ignored_groups) - len(covered_groups)},
        "public_symbols": len(symbols),
        "files": {"enumerated": len(code_files), **status_count, "failed_paths": failed[:top]},
        "consistent": consistent,
    }


# ---------------------------------------------------------------------------
# 草稿区边界（scratch/ 不得被正式代码引用）
#
# 草稿区里的代码不审、不测，可以随便写；代价是正式代码不能依赖它，否则屎山会顺着 import 悄悄流进来。
# 要转正就把代码搬出草稿区，搬的那个 PR 带上独立测试和负责人 —— 这样「流进来」变成一次看得见的迁移。
#
# 口径：
#   - 草稿区目录取 .agent-ready.json 的 `scratch_dirs`（相对仓库根的路径列表），缺省为 ["scratch"]。
#   - 只查草稿区**之外**的代码文件；草稿区内部互相引用随意。
#   - 先把引用解析成仓库内的规范路径，再判断是否落在草稿区里（判概念，不判字符串）：
#       Python  `import scratch.x` / `from pkg.scratch import y` / 相对导入 `from ..scratch import z`
#       JS/TS   相对路径 import / require / export-from / 动态 import()，以及首段等于草稿区目录名的裸路径
#       Go      import 路径里含草稿区目录这一段
#   - 不静默跳过：草稿区外的代码文件数 == 检查 + 解析失败 + 不支持的后缀。
# ---------------------------------------------------------------------------
SCRATCH_DEFAULT = ("scratch",)
JS_IMPORT_PATTERNS = (
    re.compile(r"""\bimport\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]"""),
    re.compile(r"""\bexport\s+[^'"]*?\s+from\s+['"]([^'"]+)['"]"""),
    re.compile(r"""\b(?:require|import)\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
)
GO_IMPORT_BLOCK = re.compile(r"^import\s*\(([^)]*)\)", re.M | re.S)
GO_IMPORT_LINE = re.compile(r"""^import\s+(?:\w+\s+)?"([^"]+)\"""", re.M)


def _norm(rel: str) -> str | None:
    """仓库根相对的规范 posix 路径；越出仓库根返回 None。"""
    n = os.path.normpath(rel).replace("\\", "/")
    if n == ".":
        return ""
    return None if n.startswith("../") or n == ".." else n


def _inside(path: str | None, zones: list[str]) -> str | None:
    if path is None:
        return None
    for z in zones:
        if path == z or path.startswith(z + "/"):
            return z
    return None


def _py_targets(tree, rel: str) -> list[tuple[int, str, str]]:
    """(行号, 原写法, 解析出的仓库相对路径前缀)。绝对导入按「模块路径即目录路径」解析。"""
    import ast
    pkg = rel.rsplit("/", 1)[0] if "/" in rel else ""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.append((node.lineno, f"import {a.name}", a.name.replace(".", "/")))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:
                parts = pkg.split("/") if pkg else []
                up = node.level - 1
                base = ".." if up > len(parts) else "/".join(parts[:len(parts) - up])
                tgt = "/".join(x for x in (base, mod.replace(".", "/")) if x)
                for a in node.names:      # from . import scratch
                    out.append((node.lineno, f"from {'.' * node.level}{mod} import {a.name}",
                                "/".join(x for x in (tgt, a.name) if x) if a.name != "*" else tgt))
            else:
                for a in node.names:
                    out.append((node.lineno, f"from {mod} import {a.name}",
                                f"{mod.replace('.', '/')}/{a.name}" if a.name != "*" else mod.replace(".", "/")))
    return out


def scratch_scan(code_files: list[tuple[Path, str, str]], cfg: dict, root: Path, top: int) -> dict:
    zones = [z for z in (_norm(str(x).strip("/")) for x in (cfg.get("scratch_dirs") or SCRATCH_DEFAULT)) if z]
    zone_names = {z.rsplit("/", 1)[-1] for z in zones}
    outside = [(p, rel, suf) for p, rel, suf in code_files if not _inside(rel, zones)]
    counts = {"checked": 0, "failed": 0, "unsupported": 0}
    failed: list[str] = []
    hits: list[dict] = []

    def hit(rel, line, spec, zone):
        hits.append({"file": rel, "line": line, "import": spec, "zone": zone})

    for p, rel, suf in outside:
        here = rel.rsplit("/", 1)[0] if "/" in rel else ""
        if suf == ".py":
            import ast
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except (OSError, SyntaxError, ValueError):
                counts["failed"] += 1
                failed.append(rel)
                continue
            counts["checked"] += 1
            for line, spec, tgt in _py_targets(tree, rel):
                z = _inside(_norm(tgt), zones)
                if z:
                    hit(rel, line, spec, z)
        elif suf in (".js", ".mjs", ".ts", ".tsx", ".vue", ".go"):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                counts["failed"] += 1
                failed.append(rel)
                continue
            counts["checked"] += 1
            if suf == ".go":
                specs = GO_IMPORT_LINE.findall(text)
                for blk in GO_IMPORT_BLOCK.findall(text):
                    specs += re.findall(r'"([^"]+)"', blk)
                for s in specs:
                    segs = s.split("/")
                    z = next((zz for zz in zones if zz.split("/")[-1] in segs), None)
                    if z:
                        hit(rel, None, f'import "{s}"', z)
                continue
            for pat in JS_IMPORT_PATTERNS:
                for m in pat.finditer(text):
                    s = m.group(1)
                    line = text.count("\n", 0, m.start()) + 1
                    if s.startswith("."):
                        z = _inside(_norm(f"{here}/{s}" if here else s), zones)
                    else:
                        first = s.lstrip("@/~").split("/")[0]
                        z = next((zz for zz in zones if zz.split("/")[-1] == first), None) \
                            if first in zone_names else None
                    if z:
                        hit(rel, line, s, z)
        else:
            counts["unsupported"] += 1

    seen, uniq = set(), []
    for h in hits:                      # 同一处可能被两条正则各命中一次
        k = (h["file"], h["line"], h["import"])
        if k not in seen:
            seen.add(k)
            uniq.append(h)
    return {
        "zones": zones,
        "applicable": len(code_files) > 0,  # 只按事实判：一个代码文件都没有才算不适用
        "zones_exist": [z for z in zones if (root / z).is_dir()],
        "inside_zone": len(code_files) - len(outside),  # 草稿区一放宽，这个数就变大
        "violations": uniq[:top],
        "violation_total": len(uniq),
        "files": {"outside_zone": len(outside), **counts, "failed_paths": failed[:top]},
        "consistent": sum(counts.values()) == len(outside),
    }


def load_config(root: Path, explicit: str | None) -> dict:
    path = Path(explicit) if explicit else (root / CONFIG_NAME)
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8")) or {}
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def collect(root: Path, top: int, skip_dirs: set[str], skip_prefixes: tuple[str, ...],
            cfg: dict | None = None) -> dict:
    all_skip = SKIP_DIR_PARTS | skip_dirs
    doc_counts: dict[str, int] = defaultdict(int)
    code_counts: dict[str, int] = defaultdict(int)
    dir_stats: dict[str, dict] = {}
    sensitive: list[dict] = []
    dup_map: dict[tuple[str, str], list[str]] = defaultdict(list)
    gitignore = read_gitignore(root)
    code_files: list[tuple[Path, str, str]] = []

    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        rel = d.relative_to(root).as_posix()
        rel = "" if rel == "." else rel
        dirnames[:] = _prune(dirnames, rel, all_skip, skip_prefixes)

        seg = rel.split("/")[0] if rel else ""
        files = size = 0
        for name in filenames:
            p = d / name
            if p.is_symlink():
                continue
            r = f"{rel}/{name}" if rel else name
            files += 1
            size += du(p)
            suf = p.suffix.lower()
            if suf in DOC_SUFFIXES:
                doc_counts[seg] += 1
            elif suf in CODE_SUFFIXES:
                code_counts[seg] += 1
                code_files.append((p, r, suf))

            # --- 敏感候选 ---
            strong = bool(SENSITIVE_STRONG.match(name))
            stem = name[: -len(suf)] if suf else name
            weak = (not strong and suf not in TEXT_SUFFIXES and bool(SENSITIVE_WEAK.match(stem)))
            if strong or weak:
                sensitive.append({"path": r, "why": "strong" if strong else "weak-keyword",
                                  "ignored": is_gitignored(r, gitignore)})

            # --- 重复内容（跳过样板小文件） ---
            try:
                if DUP_MIN_BYTES <= p.stat().st_size <= HASH_MAX_BYTES:
                    dup_map[(name, hashlib.sha1(p.read_bytes()).hexdigest())].append(r)
            except OSError:
                pass

        if seg:
            st = dir_stats.setdefault(seg, {"files": 0, "bytes": 0})
            st["files"] += files
            st["bytes"] += size
        elif files:
            dir_stats.setdefault("<root>", {"files": 0, "bytes": 0})
            dir_stats["<root>"]["files"] += files
            dir_stats["<root>"]["bytes"] += size

    # 只报「跨目录组」的重复：目录组 = 前 2 段路径（不足则取 1 段）
    def group_of(rel: str) -> str:
        segs = rel.split("/")[:-1]
        return "/".join(segs[:2]) if len(segs) >= 2 else (segs[0] if segs else "<root>")

    dup_groups = []
    for (name, _h), paths in dup_map.items():
        if len(paths) < 2:
            continue
        if len({group_of(p) for p in paths}) < 2:
            continue                      # 同一目录组内的重复 = 正常（如各 UI 包的样板）
        dup_groups.append({"name": name, "groups": len({group_of(p) for p in paths}),
                           "paths": sorted(paths)})
    dup_groups.sort(key=lambda g: (-g["groups"], -len(g["paths"]), g["name"]))

    agent_entry = find_one_level(root, AGENT_ENTRY_CANDIDATES, 2, all_skip, skip_prefixes)
    human_entry = find_one_level(root, HUMAN_ENTRY_CANDIDATES, 2, all_skip, skip_prefixes)
    gov = find_one_level(root, GOV_CANDIDATES, 2, all_skip, skip_prefixes)

    def any_exists(cands) -> str | None:
        for c in cands:
            if (root / c).exists():
                return c
        return None

    misc = {
        "gitignore": (root / ".gitignore").is_file(),
        "verify_refs_config": (root / CONFIG_NAME).is_file(),
        "memory": any_exists(MEMORY_CANDIDATES),
        "rules_dir": any_exists(RULE_DIR_CANDIDATES),
    }

    # --- 平台画像：只陈述「探测到什么约定」，不给建议 ---
    known: dict[str, list[str]] = {}
    for grp in (agent_entry, human_entry, gov):
        for k, v in grp.items():
            if v:
                known.setdefault(k, v)
    for k in MEMORY_CANDIDATES + RULE_DIR_CANDIDATES:
        if (root / k).exists():
            known.setdefault(k, [k])

    platform: dict[str, dict] = {}
    for fam, spec in PLATFORM_SIGNATURES.items():
        hits = [s for s in spec["signatures"] if (root / s).exists() or known.get(s)]
        if hits:
            platform[fam] = {"desc": spec["desc"], "confidence": spec["confidence"], "hit": hits}

    # 多方向容器可能在根，也可能在一层子目录下（如 <<方向容器>>/teams/）
    handoff = []
    containers = [root / c for c in HANDOFF_CONTAINERS if (root / c).is_dir()]
    for sub in sorted(x for x in root.iterdir() if x.is_dir() and not x.name.startswith(".")):
        containers += [sub / c for c in HANDOFF_CONTAINERS if (sub / c).is_dir()]
    for c in containers:
        for sub in sorted(x for x in c.iterdir() if x.is_dir() and not x.name.startswith(".")):
            handoff.append({
                "dir": sub.relative_to(root).as_posix(),
                "state": (sub / "STATE.md").is_file() or (sub / "state.md").is_file(),
                "readme": (sub / "README.md").is_file(),
            })

    big = [{"dir": k, "files": v["files"], "mb": round(v["bytes"] / 1048576, 1)}
           for k, v in dir_stats.items() if v["bytes"] / 1048576 >= BIG_DIR_MB]
    big.sort(key=lambda x: -x["mb"])

    concepts = concept_scan(root, code_files, cfg or {}, top)
    scratch = scratch_scan(code_files, cfg or {}, root, top)

    signals = {
        "no_git": 0 if run_git(root)["is_repo"] else 1,
        "no_gitignore": 0 if misc["gitignore"] else 1,
        "no_agent_entry_doc": 0 if any(agent_entry.values()) else 1,
        "no_governance_doc": 0 if any(gov.values()) else 1,
        "no_memory": 0 if misc["memory"] else 1,
        "no_rules_dir": 0 if misc["rules_dir"] else 1,
        "sensitive_unguarded": sum(1 for s in sensitive if not s["ignored"]),
        "duplicate_groups": len(dup_groups),
        "handoff_missing_state": sum(1 for h in handoff if not h["state"]),
        "no_vocab": 0 if concepts["vocab_path"] else 1,
        "vocab_issues": len(concepts["vocab_issues"]) + (1 if concepts["vocab_read_error"] else 0),
        "vocab_alias_in_code": sum(h["count"] for h in concepts["alias_in_code"]),
        "vocab_retired_in_code": sum(h["count"] for h in concepts["retired_in_code"]),
        "concept_fork_suspects": concepts["fork_total"],
        "code_parse_failed": concepts["files"]["failed"],
        "scratch_imports": scratch["violation_total"],
        # 以下两项不是问题数，是「判据有多宽」：体检时变大按放宽报，需要主人批
        "concept_groups_ignored": len(concepts["groups"]["ignored"]),
        "scratch_inside_zone": scratch["inside_zone"],
    }

    return {
        "root": str(root),
        "git": run_git(root),
        "gitignore_patterns": len(gitignore),
        "skip_from_config": {"skip_dirs": sorted(skip_dirs), "skip_prefixes": list(skip_prefixes)},
        "dirs": [{"dir": k, "files": v["files"], "mb": round(v["bytes"] / 1048576, 1)}
                 for k, v in sorted(dir_stats.items(), key=lambda kv: -kv[1]["bytes"])][:top],
        "size_note": "体积仅统计源码/文档（已排除 " + ", ".join(sorted(SKIP_DIR_PARTS)) + " 及配置的 skip）",
        "big_dirs": big,
        "sensitive": sensitive[:top],
        "sensitive_total": len(sensitive),
        "agent_entry": agent_entry,
        "human_entry": human_entry,
        "governance": gov,
        "platform": platform,
        "nested_agents_md": len(known.get("AGENTS.md", [])) + len(known.get("AGENT.md", [])),
        "misc": misc,
        "docs": {"total": sum(doc_counts.values()),
                 "by_top_dir": dict(sorted(doc_counts.items(), key=lambda kv: -kv[1])[:top])},
        "code": {"total": sum(code_counts.values()),
                 "by_top_dir": dict(sorted(code_counts.items(), key=lambda kv: -kv[1])[:top])},
        "duplicate_suspects": dup_groups[:top],
        "duplicate_total": len(dup_groups),
        "handoff": handoff,
        "concepts": concepts,
        "scratch": scratch,
        "signals": signals,
    }


def render(a: dict) -> None:
    g = a["git"]
    print(f"# Workspace audit: {a['root']}\n")

    print("## 0. 平台画像（探测到的现存约定 —— 只陈述事实）")
    if a["platform"]:
        for fam, d in a["platform"].items():
            print(f"  ✅ {fam:<12} [{d['confidence']}] {d['desc']}")
            print(f"       签名命中: {', '.join(d['hit'])}")
        if a.get("nested_agents_md", 0) > 1:
            print(f"  ℹ️  检测到 {a['nested_agents_md']} 份 AGENTS.md/AGENT.md"
                  f"（嵌套生效：最近者优先，子目录覆盖父目录）")
    else:
        print("  （未探测到任何已知平台约定）")
    print("  → 「该新建什么 / 怎么适配」的决策表见技能 references/platform-mapping.md §5")

    print("\n## 1. 仓库与版本控制")
    if g["is_repo"]:
        print(f"  git          : yes  branch={g['branch']}  dirty={g['dirty_files']}  tracked={g['tracked_files']}")
    else:
        print("  git          : ❌ 不是 git 仓库 → 无回滚 / 无 diff / 多 agent 覆盖无法归因（最高优先级）")
    print(f"  .gitignore   : {'yes' if a['misc']['gitignore'] else '❌ no'}  ({a['gitignore_patterns']} 条规则)")
    print(f"  自检配置     : {'yes' if a['misc']['verify_refs_config'] else 'no'} ({CONFIG_NAME})")

    print("\n## 2. 目录概览（顶层）")
    print(f"  {a['size_note']}")
    print(f"  {'dir':<26}{'files':>8}{'MB':>9}")
    for d in a["dirs"]:
        print(f"  {d['dir']:<26}{d['files']:>8}{d['mb']:>9}")
    if a["big_dirs"]:
        print(f"\n  ⚠ 源码体积 >= {BIG_DIR_MB} MB（考虑是否属「外来只读内容」，应排除出 agent 视野）：")
        for d in a["big_dirs"]:
            print(f"    - {d['dir']}/  {d['mb']} MB / {d['files']} files")

    print(f"\n## 3. 敏感文件候选（{a['sensitive_total']}）")
    if not a["sensitive"]:
        print("  （无）")
    for s in a["sensitive"]:
        mark = "已忽略" if s["ignored"] else "❌ 未忽略"
        tag = "强" if s["why"] == "strong" else "弱(关键词)"
        print(f"  [{mark}][{tag}] {s['path']}")

    print("\n## 4. 入口与治理文档（平台中立：任一候选存在即算「有」）")
    hit = [(k, v) for k, v in a["agent_entry"].items() if v]
    if hit:
        for k, v in hit:
            print(f"  ✅ {k:<36}→ {', '.join(v[:3])}")
    else:
        print("  ❌ 未找到任何 agent 入口文档（常见名：AGENTS.md / CLAUDE.md / GEMINI.md / "
              "CODEBUDDY.md / .github/copilot-instructions.md）")
    for k, v in a["human_entry"].items():
        print(f"  {'✅' if v else '❌'} {k:<36}{('→ ' + ', '.join(v[:3])) if v else ''}")
    for k, v in a["governance"].items():
        print(f"  {'✅' if v else '❌'} {k:<36}{('→ ' + ', '.join(v[:3])) if v else ''}")
    print(f"  {'✅' if a['misc']['memory'] else '❌'} {'记忆文件（跨会话）':<32}"
          f"{('→ ' + a['misc']['memory']) if a['misc']['memory'] else ''}")
    print(f"  {'✅' if a['misc']['rules_dir'] else '❌'} {'规则目录（始终生效）':<31}"
          f"{('→ ' + a['misc']['rules_dir']) if a['misc']['rules_dir'] else ''}")

    print(f"\n## 5. 文档库存：{a['docs']['total']} 个文档 / {a['code']['total']} 个代码文件")
    for k, v in a["docs"]["by_top_dir"].items():
        print(f"  {(k or '<root>'):<26}{v:>6}")

    print(f"\n## 6. 重复内容嫌疑（{a['duplicate_total']} 组：同名 + 同内容 + 跨目录组）")
    print("  ← 同一份内容出现在不同位置 = 单一事实源被破坏的强信号（agent 会读到互相矛盾的副本）")
    if not a["duplicate_suspects"]:
        print("  （无）")
    for gp in a["duplicate_suspects"]:
        print(f"  · {gp['name']}  ×{len(gp['paths'])} 跨 {gp['groups']} 个目录组")
        for p in gp["paths"][:6]:
            print(f"      {p}")
        if len(gp["paths"]) > 6:
            print(f"      … 另有 {len(gp['paths']) - 6} 处")

    if a["handoff"]:
        print("\n## 7. 交接缺口（多方向容器）")
        for h in a["handoff"]:
            print(f"  {h['dir']:<28} STATE.md={'✅' if h['state'] else '❌'}  README.md={'✅' if h['readme'] else '❌'}")

    print("\n## 8. 信号计数（供打分，非结论）")
    for k, v in a["signals"].items():
        flag = "✅" if v == 0 else "❌"
        print(f"  {flag} {k:<24}{v}")

    c = a["concepts"]
    print("\n## 9. 概念碎片（同一个东西有了好几个名字）")
    f = c["files"]
    print(f"  代码文件 {f['enumerated']} = 解析 {f['parsed']} + 失败 {f['failed']} + 不支持的后缀 {f['unsupported']}"
          f"  {'✅' if c['consistent'] else '❌ 计数不自洽'}；公共符号 {c['public_symbols']} 个")
    for fp in f["failed_paths"]:
        print(f"    ❌ 解析失败：{fp}")
    if c["vocab_read_error"]:
        print(f"  ❌ 词表 {c['vocab_path']} 读不出来：{c['vocab_read_error']}")
    elif c["vocab_path"]:
        print(f"  词表：{c['vocab_path']}  version={c['vocab_version']}")
        if c["vocab_unapproved"]:
            print(f"    ℹ️  还没批准的概念 {len(c['vocab_unapproved'])} 个：{', '.join(c['vocab_unapproved'][:10])}")
        for i in c["vocab_issues"]:
            print(f"    ❌ {i}")
        for h in c["alias_in_code"]:
            print(f"    ❌ {h['concept']}：代码用了别名 {h['alias']!r} 而不是正式名 {h['canonical']!r}（{h['count']} 处）")
            for e in h["examples"]:
                print(f"         {e}")
        for h in c["retired_in_code"]:
            print(f"    ❌ 已退役的 {h['id']!r} 还在用（{h['count']} 处），应改为 {h['replaced_by']!r}")
            for e in h["examples"]:
                print(f"         {e}")
    else:
        print("  ❌ 开工前提缺失：没有词表（vocab.json）→ 概念的边界没人定，每个 agent、每次会话都可能起个新名字")
        print("     先做词表访谈（skill 的 references/vocab-interview.md），首批约五个，优先从下面的近义分叉嫌疑里挑")
    gr = c["groups"]
    print(f"  同义词组 {gr['total']} = 检查 {gr['checked']} + 词表已管 {len(gr['covered_by_vocab'])}"
          f" + 配置屏蔽 {len(gr['ignored'])}" + (f"（{', '.join(gr['ignored'])}）" if gr["ignored"] else ""))
    if c["fork_suspects"]:
        print(f"  近义分叉嫌疑（词表没管到的部分，{c['fork_total']} 组，仅供参考）：")
        for fk in c["fork_suspects"]:
            used = "、".join(f"{t}×{u['count']}" for t, u in fk["used"].items())
            print(f"    · {used}")
            for t, u in fk["used"].items():
                print(f"         {t}: {u['examples'][0]}")
    else:
        print("  近义分叉嫌疑：（无）")

    sc = a["scratch"]
    print("\n## 10. 草稿区边界（正式代码不得引用草稿区）")
    if not sc["applicable"]:
        print("  不适用：仓库里没有代码文件（按事实判断，不接受声明）")
    else:
        exist = sc["zones_exist"]
        print(f"  草稿区：{', '.join(z + '/' for z in sc['zones'])}"
              f"  {'（存在）' if exist else '（仓库里还没有这个目录）'}")
        f = sc["files"]
        print(f"  草稿区内的代码文件 {sc['inside_zone']}（不受本节检查；这个数变大说明草稿区被放宽了）")
        print(f"  草稿区外的代码文件 {f['outside_zone']} = 检查 {f['checked']} + 失败 {f['failed']} + 不支持的后缀 {f['unsupported']}"
              f"  {'✅' if sc['consistent'] else '❌ 计数不自洽'}")
        for fp in f["failed_paths"]:
            print(f"    ❌ 解析失败：{fp}")
        if sc["violations"]:
            print(f"  ❌ 正式代码引用了草稿区（{sc['violation_total']} 处）→ 要用就先把代码搬出草稿区，PR 里带上测试和负责人")
            for v in sc["violations"]:
                loc = f"{v['file']}:{v['line']}" if v["line"] else v["file"]
                print(f"    {loc}  {v['import']}")
        else:
            print("  ✅ 没有正式代码引用草稿区")


def main() -> int:
    ap = argparse.ArgumentParser(description="工作区 agent 友好度事实采集（只读）")
    ap.add_argument("--root", default=".")
    ap.add_argument("--config", default=None, help=f"默认 <root>/{CONFIG_NAME}")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--skip", action="append", default=[], help="额外跳过目录名（可重复）")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"! 不是目录：{root}")
        return 2

    skip_dirs, skip_prefixes = load_skip(root, args.config)
    skip_dirs |= set(args.skip)
    data = collect(root, args.top, skip_dirs, skip_prefixes, load_config(root, args.config))

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        render(data)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    raise SystemExit(main())
