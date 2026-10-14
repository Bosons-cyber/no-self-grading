#!/usr/bin/env python3
"""check-judgefiles.py —— PR「最多碰 1 个判据文件」检查（只读，不看 PR 文件内容）。

定位
    只读两样东西：判据清单（vocab.json 的 judgefiles，CI 里取 main 的那份）和 PR 改动的路径清单，
    外加触发这次运行的事件信息（动作、操作人、标签名）。**从不读取 PR 里任何文件的内容**，
    也不看提交时间（提交时间由提交者自己填，不可信）。

用法
    python check-judgefiles.py --vocab base/vocab.json --paths 改动清单.txt \
        --action synchronize --sender 某账号 [--label 标签名] [--owner Bosons-cyber]
    python check-judgefiles.py --red base/tests/red/judgefiles.json --target pr/scripts/check-judgefiles.py

路径清单
    GitHub 改动文件接口返回的 JSON 列表（取 filename / previous_filename），
    或纯文本：每行一个路径；改名写成「旧路径 制表符 新路径」，新旧都算。

规则（按事件判，不按时间判）
    碰到的判据文件按文件计：≤1 通过。>1 时：
    - 只有「这次事件是加标签、标签名是 multi-sensitive、操作人是所有者账号」才通过；
    - 其余事件（新开、推新提交、重新打开、去标签……）一律不通过，不管 PR 上现在挂着什么标签。
    推新提交会产生新的头提交，之前那次通过不会带过来；所有者要先去掉再重新加一次标签。

退出码：0 = 通过；1 = 不通过（--red 时为有样本没过）；2 = 输入无效。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path



def norm(p: str) -> str:
    p = p.replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/").lower()


def hits(path: str, rules: list[str]) -> bool:
    p = norm(path)
    for r in map(norm, rules):
        if (r.endswith("/") and p.startswith(r)) or p == r:
            return True
    return False


def load_paths(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    out: list[str] = []
    if text[0] == "[":
        for f in json.loads(text):
            if isinstance(f, str):
                out.append(f)
            else:
                out.append(f["filename"])
                if f.get("previous_filename"):
                    out.append(f["previous_filename"])
        return out
    for line in text.splitlines():
        out.extend(x for x in line.split("\t") if x.strip())
    return out


def decide(rules, paths, action, s, mark, o):
    touched = sorted({norm(p) for p in paths if hits(p, rules)})
    if len(touched) <= 1:
        return True, touched, f"碰到判据文件 {len(touched)} 个，通过"
    head = f"碰到判据文件 {len(touched)} 个（上限 1）"
    if action == "labeled" and mark == "multi-sensitive" and s.lower() == o.lower():
        return True, touched, f"{head}；所有者 {o} 刚加了 multi-sensitive，放行"
    if action == "labeled" and mark == "multi-sensitive":
        why = f"multi-sensitive 是 {s or '未知账号'} 加的，不是所有者 {o}"
    else:
        why = f"这次事件是 {action or '未知'}，不是所有者加 multi-sensitive"
    return False, touched, (f"{head}；{why}。请拆成多个 PR；确需一起改，由所有者亲手加 multi-sensitive"
                            f"（有新提交后要先去掉再重新加）")


def run_red(red: Path, target: Path) -> int:
    data = json.loads(red.read_text(encoding="utf-8"))
    rules = data["rules"]
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        vp = Path(tmp) / "vocab.json"
        vp.write_text(json.dumps({"judgefiles": {"paths": rules}}), encoding="utf-8")
        for i, c in enumerate(data["cases"]):
            pp = Path(tmp) / f"p{i}.json"
            pp.write_text(json.dumps(c["paths"], ensure_ascii=False), encoding="utf-8")
            cmd = [sys.executable, str(target), "--vocab", str(vp), "--paths", str(pp),
                   "--action", c.get("action", ""), "--sender", c.get("sender", ""),
                   "--label", c.get("label", "")]
            r = subprocess.run(cmd, capture_output=True, text=True)
            got = r.returncode == 0
            good = got == c["pass"]
            bad += not good
            print(f"{'✅' if good else '❌'} {c['why']}（期望{'通过' if c['pass'] else '不通过'}，"
                  f"实际{'通过' if got else '不通过'}）")
    print(f"红样本 {len(data['cases'])} 条，没过 {bad} 条")
    return 1 if bad else 0


def main() -> int:
    p = argparse.ArgumentParser(description="PR 判据文件个数检查（只读路径清单和事件信息）")
    p.add_argument("--vocab", help="判据清单所在的 vocab.json（CI 里取 main 的那份）")
    p.add_argument("--paths", help="改动路径清单（JSON 或每行一个路径）")
    p.add_argument("--action", default="", help="触发事件的动作，如 opened / synchronize / labeled")
    p.add_argument("--sender", default="", help="触发事件的账号")
    p.add_argument("--label", default="", help="labeled / unlabeled 事件里的标签名")
    p.add_argument("--owner", default="Bosons-cyber", help="可放行的所有者账号")
    p.add_argument("--red", help="红样本文件（tests/red/judgefiles.json）")
    p.add_argument("--target", help="配合 --red：被测的脚本，默认测自己")
    a = p.parse_args()
    if a.red:
        return run_red(Path(a.red), Path(a.target or __file__))
    if not (a.vocab and a.paths):
        p.error("需要 --vocab 和 --paths")
    try:
        rules = json.loads(Path(a.vocab).read_text(encoding="utf-8"))["judgefiles"]["paths"]
        paths = load_paths(Path(a.paths).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"输入无效：{e}", file=sys.stderr)
        return 2
    good, touched, msg = decide(rules, paths, a.action, a.sender, a.label, a.owner)
    print(("✅ " if good else "❌ ") + msg)
    for t in touched:
        print(f"  - {t}")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
