# -*- coding: utf-8 -*-
"""
pmllib.checks —— 产物校验与版本同步比对
"""

from __future__ import annotations

import re
from pathlib import Path

from . import common as C

KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


# ---------------------------------------------------------------- 校验


def verify_skill_dir(d: Path) -> list[str]:
    """单个 skill 目录的规范校验。"""
    issues = []
    f = d / "SKILL.md"
    if not f.exists():
        return [f"{d.name}: 缺少 SKILL.md"]
    text = f.read_text(encoding="utf-8")
    m = re.search(r"^name\s*:\s*(.+?)\s*$", text, re.M)
    name = m.group(1) if m else ""
    if not name:
        issues.append(f"{d.name}: frontmatter 缺 name")
    elif name != d.name:
        issues.append(f"{d.name}: name({name}) 与目录名不一致 → skill 不会加载")
    elif not KEBAB.match(name):
        issues.append(f"{d.name}: name 非 kebab-case")
    if not re.search(r"^description\s*:", text, re.M):
        issues.append(f"{d.name}: frontmatter 缺 description（隐式触发的唯一依据）")
    return issues


def verify_agent_toml(f: Path) -> list[str]:
    issues = []
    try:
        d = C.load_toml(f)
    except Exception as e:
        return [f"{f.name}: TOML 解析失败 {e}"]
    if not d:
        return []
    for k in ("name", "description", "developer_instructions"):
        if not d.get(k):
            issues.append(f"{f.name}: 缺必填字段 {k}")
    if d.get("name") and d["name"] != f.stem:
        issues.append(f"{f.name}: name({d['name']}) 与文件名不一致")
    return issues


def verify_package(root: Path) -> dict:
    """校验转换/封装产物。root 可以是 plugin 根或单专家根。"""
    report = {"skills": [], "agents": [], "json": [], "name_check": [], "ok": True}

    skills = root / "skills"
    if skills.is_dir():
        for d in sorted(skills.iterdir()):
            if d.is_dir():
                report["skills"].extend(verify_skill_dir(d))

    agents = root / "agents"
    if agents.is_dir():
        for f in sorted(agents.glob("*.toml")):
            report["agents"].extend(verify_agent_toml(f))

    for f in root.rglob("*.json"):
        if "__pycache__" in f.parts:
            continue
        try:
            C.load_json(f)
        except Exception as e:
            report["json"].append(f"{f.relative_to(root)}: JSON 非法 {e}")

    # 三方名称一致性（仅 plugin 形态）
    pj = root / ".codex-plugin" / "plugin.json"
    if pj.exists():
        try:
            manifest = C.load_json(pj)
            if manifest.get("name") != root.name:
                report["name_check"].append(
                    f"manifest name({manifest.get('name')}) != 目录名({root.name})")
        except Exception:
            pass

    report["ok"] = not (report["skills"] or report["agents"]
                        or report["json"] or report["name_check"])
    return report


def print_report(root: Path, report: dict) -> None:
    if report["ok"]:
        C.ok(f"产物校验通过：{root}")
        n_sk = len(list((root / 'skills').iterdir())) if (root / 'skills').is_dir() else 0
        n_ag = len(list((root / 'agents').glob('*.toml'))) if (root / 'agents').is_dir() else 0
        C.log(f"       skills {n_sk} 个，agents {n_ag} 个，JSON 全部合法")
        return
    for k, label in (("skills", "Skill"), ("agents", "Agent"), ("json", "JSON"), ("name_check", "命名")):
        for i in report[k]:
            C.warn(f"{label}：{i}")


# ---------------------------------------------------------------- 同步比对


def find_origin_files(root: Path) -> list[Path]:
    return sorted(root.rglob(C.ORIGIN_FILENAME))


def sync_check(universe: Path | None = None) -> list[dict]:
    """
    比对已建产物与 wb 源的版本。
    返回 [{origin_file, package, built_updatedAt, source_updatedAt, outdated}]
    """
    from . import discover as D

    by_plugin, _ = D.load_market_index()
    out = []
    roots = [universe] if universe else _default_scan_roots()
    for root in roots:
        if not root or not root.exists():
            continue
        for of in find_origin_files(root):
            try:
                data = C.load_json(of)
            except Exception:
                continue
            src = data.get("source", {}) or {}
            key = src.get("package", "")
            built = src.get("updatedAt", "")
            cur = (by_plugin.get(key, {}) or {}).get("updatedAt", "")
            out.append({
                "origin_file": str(of),
                "package": key,
                "built_updatedAt": built,
                "source_updatedAt": cur,
                "outdated": bool(cur and built and cur != built),
                "present": bool(cur),
            })
    return out


def _default_scan_roots() -> list[Path]:
    home = Path.home()
    cands = [
        Path.cwd() / "pml-dist",
        C.codex_home() / "plugins" / "local",
        C.codex_home() / "skills",
    ]
    return [c for c in cands if c.exists()]
