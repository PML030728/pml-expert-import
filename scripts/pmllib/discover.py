# -*- coding: utf-8 -*-
"""
pmllib.discover —— 源发现与解析

职责：
  * 枚举 wb 侧「已下载」的专家包（= 曾被召唤过的专家）
  * 把用户输入的任意写法（包名 / 专家 ID / 中文名 / 英文名）解析为具体包
  * 区分「市场里有但本地未下载」的情形，并给出明确提示
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import common as C


@dataclass
class ExpertPackage:
    key: str                       # 包目录名，也是 plugin 名
    path: Path                     # 包目录
    expert_type: str               # agent | team
    agent_name: str                # 主 agent 名
    display_zh: str = ""
    display_en: str = ""
    description_zh: str = ""
    category: str = ""
    agent_files: list[str] = field(default_factory=list)   # agents/*.md 的 stem
    skill_dirs: list[str] = field(default_factory=list)     # skills/* 的目录名
    members: list[dict] = field(default_factory=list)
    market_id: str = ""            # wb 市场清单里的 id
    updated_at: str = ""

    @property
    def is_team(self) -> bool:
        return self.expert_type == "team"

    @property
    def role_count(self) -> int:
        """角色数 —— E1 的封装判定依据（不是 skill 数）。"""
        return max(len(self.agent_files), 1)

    def label(self) -> str:
        name = self.display_zh or self.display_en or self.key
        kind = "专家团" if self.is_team else "单专家"
        return f"{name}（{kind}，{self.role_count} 个角色）"


# ---------------------------------------------------------------- 扫描


def scan_downloaded() -> list[ExpertPackage]:
    """枚举 wb 侧已下载的专家包。"""
    root = C.wb_experts_dir()
    if not root.is_dir():
        return []
    pkgs = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        pj = d / ".codebuddy-plugin" / "plugin.json"
        if pj.exists():
            pkgs.append(load_package(pj))
    return pkgs


def load_package(plugin_json: Path) -> ExpertPackage:
    """从 .codebuddy-plugin/plugin.json 构造 ExpertPackage。"""
    d = C.load_json(plugin_json)
    pkg_dir = plugin_json.parent.parent

    agent_files = [Path(p).stem for p in d.get("agents", []) if str(p).endswith(".md")]
    skill_dirs = [Path(str(p)).name for p in d.get("skills", [])]

    dn = d.get("displayName", {}) or {}
    desc = d.get("displayDescription", {}) or {}

    return ExpertPackage(
        key=d.get("name") or pkg_dir.name,
        path=pkg_dir,
        expert_type=d.get("expertType", "agent"),
        agent_name=d.get("agentName", agent_files[0] if agent_files else ""),
        display_zh=dn.get("zh", ""),
        display_en=dn.get("en", ""),
        description_zh=desc.get("zh", ""),
        category=d.get("categoryId", ""),
        agent_files=agent_files,
        skill_dirs=skill_dirs,
        members=d.get("members", []) or [],
    )


# ---------------------------------------------------------------- 市场信息


def load_market_index() -> tuple[dict, dict]:
    """
    返回 (by_plugin, by_id)：
      by_plugin: 包名 -> 市场条目
      by_id    : 市场 id -> 市场条目
    市场清单可能不存在（用户清理过缓存），此时返回空表。
    """
    p = C.wb_manifest_path()
    if not p.exists():
        return {}, {}
    try:
        data = C.load_json(p)
    except Exception:
        return {}, {}
    by_plugin, by_id = {}, {}
    for e in data.get("experts", []) or []:
        if not isinstance(e, dict):
            continue
        if e.get("plugin"):
            by_plugin[e["plugin"]] = e
        if e.get("id"):
            by_id[e["id"]] = e
    return by_plugin, by_id


def enrich(pkg: ExpertPackage) -> ExpertPackage:
    """补上市场侧的 id 与 updatedAt（用于版本同步比对）。"""
    by_plugin, _ = load_market_index()
    e = by_plugin.get(pkg.key)
    if e:
        pkg.market_id = str(e.get("id", ""))
        pkg.updated_at = str(e.get("updatedAt", ""))
    return pkg


# ---------------------------------------------------------------- 解析输入


def _norm(s: str) -> str:
    return (s or "").strip().lower().replace(" ", "").replace("　", "")


def resolve(query: str) -> ExpertPackage | None:
    """把任意写法的专家名解析为已下载的包；找不到返回 None。"""
    pkgs = [enrich(p) for p in scan_downloaded()]
    q = _norm(query)
    if not q:
        return None

    # 1) 精确匹配：包名 / 市场 id / 中英文显示名
    for p in pkgs:
        keys = {_norm(p.key), _norm(p.market_id), _norm(p.display_zh), _norm(p.display_en),
                _norm(p.agent_name)}
        if q in keys:
            return p

    # 2) 模糊匹配：包含关系
    fuzzy = []
    for p in pkgs:
        for cand in (p.key, p.market_id, p.display_zh, p.display_en):
            if cand and (q in _norm(cand) or _norm(cand) in q):
                fuzzy.append(p)
                break
    if len(fuzzy) == 1:
        return fuzzy[0]
    if len(fuzzy) > 1:
        return None  # 有歧义，交由调用方提示

    return None


def resolve_all() -> list[ExpertPackage]:
    """全量：所有已下载的专家包。"""
    return [enrich(p) for p in scan_downloaded()]


def market_only_hint(query: str) -> str | None:
    """
    用户想导入的专家在市场里存在、但本地未下载时的提示语。
    返回 None 表示市场里也查不到。
    """
    _, by_id = load_market_index()
    by_plugin, _ = load_market_index()
    q = _norm(query)
    hit = None
    for e in list(by_id.values()) + list(by_plugin.values()):
        dn = e.get("displayName", {}) or {}
        cands = [_norm(e.get("plugin", "")), _norm(e.get("id", "")),
                 _norm(dn.get("zh", "")), _norm(dn.get("en", ""))]
        if q and any(q == c or (c and q in c) for c in cands if c):
            hit = e
            break
    if not hit:
        return None
    dn = (hit.get("displayName", {}) or {}).get("zh") or hit.get("id")
    return (
        f"「{dn}」在 WorkBuddy 专家市场中存在，但**本地尚未下载**。\n"
        f"  导入的前提是源包已在本地——请先在 WorkBuddy 里召唤一次该专家\n"
        f"  （召唤后包会落到 {C.wb_experts_dir()}），再回来执行导入。"
    )


def list_available() -> str:
    """人类可读的可用清单。"""
    pkgs = resolve_all()
    if not pkgs:
        return f"未发现任何已下载的专家包。请确认路径：{C.wb_experts_dir()}"
    lines = [f"wb 侧已下载 {len(pkgs)} 个专家包（= 曾被召唤过，可导入）：", ""]
    for i, p in enumerate(pkgs, 1):
        lines.append(f"  {i}. {p.label()}")
        lines.append(f"     包名/别名：{p.key}"
                     + (f" / {p.market_id}" if p.market_id else ""))
        if p.display_zh and p.display_zh != p.key:
            lines.append(f"     中文名：{p.display_zh}")
        lines.append(f"     技能数：{len(p.skill_dirs)}    本地路径：{p.path}")
    return "\n".join(lines)
