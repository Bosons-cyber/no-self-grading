#!/usr/bin/env python3
"""verify-refs.py —— 文档路径引用一致性自检（只读，不修改任何文件）。

为什么需要它
    目录迁移 / 重命名后，**文档里的路径引用往往没跟着改**，结果是「新 agent 照着文档做会失败」
    （例如 RUNBOOK 里 `cd <已删除的旧目录>`）。人眼审计必漏，必须变成**可回归的检查**。

用法（**先确定「根」**）
    **根 = 配置文件 `.agent-ready.json` 所在的目录**（通常就是仓库根）。从那里跑最省事。
    python verify-refs.py                          # 用 <root>/.agent-ready.json（若存在）
    python verify-refs.py --root /path/to/repo
    python verify-refs.py --write-default-config   # 生成起步配置后退出
    python verify-refs.py --include-code           # 同时扫 .py/.json/.yml 等
    python verify-refs.py --no-legacy              # 跳过「迁移残留模式」检查
    python verify-refs.py --json                   # 机器可读输出
    python verify-refs.py --verbose                # 额外打印解析成功的引用
    python verify-refs.py --expect-sha <12位>       # 本脚本哈希与基准不符 ⇒ 拒答（退出码 2）
    python verify-refs.py --base <提交号>           # external_roots 还要和基线提交的顶层目录比（体检必加）

覆盖范围（**防「假绿」**）
    ⚠️ 本脚本的解析基准（`scan.dirs` / 跳过前缀 / 文件名索引）**全都相对「根」**。
    从别的目录跑（尤其是仓库的**子目录**）时，它可能**静默退化成「只扫一点点」**，然后照样打印 `ERROR 0`
    —— **不可信的绿比红更危险**（红会被查，绿会被信）。故**默认拒绝**下这种结论：
      · 根上**没有**配置文件，且（**上级目录里**有配置文件，或扫描到的文件数 < 5）
        ⇒ 判定「**扫描范围不可信**」，**退出码 2**，并打印修法；
      · 确知范围没问题时用 `--allow-untrusted-range` 显式放行（会打印醒目警告）。

退出码（只是提示；闸门**只认哨兵行**，见下）
    0 = 无 ERROR / WARN（可能仍有 INFO 提示）
    1 = 存在 ERROR
    3 = 无 ERROR、但有 WARN ⇒ **需人工复核**（agent 这边做完了，剩下这几条归人看）
    2 = **拒绝给结论**：扫描范围不可信（假绿风险）/ `--expect-sha` 不符 / 配置非法（含旧字段 `project_roots`、
        `external_roots` 写了本仓库真实存在的目录）/ 敏感词表非法 —— **这不等于「检查通过」**
    ⚠️ 某条命中归 ERROR 还是 WARN，**只由本脚本的规则和配置里的 `external_roots` 决定**，agent 不能逐条改判；
       改 `external_roots` 本身就是一次判据变化（体检 D10 会逐项列出）。

哨兵行（旧字段顺序不变，新字段只在后面追加）
    ###VERIFY stamp=… errors=<n> warns=<n> infos=<n> exempt_lines=<n> exempt_ranges=<n>
              legacy_allow_files=<n> ignore_hits=<n> skip_rules=<n> dead_rules=<n> unread=<n> sha=<12位>
              deny_hits=<n|-> roots_base=<12位|->
    · roots_base     `--base` 给的基线提交号前 12 位；`-` = 这回**没和基线比**，external_roots 只挡了
                     磁盘上现有的目录，「先删目录再登记」挡不住，要靠体检 D10 逐项比对兜底
    · stamp          取自环境变量 VERIFY_RUN_STAMP（跑器传入本次戳并断言相等，防读到旧产物；未设时为 -）
    · exempt_lines   被 refs:skip-line / skip-start…skip-end 跳过的行数（豁免是**放松通道**，必须看得见）
    · exempt_ranges  skip-start 区间个数；**未闭合的 skip-start 记 ERROR**（否则一行标记就能静默跳过整个文件余下部分）
    · legacy_allow_files  带 refs:allow-legacy 的文件数
    · ignore_hits    被配置 ignore_refs 吞掉的引用条数（--json 的 exemptions.ignore_ref_hits 按规则给出
                     命中数和每处 文件:行号；基线按规则逐条记，某条涨了就是漂移 —— 防「规则太宽、一直有命中」）
    · skip_rules / dead_rules  配置里 skip_prefixes + ignore_refs 的条数 / 其中**一次都没命中**的条数（死规则记 WARN）
    · unread         落在扫描面内、却读不出来的文件数（读不出来记 ERROR，**不再静默跳过**）
    · deny_hits      `--deny-terms <文件>` 的命中处数；没给词表时为 `-`（= 这一项没查，**不是 0**）。
                     词表一行一个词，`#` 开头为注释，不区分大小写按子串匹配；扫 <root> 下**所有文本文件**
                     （不限后缀、不吃任何豁免与 skip，只排除 SKIP_DIR_PARTS）。输出只给 文件:行号 和词的序号，
                     **不打印词本身**；词表必须放在 <root> 之外，放在里面直接拒答（退出码 2）——
                     词表进了仓库，它自己就是泄露。命中记 ERROR。
    · sha            本脚本文件内容的 sha256 前 12 位。体检 / 闸门应拿它去比**远端主分支**上那一版，
                     而不是本机那份 —— 本机那份可能已被改过。
    ⚠️ 脚本自报的 sha 和 `--expect-sha` 都是**被检对象自己说的话**：被改过的脚本可以照抄旧 sha、删掉这段校验。
       **权威比对必须在脚本外面做**：调用方（跑闸门的程序或用户本人）自己算
       `sha256sum tools/verify-refs.py`，去比远端 main 上那一版。`--expect-sha` 只防「无意落后」，不防「有意篡改」；
       要求恰好 12 位十六进制，不接受前缀或空值。
    自洽断言：读出数 + unread == 扫描数，不成立就拒答（退出码 2）。
    这些计数**只负责让放松看得见**；新增豁免是否被允许，由仓库外的审核（CODEOWNERS / 主分支保护）决定。

三个级别
    ERROR  引用**指向本仓库结构**（首段是真实顶层目录，或绝对路径）却解析不到 → 必须修
    WARN   解析不到但不像本仓库路径（外部简写 / 裸文件名未匹配）→ 建议核对
    INFO   命中 legacy_patterns（旧目录名残留）→ 即使能解析也建议更新
           （默认不检查；需在配置里显式给出本仓库的「旧名」才有意义）

豁免标记（写在被扫文件里，逐文件生效；**只认写在注释里或独占一行的**，见 SKIP_START 附近的说明）
    refs:skip-start … refs:skip-end   跳过区间内所有检查（历史迁移表、模型原文引用等）
    refs:skip-line                    跳过该行（「目标路径」等尚不存在的路径）
    refs:allow-legacy                 跳过本文件的 INFO 级检查

配置 .agent-ready.json（放仓库根；全部字段可选）
    {
      "scan": {
        "dirs": ["docs", "src"],          // 只扫这些子树；省略 = 扫全仓库
        "files": ["README.md"],           // 额外单文件；省略 = 无
        "suffixes": [".md", ".txt"]       // 覆盖默认后缀集合
      },
      "skip_dirs": ["vendor"],            // 追加到内置跳过名单（node_modules/.git/...）
      "skip_prefixes": ["generated/"],    // 根相对前缀，整棵子树跳过（生成物 / 归档 / 冻结快照）
      "resolve_bases": ["docs", "vendor/lib"],  // 额外解析基准（默认仅 仓库根 + 引用文件所在目录）
      "external_roots": ["other-repo"],   // 解析不到时只报 WARN 的「外部」首段目录名；**其余一律 ERROR**
                                          //   · 漏写 / 写错 / 删条目都只会变严；
                                          //   · 写了本仓库的顶层目录 ⇒ 拒答（退出码 2）——
                                          //     那等于把本仓库的坏引用整批降成 WARN；
                                          //     「本仓库的」= 磁盘上现有的 ∪ `--base` 基线提交里有过的。
                                          //     **只看磁盘挡不住「先删目录、再登记」**，体检必须带
                                          //     `--base <git ls-remote 现取的受保护 main 提交号>`；
                                          //     没带时哨兵行 `roots_base=-`，这条只靠体检 D10 兜底。
                                          //   · 旧字段 project_roots（方向相反：列得越窄越松）已废，出现即拒答。
      "legacy_patterns": ["old-name-2024"],     // 旧目录名（INFO）
      "ignore_refs": ["docs/adr-007.md"]  // 故意不存在的路径（虚构示例、攻击载荷产物等）
    }

设计约定
    · 零第三方依赖（stdlib）；Windows 友好（stdout 强制 UTF-8）。
    · **名字索引与扫描范围解耦**：裸文件名（`xx.sql` / `yy.js` 这类）校验用的文件名集合 =
      **扫描范围**（`scan_dirs` / `scan_files`）内的文件名，**含被 `skip_dirs` / `skip_prefixes` 跳过的子树**
      （`out/`、`<<外部只读资料>>/`、归档 / 冻结快照），但**不含** `<<本机私有目录>>/` 这类「不在扫描面、也**不随仓库分发**」的目录
      —— 否则本机有、别人 clone 没有 ⇒ **假绿**。即：被跳过的目录**只跳过「扫它内部引用」**，不跳过「**别人引用它**」。
    · 名字索引模式仍排除内置 `SKIP_DIR_PARTS` 与点目录（`node_modules` / `.git` / `.cache` …）。
    · **严格默认**：解析基准只有「仓库根」与「引用文件所在目录」，放宽必须写进 resolve_bases，
      否则「什么都能解析」会掩盖真问题；跳过目录一律按**根相对前缀**匹配。
    · 通配符模式用**后置校验**（GLOB_AFTER）剔除，不用正则 lookahead —— lookahead 会迫使正则
      回溯成更短匹配（`docs/a/*.md` 截成 `docs/a`），把通配符误判为路径。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

CONFIG_NAME = ".agent-ready.json"

# 「扫描范围不可信」判定的最小文件数：没有配置文件时，扫描范围是靠推断的，
# 扫到的文件数低于此值基本可以确定「根不对」（典型症状：只扫到 1 个文件却报 ERROR 0）。
MIN_TRUSTED_FILES = 5

DEFAULT_SUFFIXES = (".md", ".txt", ".mjs", ".ps1")
CODE_SUFFIXES = (".py", ".json", ".sql", ".yml", ".yaml", ".ts", ".js", ".vue")

# 任何项目都无意义的目录（不可扫描）
SKIP_DIR_PARTS = {
    "__pycache__", "node_modules", ".git", ".svn", ".hg", ".venv", "venv",
    ".idea", ".vscode", ".mypy_cache", ".pytest_cache", "dist", "build", "target",
}

# 匹配片段之后若紧跟这些字符，说明是通配 / 模板 / 管道 / 区间写法，不是真路径
# （`–` `—` `~` 覆盖 `S01–S09`、`R1–R4` 这类区间写法）
GLOB_AFTER = set("*{}<>|%–—~")
BAD_CHARS = set('*{}<>|=%"\'`$^[]!?,;')
EXT_TAIL_RE = re.compile(r"\.[A-Za-z0-9]{1,6}$")
URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")

# 含 `/` 的候选；末段是否像「文件名」由 is_candidate() 判断
PATH_RE = re.compile(
    r"""
    (?<![A-Za-z0-9_./\\-])
    (
      (?:[A-Za-z]:[\\/])?
      (?:\.{1,2}[\\/])*
      (?:[A-Za-z0-9_][A-Za-z0-9_.\-]*[\\/])+
      [A-Za-z0-9_][A-Za-z0-9_.\-]*
      [\\/]?
    )
    (?::\d+(?:-\d+)?)?
    """,
    re.VERBOSE,
)

BARE_RE = re.compile(
    r"(?<![\w./\\-])"
    r"([A-Za-z0-9_][A-Za-z0-9_.\-]*"
    r"\.(?:md|txt|py|json|jsonl|xlsx|ps1|mjs|docx|sql|csv|zip|ya?ml|ts|js|vue|java|go|rs))"
    r"(?![\w/\\-])"
)

SKIP_START = "refs:skip-start"
SKIP_END = "refs:skip-end"
SKIP_LINE = "refs:skip-line"
ALLOW_LEGACY = "refs:allow-legacy"
# 豁免标记**只认写在注释里的**，正文里「提到」它不算（旧实现用子串匹配：文档里写一句
#   `refs:skip-start/end` 或「refs:allow-legacy」，就会静默跳过该文件余下内容 / 关掉整份文件的残留检查）。
#   认的写法只有三种，其余一律当作「提到」：
#     ① 写在 HTML 注释里：`<!-- refs:skip-line -->`（Markdown 推荐写法，渲染后不可见）；
#     ② 写在行注释后面：`# refs:skip-line`、`// refs:skip-line`（.ps1 / .mjs / .py 等）；
#     ③ 独占一行（去掉首尾空白后整行就是这个记号）。
#   标记本身仍须是完整记号：后面不能紧跟 `/`、字母数字或 `-`。
_MARK_TAIL = r"(?![\w/\-])"
_HTML_COMMENT_RE = re.compile(r"<!--(.*?)-->")
_LINE_COMMENT_RE = re.compile(r"(?:^|\s)(?:#|//)\s*(.*)$")


class _Marker:
    def __init__(self, tok: str):
        self.tok = tok
        self.re = re.compile(r"(?<![\w`])" + re.escape(tok) + _MARK_TAIL)

    def search(self, line: str) -> bool:
        if line.strip() == self.tok:
            return True
        for m in _HTML_COMMENT_RE.finditer(line):
            if self.re.search(m.group(1)):
                return True
        m = _LINE_COMMENT_RE.search(line)
        return bool(m and self.re.match(m.group(1).strip()))


SKIP_START_RE = _Marker(SKIP_START)
SKIP_END_RE = _Marker(SKIP_END)
SKIP_LINE_RE = _Marker(SKIP_LINE)
ALLOW_LEGACY_RE = _Marker(ALLOW_LEGACY)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
class Config:
    def __init__(self, root: Path, data: dict | None = None):
        d = data or {}
        scan = d.get("scan") or {}
        self.root = root
        self.scan_dirs: tuple[str, ...] = tuple(scan.get("dirs") or ())
        self.scan_files: tuple[str, ...] = tuple(scan.get("files") or ())
        self.suffixes: set[str] = set(scan.get("suffixes") or DEFAULT_SUFFIXES)
        self.skip_dirs: set[str] = SKIP_DIR_PARTS | set(d.get("skip_dirs") or ())
        self.skip_prefixes: tuple[str, ...] = tuple(d.get("skip_prefixes") or ())
        self.resolve_bases: tuple[str, ...] = tuple(d.get("resolve_bases") or ())
        self.legacy_patterns: tuple[str, ...] = tuple(d.get("legacy_patterns") or ())
        self.ignore_refs: set[str] = set(d.get("ignore_refs") or ())
        # 真实顶层目录：只用来判断「像不像路径」，**不可配置**（配置能改的东西就能被改窄）。
        self.top_dirs: set[str] = {p.name for p in root.iterdir() if p.is_dir()} if root.is_dir() else set()
        self.external_roots: set[str] = {str(x).strip("/") for x in (d.get("external_roots") or ())}
        self.legacy_project_roots = "project_roots" in d


def base_top_dirs(root: Path, rev: str) -> tuple[set[str] | None, str]:
    """基线提交里、与 root 对应的那一层的顶层目录名。取不到就返回 (None, 原因)，调用方拒答。"""
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", rev):
        return None, f"--base 必须是 7–40 位十六进制提交号（收到：{rev!r}），不接受分支名（分支能被挪）"
    def git(*a: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True)
    try:
        pre = git("rev-parse", "--show-prefix")
    except OSError as e:
        return None, f"调不起 git：{e}"
    if pre.returncode != 0:
        return None, "root 不在 git 仓库里，没法和基线比"
    prefix = pre.stdout.strip().rstrip("/")
    obj = f"{rev}:{prefix}" if prefix else f"{rev}:"
    ls = git("ls-tree", "--full-tree", "-d", "--name-only", obj)
    if ls.returncode != 0:
        return None, (f"本地取不到基线 {rev}" + (f" 下的 {prefix}/" if prefix else "")
                      + "（先 git fetch 远端受保护 main；或该目录在基线里还不存在）")
    return {ln for ln in ls.stdout.splitlines() if ln}, ""


def config_problems(cfg: Config, base_dirs: set[str] | None = None) -> list[str]:
    """配置里会让判定「悄悄变松」的写法 ⇒ 拒答，不降级运行。"""
    probs = []
    if cfg.legacy_project_roots:
        probs.append("配置里有旧字段 `project_roots`（列得越窄越松，已废）。删掉它；"
                     "确有外部前缀要只报 WARN 的，改写进 `external_roots`。")
    ours = cfg.top_dirs | (base_dirs or set())
    real = sorted(r for r in cfg.external_roots if r in ours)
    if real:
        probs.append(f"`external_roots` 里写了本仓库（磁盘上现有或基线里有过）的目录：{real} —— "
                     "这会把这些目录下的坏引用整批降成 WARN。外部前缀不应该是本仓库目录；"
                     "目录删了留下的坏引用要修，不要登记。")
    return probs


def script_sha() -> str:
    """本脚本内容的 sha256 前 12 位（用于和远端主分支上的基准版本比对）。"""
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
    except OSError:
        return "unknown"


def load_config(root: Path, explicit: str | None) -> tuple[Config, str | None]:
    path = Path(explicit) if explicit else (root / CONFIG_NAME)
    if path.is_file():
        try:
            return Config(root, json.loads(path.read_text(encoding="utf-8"))), str(path)
        except (OSError, json.JSONDecodeError) as e:
            print(f"! 配置读取失败（将用默认值）：{path}: {e}")
    return Config(root), None


def default_config_dict(root: Path) -> dict:
    """生成起步配置：把可疑的「大目录 / 生成物 / 外来内容」预先填进 skip_prefixes。"""
    skip = []
    for p in sorted(root.iterdir()) if root.is_dir() else []:
        if not p.is_dir() or p.name in SKIP_DIR_PARTS or p.name.startswith("."):
            continue
        if p.name in {"archive", "vendor", "out", "dist", "node_modules", "generated"}:
            skip.append(f"{p.name}/")
    return {
        "_comment": "no-self-grading / verify-refs.py 配置。省略字段即用默认值。",
        "scan": {"dirs": [], "files": [], "suffixes": list(DEFAULT_SUFFIXES)},
        "skip_dirs": [],
        "skip_prefixes": skip,
        "resolve_bases": [],
        "external_roots": [],
        "legacy_patterns": [],
        "ignore_refs": [],
    }


# ---------------------------------------------------------------------------
# 提取与判定
# ---------------------------------------------------------------------------
def normalize(tok: str) -> str:
    return tok.replace("\\", "/").rstrip("/.")


def first_segment(tok: str) -> str:
    for part in tok.split("/"):
        if part and part != "." and part != "..":
            return part
    return ""


def is_candidate(tok: str, cfg: Config) -> bool:
    """只有「像路径」的 token 才进入校验，压掉 `A/B`、`40/46/50` 这类文本误报。"""
    if not tok or len(tok) > 300:
        return False
    if URL_RE.match(tok) or any(c in BAD_CHARS for c in tok) or "//" in tok:
        return False
    if "/" not in tok:
        return False
    if tok.endswith("/"):                              # 显式目录
        return True
    if EXT_TAIL_RE.search(tok.split("/")[-1]):         # 末段是「名字.扩展名」
        return True
    seg = first_segment(tok)                           # 以真实顶层目录 / 已登记的外部前缀开头
    return seg in cfg.top_dirs or seg in cfg.external_roots


def resolve(tok: str, file_dir: Path, cfg: Config):
    raw = tok.replace("\\", "/")
    p = Path(raw)
    if p.is_absolute():
        try:
            return p if p.exists() else None
        except OSError:
            return None
    bases = [file_dir, cfg.root] + [cfg.root / b for b in cfg.resolve_bases]
    for base in bases:
        try:
            cand = (base / raw).resolve()
        except (OSError, ValueError):
            continue
        if cand.exists():
            return cand
    return None


# ---------------------------------------------------------------------------
# 遍历
# ---------------------------------------------------------------------------
SKIP_HITS: dict[str, int] = {}   # skip_prefixes 每条规则命中的目录数（只在 honor_skips 模式下累计）


def _prune(dirnames, rel: str, cfg: Config, honor_skips: bool = True) -> list[str]:
    """honor_skips=False 用于「名字索引」模式：**不**吃配置级 skip（skip_dirs / skip_prefixes），
    这样被跳过的产物 / 归档目录里的**文件名仍能被索引**（跳过的是「扫它内部引用」，不该让「别人引用它」变成 WARN）。
    ⚠️ 两种模式都仍排除内置 SKIP_DIR_PARTS（node_modules / .git / … ⇒ 性能与噪声）。"""
    kept = []
    for x in sorted(dirnames):
        if x in SKIP_DIR_PARTS:
            continue
        if honor_skips:
            if x in cfg.skip_dirs:
                continue
            child = f"{rel}/{x}/" if rel else f"{x}/"
            hit = next((p for p in cfg.skip_prefixes if child.startswith(p)), None)
            if hit is not None:
                SKIP_HITS[hit] = SKIP_HITS.get(hit, 0) + 1
                continue
        elif x.startswith("."):
            continue          # 名字索引模式：点目录（.cache 等运行时态）不入名字
        kept.append(x)
    return kept


def walk(base: Path, prefix: str, cfg: Config, honor_skips: bool = True):
    """在 base 下遍历，产出 (Path, **根相对**路径)。prefix = base 的根相对路径。"""
    for dirpath, dirnames, filenames in os.walk(base):
        d = Path(dirpath)
        rel_in = d.relative_to(base).as_posix()
        rel_in = "" if rel_in == "." else rel_in
        # prefix 为空（未配 scan.dirs、从根遍历）时旧写法会拼出 "/assets/…"，
        #   导致嵌套的 skip_prefixes（如 "assets/templates/"）永远匹配不上、报告里的路径也带前导 "/"。
        rel = (f"{prefix}/{rel_in}" if prefix else rel_in) if rel_in else prefix
        dirnames[:] = _prune(dirnames, rel, cfg, honor_skips)
        for name in sorted(filenames):
            yield d / name, (f"{rel}/{name}" if rel else name)


def iter_targets(cfg: Config, honor_skips: bool = True):
    if cfg.scan_dirs:
        for sub in cfg.scan_dirs:
            base = cfg.root / sub
            if base.is_dir():
                yield from walk(base, sub, cfg, honor_skips)
    else:
        yield from walk(cfg.root, "", cfg, honor_skips)
    for name in cfg.scan_files:
        f = cfg.root / name
        if f.is_file():
            yield f, name


def collect_names(cfg: Config) -> set[str]:
    """裸文件名校验用的**文件名集合**。

    ⚠️ 它与「扫描范围」的取舍**不同**（教训：生成物目录移出版本库后，名字索引若跟着扫描范围走，WARN 会成片反涨）：
      - **范围 = 扫描范围**（`scan_dirs` / `scan_files`），**不是**整个 root ——
        不把 `<<本机私有目录>>/` 这类「既不在扫描面、也**不随仓库分发**」的目录拉进来（否则本机有、别人 clone 没有 ⇒ **假绿**）。
      - **不吃配置级 skip**（`skip_dirs` / `skip_prefixes`）—— `out/`、`<<外部只读资料>>/`、`<<共享基线快照>>/`、
        `<<评审产物目录>>/` 等**被跳过的产物 / 归档 / 冻结快照**，其**文件名仍进索引**：
        跳过的是「**扫它内部**的引用」，不该让「**别人引用它**」变成 WARN。
      - 仍排除内置 `SKIP_DIR_PARTS` 与点目录（`node_modules` / `.git` / `.cache` … ⇒ 性能与噪声）。
    """
    names: set[str] = set()
    for _p, _rel in iter_targets(cfg, honor_skips=False):
        names.add(_p.name)
    return names


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def coverage_verdict(root: Path, cfg_path: str | None, scanned: int) -> tuple[bool, list[str]]:
    """判断本次「扫描范围」是否可信 —— 防的是「假绿」：根不对 ⇒ 只扫一点点 ⇒ ERROR 0。

    可信 = 根上有配置文件（**范围是声明过的**）。
    不可信 = 没配置，且出现下面任一信号：
      · **上级目录里**有配置文件 ⇒ 说明你很可能在仓库的子目录里跑；
      · 扫到的文件数 < MIN_TRUSTED_FILES ⇒ 范围几乎肯定不对。
    """
    if cfg_path:
        return True, []                     # 范围由配置文件声明，可信
    reasons: list[str] = []
    parents = [p for p in root.parents if (p / CONFIG_NAME).is_file()]
    if parents:
        reasons.append(f"在 {root} 找不到 {CONFIG_NAME}，但**上级目录**里有：{parents[0]}"
                       " ⇒ 你很可能在仓库的子目录里跑（真正的根是上面那个）")
    if scanned < MIN_TRUSTED_FILES:
        reasons.append(f"没有配置文件（扫描范围只能靠推断），且只扫到 {scanned} 个文件"
                       f"（阈值 {MIN_TRUSTED_FILES}）⇒ 范围几乎肯定不对")
    return (not reasons), reasons


def load_deny_terms(path: Path, root: Path) -> list[str]:
    """读仓库外的敏感词表。词表落在 <root> 里 ⇒ 抛 ValueError（调用方拒答）。"""
    rp, rr = path.resolve(), root.resolve()
    if rp == rr or rr in rp.parents:
        raise ValueError(f"敏感词表必须放在 {rr} 之外（放在仓库里，词表本身就是泄露）")
    terms = []
    for ln in rp.read_text(encoding="utf-8").splitlines():
        t = ln.strip()
        if t and not t.startswith("#"):
            terms.append(t.casefold())
    if not terms:
        raise ValueError("敏感词表为空（空表 = 什么都没查，不能当通过）")
    return terms


def deny_scan(root: Path, terms: list[str]):
    """逐个文本文件逐行查；产出 (path, rel, 行号, 词序号)。二进制 / 非 UTF-8 文件跳过但计数。"""
    global DENY_SKIPPED
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_PARTS]
        for fn in filenames:
            fp = Path(dirpath) / fn
            try:
                data = fp.read_bytes()
                if b"\0" in data[:4096]:
                    raise UnicodeDecodeError("bin", b"", 0, 1, "binary")
                text = data.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                DENY_SKIPPED.append(fp.relative_to(root).as_posix())
                continue
            rel = fp.relative_to(root).as_posix()
            for i, ln in enumerate(text.splitlines(), start=1):
                low = ln.casefold()
                for idx, t in enumerate(terms, start=1):
                    if t in low:
                        yield fp, rel, i, idx


DENY_SKIPPED: list[str] = []


def main() -> int:
    ap = argparse.ArgumentParser(description="文档路径引用一致性自检（只读）")
    ap.add_argument("--root", default=".", help="仓库根（默认当前目录）")
    ap.add_argument("--config", default=None, help=f"配置文件路径（默认 <root>/{CONFIG_NAME}）")
    ap.add_argument("--include-code", action="store_true", help="同时扫 .py/.json/.yml 等")
    ap.add_argument("--no-legacy", action="store_true", help="跳过 legacy_patterns 检查")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--verbose", action="store_true", help="额外打印解析成功的引用")
    ap.add_argument("--write-default-config", action="store_true",
                    help=f"在 <root> 写出 {CONFIG_NAME} 起步配置后退出")
    ap.add_argument("--allow-untrusted-range", action="store_true",
                    help="扫描范围不可信时仍继续（默认拒绝；见 docstring「覆盖范围」）")
    ap.add_argument("--deny-terms", default=None,
                    help="仓库外的敏感词表（一行一词）；命中记 ERROR，只报位置与词序号，不打印词")
    ap.add_argument("--expect-sha", default=None,
                    help="基准哈希（取自远端主分支上的本脚本）；与本脚本 sha 不符即拒答")
    ap.add_argument("--base", default=None,
                    help="基线提交号（git ls-remote 现取的受保护 main）；external_roots 不得含基线里有过的顶层目录")
    args = ap.parse_args()

    sha = script_sha()
    if args.expect_sha is not None:
        want = args.expect_sha.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{12}", want):
            print(f"🛑 **--expect-sha 必须是恰好 12 位十六进制**（收到：{args.expect_sha!r}）—— 拒绝给出结论")
            return 2
        if want != sha:
            print(f"🛑 **脚本哈希与基准不符 —— 拒绝给出结论**：本脚本 sha={sha}，基准={want}")
            print("   ⇒ 本机这份 verify-refs.py 与基准版本不一致（可能被改过，或落后于 skill 主分支）。")
            return 2

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"! 不是目录：{root}")
        return 2

    if args.write_default_config:
        out = root / CONFIG_NAME
        if out.exists():
            print(f"! 已存在，未覆盖：{out}")
            return 1
        out.write_text(json.dumps(default_config_dict(root), ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        print(f"✅ 已写出起步配置：{out}\n   请按注释调整 scan / skip_prefixes / resolve_bases。")
        return 0

    cfg, cfg_path = load_config(root, args.config)
    base_dirs: set[str] | None = None
    if args.base is not None:
        base_dirs, why = base_top_dirs(root, args.base.strip())
        if base_dirs is None:
            print(f"🛑 **--base 取不到基线 —— 拒绝给出结论**：{why}")
            return 2
    roots_base = args.base.strip().lower()[:12] if base_dirs is not None else "-"
    probs = config_problems(cfg, base_dirs)
    if probs:
        print("🛑 **配置非法 —— 拒绝给出结论**")
        for pr_ in probs:
            print(f"   · {pr_}")
        return 2
    deny_terms: list[str] = []
    if args.deny_terms:
        try:
            deny_terms = load_deny_terms(Path(args.deny_terms), root)
        except (OSError, ValueError) as e:
            print(f"🛑 --deny-terms 拒答：{e}")
            return 2
    if args.include_code:
        cfg.suffixes |= set(CODE_SUFFIXES)

    names = collect_names(cfg)
    errors, warns, infos = [], [], []
    ok_count = scanned = read_ok = 0
    exempt_lines = exempt_ranges = legacy_allow_files = ignore_hits = 0
    unread: list[str] = []
    ignore_used: dict[str, int] = {}
    ignore_at: dict[str, list[str]] = {}

    for path, rel in iter_targets(cfg):
        if path.suffix.lower() not in cfg.suffixes:
            continue
        scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            unread.append(rel)                   # 不再静默跳过：读不出来 = 没检查 ⇒ ERROR
            errors.append((rel, 0, f"<读取失败：{e.__class__.__name__}>"))
            continue
        read_ok += 1

        allow_legacy = any(ALLOW_LEGACY_RE.search(ln) for ln in text.splitlines())
        if allow_legacy:
            legacy_allow_files += 1
        skipping = False
        skip_start_line = 0
        for lineno, line in enumerate(text.splitlines(), start=1):
            if SKIP_START_RE.search(line):
                skipping = True
                skip_start_line = lineno
                exempt_ranges += 1
                continue
            if SKIP_END_RE.search(line):
                skipping = False
                continue
            if skipping or SKIP_LINE_RE.search(line):
                exempt_lines += 1
                continue

            for m in PATH_RE.finditer(line):
                if m.end() < len(line) and line[m.end()] in GLOB_AFTER:
                    continue                     # 通配 / 模板 / 区间后缀，不是真路径
                tok = normalize(m.group(1))
                if not is_candidate(tok, cfg):
                    continue
                if tok in cfg.ignore_refs:
                    ignore_hits += 1
                    ignore_used[tok] = ignore_used.get(tok, 0) + 1
                    ignore_at.setdefault(tok, []).append(f"{rel}:{lineno}")
                    continue
                if resolve(tok, path.parent, cfg) is not None:
                    ok_count += 1
                    if args.verbose:
                        print(f"  ok   {rel}:{lineno}  {tok}")
                    continue
                # 默认 ERROR；只有首段登记在 external_roots 的才降为 WARN（反向开关：漏写只会变严）
                if not tok.startswith("../") and first_segment(tok) in cfg.external_roots:
                    warns.append((rel, lineno, tok))
                else:
                    errors.append((rel, lineno, tok))

            for m in BARE_RE.finditer(line):
                if m.group(1) in names:
                    ok_count += 1
                elif m.group(1) in cfg.ignore_refs:      # 裸名也吃 ignore_refs（旧版只有路径吃，裸名白名单写了不生效）
                    tok = m.group(1)
                    ignore_hits += 1
                    ignore_used[tok] = ignore_used.get(tok, 0) + 1
                    ignore_at.setdefault(tok, []).append(f"{rel}:{lineno}")
                else:
                    warns.append((rel, lineno, m.group(1)))

            if not args.no_legacy and not allow_legacy:
                for pat in cfg.legacy_patterns:
                    if pat in line:
                        infos.append((rel, lineno, pat))

        if skipping:                             # skip-start 没有对应的 skip-end
            errors.append((rel, skip_start_line, f"<{SKIP_START} 未闭合：本文件其余部分被静默跳过>"))

    # 敏感词：词表在仓库外、扫全部文本文件、不吃任何豁免；只报位置和词序号。
    deny_hits: int | None = None
    if args.deny_terms:
        deny_hits = 0
        for dp, rel_d, line_no, idx in deny_scan(root, deny_terms):
            deny_hits += 1
            errors.append((rel_d, line_no, f"<敏感词 #{idx}>"))

    # 死规则：配置写了、却一次都没命中的 skip_prefixes / ignore_refs ⇒ 等于没写，或已过期。
    #   · skip_prefixes：**目录真实存在**却 0 命中 ⇒ WARN（典型：路径基准不一致，`./runs/` 对不上 `runs/`）；
    #     目录还不存在（模板占位、尚未生成）⇒ 只计数，不报 WARN，免得升级后整片变红没人信。
    #   · ignore_refs：0 命中 ⇒ 只计数并列出（过期白名单，日后可能悄悄吞掉一条真缺失）。
    cfg_label = Path(cfg_path).name if cfg_path else CONFIG_NAME
    skip_rules = len(cfg.skip_prefixes) + len(cfg.ignore_refs)
    dead: list[str] = []
    for p in cfg.skip_prefixes:
        if SKIP_HITS.get(p):
            continue
        dead.append(f"skip_prefixes: {p}")
        if (root / p.strip("/")).is_dir():
            warns.append((cfg_label, 0, f"<死规则：目录存在却 0 命中> skip_prefixes: {p}"))
    dead += [f"ignore_refs: {r}" for r in sorted(cfg.ignore_refs) if not ignore_used.get(r)]

    errors, warns, infos = sorted(set(errors)), sorted(set(warns)), sorted(set(infos))

    # --- 自洽断言：读出数 + 读取失败数 == 扫描数 ---------------------------------
    if read_ok + len(unread) != scanned:
        print(f"🛑 **计数不自洽 —— 拒绝给出结论**：读出 {read_ok} + 读取失败 {len(unread)} != 扫描 {scanned}")
        return 2

    # --- 覆盖范围闸门：宁可不给结论，也不给一个「假绿」 -------------------------
    trusted, reasons = coverage_verdict(root, cfg_path, scanned)
    if not trusted and not args.allow_untrusted_range:
        if args.json:
            print(json.dumps({
                "root": str(root), "config": cfg_path, "scanned_files": scanned,
                "coverage_trusted": False, "untrusted_reasons": reasons,
                "refused": True,
            }, ensure_ascii=False, indent=2))
        else:
            print(f"🛑 **扫描范围不可信 —— 拒绝给出结论**（{root}）")
            for r in reasons:
                print(f"   · {r}")
            print(f"   ⇒ 修法（任选）：① 从仓库根跑：`python <repo>/tools/verify-refs.py --root .`；"
                  f"② 显式指定真正的根：`--root <真正的仓库根>`；"
                  f"③ 在根上生成起步配置：`--write-default-config`；"
                  f"④ 确知范围没问题时显式放行：`--allow-untrusted-range`。")
            print("   为什么拒绝：这种情形下它会打印 `ERROR 0`，但那只是「几乎什么都没扫」——"
                  "**不可信的绿比红更危险**（详见 `references/traps.md` 的 A7）。")
        return 2
    # ---------------------------------------------------------------------------

    if args.json:
        print(json.dumps({
            "root": str(root), "config": cfg_path, "scanned_files": scanned,
            "resolved_refs": ok_count,
            "coverage_trusted": trusted, "untrusted_reasons": reasons,
            "sha": sha,
            "external_roots": sorted(cfg.external_roots),
            "roots_base": roots_base,
            "exemptions": {
                "exempt_lines": exempt_lines, "exempt_ranges": exempt_ranges,
                "legacy_allow_files": legacy_allow_files, "ignore_hits": ignore_hits,
                "skip_rules": skip_rules, "dead_rules": dead,
                "skip_prefix_hits": {p: SKIP_HITS.get(p, 0) for p in cfg.skip_prefixes},
                "ignore_ref_hits": {r: {"count": ignore_used.get(r, 0), "at": ignore_at.get(r, [])}
                                    for r in sorted(cfg.ignore_refs)},
            },
            "unread": unread,
            "deny_hits": deny_hits, "deny_skipped_files": DENY_SKIPPED,
            "errors": [{"file": f, "line": n, "ref": t} for f, n, t in errors],
            "warnings": [{"file": f, "line": n, "ref": t} for f, n, t in warns],
            "legacy": [{"file": f, "line": n, "pattern": t} for f, n, t in infos],
        }, ensure_ascii=False, indent=2))
        return 1 if errors else (3 if warns else 0)

    print(f"verify-refs: 扫描 {scanned} 文件，解析成功 {ok_count} 条引用")
    print(f"  仓库根: {root}")
    print(f"  配置  : {cfg_path or '（默认值，无配置文件）'}")
    print(f"  覆盖  : {'配置文件已声明 ✅' if cfg_path else '推断（无配置）'}"
          + ("" if not reasons else "  ⚠️ " + "；".join(reasons)))
    print(f"  豁免  : 跳过 {exempt_lines} 行（{exempt_ranges} 个区间）；allow-legacy {legacy_allow_files} 文件；"
          f"ignore_refs 吞掉 {ignore_hits} 条；配置规则 {skip_rules} 条，其中 0 命中 {len(dead)} 条")
    print(f"  脚本  : sha={sha}（应与远端主分支上的基准一致）")
    for title, rows, fmt in (
        ("ERROR  必修为 0（指向本仓库却解析不到 / 读取失败 / 标记未闭合 / 敏感词）", errors,
         lambda r: f"{r[0]}:{r[1]}  ->  {r[2]}"),
        ("WARN   外部简写 / 裸名未匹配（建议核对）", warns,
         lambda r: f"{r[0]}:{r[1]}  ->  {r[2]}"),
        ("INFO   命中 legacy_patterns（建议更新）", infos,
         lambda r: f"{r[0]}:{r[1]}  ->  {r[2]}"),
    ):
        print(f"\n[{title}] {len(rows)}")
        for r in rows:
            print("  " + fmt(r))

    if dead:
        print(f"\n[死规则  配置写了却 0 命中（只计数；目录存在的 skip 已另记 WARN）] {len(dead)}")
        for d in dead:
            print(f"  {cfg_label}  ->  {d}")

    if deny_hits is not None:
        print(f"\n[敏感词  词表 {len(deny_terms)} 条，命中 {deny_hits} 处（已记 ERROR，不打印词本身）；"
              f"二进制 / 非 UTF-8 未查 {len(DENY_SKIPPED)} 个文件]")
        for f in DENY_SKIPPED:
            print(f"  未查  {f}")

    if not (errors or warns or infos):
        print("\n✅ 未发现问题。")
    # ⭐⭐⭐ **哨兵行（机器可读，唯一锚点）** ：
    #    ⚠️ 背景：总跑器原来**解析人看的散文**（`0 ERROR /`），而**分项里完全可能出现 `0 ERROR`**
    #    （本工具是按文件/按类逐项输出的）⇒ 一行分项命中就判绿 ⇒ **假绿**（而上游还有出口码 1 的干扰：**本工具 0 ERROR 时也可能退出码 1**）。
    #    ⇒ 现在由**本工具自己**打印唯一一行锚点：跑器**只认这一行**、**不再解析散文** ⇒
    #      人看的文案怎么排、分项怎么打，都影响不到闸；⭐ **判据也不再依赖"总计行最后打印"这个未写明的约定**。
    #    ⚠️ 必须在**所有散文之后**打印（放这里，两个 return 之前都覆盖到）。
    #    ⭐⭐ **带戳**：跑器把本次戳经环境变量传进来，
    #    跑器**断言 stamp 等于本次** ⇒ 「子进程读到旧产物」（改脚本与跑它同批）会报"**锚点陈旧**"，
    #    而不只是含混的"未命中锚点" ⇒ **把纪律变成机制** ✓
    #    ⭐ 旧字段原样在前，新字段只追加 —— 豁免 / 死规则 / 读取失败计数 + 本脚本哈希（含义见 docstring）。
    print(f"###VERIFY stamp={os.environ.get('VERIFY_RUN_STAMP', '-')} errors={len(errors)} warns={len(warns)} infos={len(infos)}"
          f" exempt_lines={exempt_lines} exempt_ranges={exempt_ranges} legacy_allow_files={legacy_allow_files}"
          f" ignore_hits={ignore_hits} skip_rules={skip_rules} dead_rules={len(dead)} unread={len(unread)} sha={sha}"
          f" deny_hits={'-' if deny_hits is None else deny_hits} roots_base={roots_base}")
    if errors:
        print(f"\n❌ 退出码 1：{len(errors)} ERROR / {len(warns)} WARN")
        return 1
    if warns:
        print(f"\n⚠️ 退出码 3：0 ERROR / {len(warns)} WARN —— 需人工复核（归 WARN 的规则见 docstring「退出码」）")
        return 3
    return 0


if __name__ == "__main__":
    try:  # Windows 控制台默认 GBK：避免非 GBK 字符抛 UnicodeEncodeError
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    raise SystemExit(main())
