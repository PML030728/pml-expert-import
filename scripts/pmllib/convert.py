# -*- coding: utf-8 -*-
"""
pmllib.convert —— 双产物生成（E3 核心）

       WorkBuddy 原始包（唯一真相来源）
         │
         ├── agents/<name>.md ──┬──▶ skills/<name>/SKILL.md   产物 A（知识层）
         │                      └──▶ agents/<name>.toml       产物 B（执行层）
         └── skills/<共享技能>/ ────▶ skills/<共享技能>/         原样搬运 + 命名规范化

两条产出线**各自直接读源**，禁止读取对方输出。
"""

from __future__ import annotations

import re
from pathlib import Path

from . import common as C
from .discover import ExpertPackage

KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# ---------------------------------------------------------------- 工具名换算表
# WorkBuddy 专有工具 → Codex Subagents 协议
TOOL_MAP = [
    ("TeamCreate", "（Codex 无此工具：父 session 本身就是编排者，不存在「创建团队」这一步）"),
    ("subagent_type", "（Codex 无此参数）"),
    ("SendMessage", "report_agent_job_result"),
    ("spawn_agent", "spawn_agent"),
]

CODEX_AGENT_GUIDE = """## 结果回报约定（Codex Subagents）

你是由主理人通过 `spawn_agent("<agent-name>")` 派发的正式子 Agent，在自己的独立线程中工作。

完成分析后，**必须调用 `report_agent_job_result` 返回结构化结果**。

补充约定：
- 返回内容必须是**完整原文**，不要为了简短而省略关键数据、代码或表格——主理人依赖这些内容做后续编排与汇编。
- 若主理人通过 `send_input` 追加追问，在原有上下文基础上继续，不必重复已交付的部分。
- 不要在返回中声称"已完成"却不给实质内容。
"""

CODEX_TEAM_RULES = """## 团队协作机制（Codex 铁律）

你必须走正式的**子 Agent 协作流程**，严禁简化或跳过：

1. **派发子 Agent**：用 `spawn_agent("<agent-name>")` 派发成员。Codex 的父 session 本身就是编排者，
   **不存在也不需要"创建团队"这一步**。每位成员必须是独立线程、持有自己的上下文。
2. **唯一调度方式**：`spawn_agent` 是在 Codex 中派发成员的唯一方式。
   `TeamCreate`、`SendMessage`、`subagent_type` 这些在原平台使用的工具在 Codex 中**不存在**，一律不要调用。
3. **结果回收**：用 `wait_agent` 等待成员完成；成员通过 `report_agent_job_result` 返回结构化产出；
   需要追问时用 `send_input` 向指定成员二次下发。
4. **信息中转**：所有跨成员的信息流必须经你转交，成员之间不直连。
5. **成员结论为准**：任何专业产出必须由对应成员线程输出后再采信，你只做编排与汇编。
6. **并行原则**：相互独立的工作并行 spawn，有依赖关系的必须串行。
7. **不得代写**：禁止自己模拟成员发言，也禁止再 spawn 一个"主理人"子线程去做编排。

### 成员 Agent 名称（CRITICAL）

`spawn_agent` 传入的名称必须与 `~/.codex/agents/` 下的 agent 名严格一致。
"""


# ---------------------------------------------------------------- 工具


def toml_str(s: str) -> str:
    """选择安全的多行字符串定界符，避免转义问题。"""
    if "'''" in s and '"""' in s:
        raise ValueError("正文同时包含两种三引号，无法安全序列化")
    if "'''" in s:
        return '"""\n' + s.replace("\\", "\\\\") + '\n"""'
    return "'''\n" + s + "\n'''"


def split_frontmatter(text: str) -> tuple[str, str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[1], parts[2].lstrip("\n")
    return "", text


def fm_get(fm: str, key: str, default: str = "") -> str:
    """
    取 frontmatter 中某个键的值。

    ⚠️ 分隔符一律用 [ \\t] 而非 \\s：\\s 会跨行吞掉下一行内容，
       导致 `displayName:`（空值键）把紧跟的 `en: "Nova"` 当成自己的值，
       进而污染 description。
    """
    # 多行块标量：key: |  或  key: >
    m2 = re.search(rf"^{re.escape(key)}[ \t]*:[ \t]*[|>]-?[ \t]*\n((?:[ \t]+.+\n?)+)", fm, re.M)
    if m2:
        return " ".join(x.strip() for x in m2.group(1).splitlines()).strip()

    # 单行标量：值必须以非空白字符开头，且不跨行
    m = re.search(rf"^{re.escape(key)}[ \t]*:[ \t]*(\S.*?)[ \t]*$", fm, re.M)
    if not m:
        return default
    return m.group(1).strip().strip('"').strip("'")


def normalize_shared_skill(dst: Path, name: str, pkg: ExpertPackage,
                          source_dir_name: str) -> list[str]:
    """
    共享技能复制后规范化 frontmatter：
      * name 必须与目录名一致（否则 Codex 不加载）
      * 缺 description 则补（否则无法隐式触发）
    尽量只改这两处，保留源文件的其他字段。
    """
    notes: list[str] = []
    f = dst / "SKILL.md"
    if not f.exists():
        return [f"{name}: 源技能缺 SKILL.md"]

    text = f.read_text(encoding="utf-8")
    fm, body = split_frontmatter(text)
    cur = fm_get(fm, "name")
    has_desc = bool(re.search(r"^description\s*:", text, re.M))

    if cur == name and has_desc:
        return notes

    if fm:  # 已有 frontmatter → 原地修正
        if cur != name:
            text = re.sub(r"^name\s*:.*$", f"name: {name}", text, count=1, flags=re.M)
            notes.append(f"frontmatter name 对齐 {cur or '(缺)'} → {name}")
        if not has_desc:
            desc = pkg.description_zh or pkg.display_zh or f"{name} 技能包"
            text = re.sub(r"^(name\s*:.*)$",
                          lambda m: f"{m.group(1)}\ndescription: |\n  {desc}",
                          text, count=1, flags=re.M)
            notes.append("补全 description")
    else:  # 无 frontmatter → 新建
        desc = pkg.description_zh or pkg.display_zh or f"{name} 技能包"
        text = (f"---\nname: {name}\ndescription: |\n  {desc}\n"
                f"metadata:\n  author: pml-expert-import\n"
                f'  source-package: "{pkg.key}"\n---\n\n' + text.lstrip("\n"))
        notes.append("新建 frontmatter")

    f.write_text(text, encoding="utf-8")
    return notes


def ascii_skill_name(raw: str, agent_name: str, existing: set[str]) -> tuple[str, bool]:
    """
    规范化共享技能目录名。返回 (新名, 是否改名)。

    Codex 要求 skill 名 kebab-case 且必须与父目录同名；源包常见中文名
    （如 `09-python全栈工程师`）必须改名。改名后若与角色 skill 撞名会导致
    内容被覆盖丢失，故这里做避让。
    """
    if KEBAB.match(raw) and raw not in existing:
        return raw, False
    base = f"{agent_name}-kit"
    if base not in existing:
        return base, True
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}", True


# ---------------------------------------------------------------- 正文换算


def convert_tool_refs(body: str, agent_names: list[str]) -> tuple[str, list[str]]:
    """工具名换算 + 结构级段落重写。返回 (新正文, 告警列表)。"""
    notes: list[str] = []
    out = body

    # 1) 成员的「SendMessage 回传要求」段落 → Codex 版
    m = re.search(r"##\s*SendMessage 回传要求\s*\n+(.*)$", out, re.S)
    if m:
        seg = m.group(1)
        im = re.search(r"包括[：:](.+?)。", seg)
        items = im.group(1).strip() if im else "完整专业产出"
        out = out[: m.start()].rstrip()
        out += "\n\n" + CODEX_AGENT_GUIDE.replace("结构化结果", f"结构化结果，内容需包含：{items}")

    # 2) 团队协作机制段落（主理人）
    if re.search(r"##\s*团队协作机制（?铁律）?", out):
        members_block = "\n".join(f"- `{n}`" for n in agent_names)
        new_rules = CODEX_TEAM_RULES + members_block + "\n"
        out = re.sub(r"##\s*团队协作机制（?铁律）?.*?(?=\n##\s|\Z)", new_rules, out, flags=re.S)
        notes.append("重写了「团队协作机制」段落")

    # 3) 协作规则里的旧流程描述
    out = out.replace(
        '"TeamCreate → Agent spawn → SendMessage 回传"',
        '"spawn_agent → report_agent_job_result 回传 → wait_agent 回收"',
    )
    out = re.sub(
        r"在 Agent 工具的\s*`?name`?\s*参数中传入[^\n。]*。",
        "`spawn_agent` 的名称必须使用成员 Agent ID，不得使用中文名或自创名称，否则调度会失败。",
        out,
    )

    # 4) 残留工具名审计：只报「非否定语境」的提及
    #    （我们自己写的"XX 在 Codex 中不存在，禁止调用"属预期，不该报警）
    NEG = ("不存在", "禁止", "无此", "不要调用", "不会调用", "不再存在")
    for wb_tool, _ in TOOL_MAP:
        if wb_tool == "spawn_agent" or wb_tool not in out:
            continue
        hits = [l for l in out.splitlines()
                if wb_tool in l and not any(n in l for n in NEG)]
        if hits:
            notes.append(f"正文有 {len(hits)} 行仍提及 `{wb_tool}` 且非否定语境（建议人工复核）")

    return out, notes


# ---------------------------------------------------------------- 产物 A：skill


def build_skill(pkg: ExpertPackage, agent_file: Path, skill_name: str,
                agents_dir_out: Path, skills_dir_out: Path) -> tuple[Path, list[str]]:
    """由源 agents/<name>.md 生成 skills/<skill_name>/SKILL.md。"""
    raw = agent_file.read_text(encoding="utf-8")
    fm, body = split_frontmatter(raw)

    desc = fm_get(fm, "description") or pkg.description_zh or pkg.display_zh
    display_zh = fm_get(fm, "displayName") or pkg.display_zh
    # 触发词前置：中文名（若有）+ 源描述
    if display_zh and display_zh not in desc:
        desc = f"{display_zh}：{desc}"

    all_agents = pkg.agent_files
    body, notes = convert_tool_refs(body, all_agents)

    out_dir = skills_dir_out / skill_name
    content = (
        "---\n"
        f"name: {skill_name}\n"
        "description: |\n"
        + "".join(f"  {line}\n" for line in desc.splitlines() or [""])
        + "metadata:\n"
        "  author: pml-expert-import\n"
        f'  generator: "{C.GENERATOR_NAME} {C.GENERATOR_VERSION}"\n'
        f'  source-package: "{pkg.key}"\n'
        f'  source-expert-id: "{pkg.market_id}"\n'
        f'  source-agent: "{agent_file.stem}"\n'
        + "---\n\n"
        + body.rstrip() + "\n"
    )
    C.write_text(out_dir / "SKILL.md", content)
    return out_dir, notes


# ---------------------------------------------------------------- 产物 B：agent toml


DEFAULT_EFFORT = {"lead": "high", "default": "medium"}


def build_agent_toml(pkg: ExpertPackage, agent_file: Path, agent_name: str,
                     agents_dir_out: Path, out_agents_ref: str = "skills/") -> tuple[Path, list[str]]:
    """由源 agents/<name>.md 生成 agents/<agent_name>.toml（与 skill 并列产出，互不依赖）。"""
    raw = agent_file.read_text(encoding="utf-8")
    fm, body = split_frontmatter(raw)

    desc = fm_get(fm, "description") or pkg.description_zh or pkg.display_zh
    is_lead = agent_name == pkg.agent_name or agent_file.stem == pkg.agent_name
    body, notes = convert_tool_refs(body, pkg.agent_files)

    # 让 skill 与 agent 的映射可追溯，但不构成依赖
    header = (
        f"# 由 {C.GENERATOR_NAME} v{C.GENERATOR_VERSION} 从 WorkBuddy 专家包生成\n"
        f"# 源包：{pkg.key}　源角色文件：agents/{agent_file.name}\n"
        f"# 配套 skill：{out_agents_ref}{agent_name}/SKILL.md（内容各自独立，互不依赖）\n\n"
    )
    content = (
        header
        + f'name = "{agent_name}"\n'
        + f"description = {toml_str(desc)}\n"
        + f'model_reasoning_effort = "{DEFAULT_EFFORT["lead"] if is_lead else DEFAULT_EFFORT["default"]}"\n'
        + 'sandbox_mode = "workspace-write"\n\n'
        + f"developer_instructions = {toml_str(body.strip())}\n"
    )
    out = agents_dir_out / f"{agent_name}.toml"
    C.write_text(out, content)
    return out, notes


# ---------------------------------------------------------------- 编排


def convert_package(pkg: ExpertPackage, out_root: Path) -> dict:
    """
    把一个专家包转换为 Codex 产物。返回结果描述 dict。
    产物布局：
      <out_root>/skills/<skill>/...      产物 A
      <out_root>/agents/<agent>.toml     产物 B
      <out_root>/shared/<skill>/...      共享技能（原样搬运）
    """
    skills_out = out_root / "skills"
    agents_out = out_root / "agents"
    skills_out.mkdir(parents=True, exist_ok=True)
    agents_out.mkdir(parents=True, exist_ok=True)

    result = {"package": pkg.key, "type": pkg.expert_type,
              "skills": [], "agents": [], "shared": [], "notes": []}

    # 主理人在团队里改名，避免与 plugin 同名造成歧义
    def skill_name_for(agent_stem: str) -> str:
        if pkg.is_team and agent_stem == pkg.agent_name:
            return "copilot-orchestrator" if pkg.key.endswith("copilot") else f"{pkg.key}-orchestrator"
        return agent_stem

    # ---- 双产物：同一源文件，两条独立产出线
    for agent_file in sorted((pkg.path / "agents").glob("*.md")):
        stem = agent_file.stem
        s_name = skill_name_for(stem)
        a_path, n1 = build_skill(pkg, agent_file, s_name, agents_out, skills_out)
        t_path, n2 = build_agent_toml(pkg, agent_file, stem, agents_out)
        result["skills"].append(s_name)
        result["agents"].append(stem)
        for n in set(n1) | set(n2):
            result["notes"].append(f"{stem}: {n}")

    # ---- 共享技能：原样搬运 + 目录名规范化 + 同步改写引用
    for sdir in sorted((pkg.path / "skills").iterdir()) if (pkg.path / "skills").is_dir() else []:
        if not sdir.is_dir():
            continue
        existing = {p.name for p in skills_out.iterdir() if p.is_dir()}
        new_name, renamed = ascii_skill_name(sdir.name, pkg.agent_name, existing)
        dst = skills_out / new_name
        import shutil
        shutil.copytree(sdir, dst)
        result["shared"].append(new_name)
        for note in normalize_shared_skill(dst, new_name, pkg, sdir.name):
            result["notes"].append(f"{new_name}: {note}")

        if renamed:
            # 同步改写所有产物里对该旧路径的引用
            for f in list(skills_out.rglob("SKILL.md")) + list(agents_out.glob("*.toml")):
                txt = f.read_text(encoding="utf-8")
                for old in (f"skills/{sdir.name}/", f"{sdir.name}/SKILL.md", f"skills/{sdir.name}"):
                    new = old.replace(sdir.name, new_name)
                    txt = txt.replace(old, new)
                f.write_text(txt, encoding="utf-8")
            result["notes"].append(f"共享技能目录改名：{sdir.name} → {new_name}（引用已同步改写）")

    return result
