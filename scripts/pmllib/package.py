# -*- coding: utf-8 -*-
"""
pmllib.package —— 封装层

按 E1 规则分流：
  * 单专家（1 个角色）→ 输出散装目录（skills/ + agents/），直接用 skill 形态分发
  * 专家团（多个角色）→ 输出「聚合 marketplace + 独立 plugin source」结构

产出的包里附带一份精简落位脚本，保证包**自身可独立使用**（不必依赖 pml skill 在场）。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import common as C
from .discover import ExpertPackage

DEFAULT_MARKETPLACE = "workbuddy-experts"

# ---------------------------------------------------------------- 模板

FALLBACK_INSTALL_AGENTS = '''# -*- coding: utf-8 -*-
"""团员 Agent 落位脚本（随包分发，不依赖 pml skill）

背景：Codex 官方规定 agents/*.toml 不是可打包的插件组件，只能作为
      「松散文件与插件并存」投递，装完插件后必须再跑一次本脚本。
用法：python install-agents.py [--codex-home PATH] [--dry-run]
"""
import argparse, os, shutil, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "agents"
SKIP = {"__PLACEHOLDER__"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codex-home", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    home = Path(a.codex_home or os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    dst = home / "agents"
    n = 0
    for f in sorted(SRC.glob("*.toml")):
        if f.stem in SKIP:
            continue
        t = dst / f.name
        if t.exists() and t.read_bytes() == f.read_bytes():
            print(f"  [跳过] {f.stem} 已一致")
            continue
        if a.dry_run:
            print(f"  [预演] {f.stem} -> {t}")
            continue
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, t)
        print(f"  [完成] {f.stem} -> {t}")
        n += 1
    print(f"\\n落位 {n} 个。别忘了确认 {home/'config.toml'} 里有 [features] multi_agent = true")
    print("改完重启 Codex 生效。")


if __name__ == "__main__":
    sys.exit(main())
'''

SINGLE_INSTALL = '''# -*- coding: utf-8 -*-
"""单专家落位脚本（随包分发，不依赖 pml skill）

把 skills/* 复制到 ~/.codex/skills/，agents/*.toml 复制到 ~/.codex/agents/。
用法：python install.py [--codex-home PATH] [--dry-run]
"""
import argparse, os, shutil, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codex-home", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    home = Path(a.codex_home or os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    n = 0
    for kind in ("skills", "agents"):
        src = ROOT / kind
        if not src.is_dir():
            continue
        dst_root = home / kind
        for item in sorted(src.iterdir()):
            dst = dst_root / item.name
            if item.is_file() and dst.is_file() and item.read_bytes() == dst.read_bytes():
                print("  [跳过] %s 已一致" % item.name)
                continue
            if a.dry_run:
                print("  [预演] %s/%s -> %s" % (kind, item.name, dst))
                continue
            dst_root.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                bak = dst.with_name(dst.name + ".bak")
                if bak.exists():
                    shutil.rmtree(bak) if bak.is_dir() else bak.unlink()
                shutil.copytree(dst, bak) if dst.is_dir() else shutil.copy2(dst, bak)
                shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
            shutil.copytree(item, dst) if item.is_dir() else shutil.copy2(item, dst)
            print("  [完成] %s/%s -> %s" % (kind, item.name, dst))
            n += 1
    print("")
    print("落位 %d 项。重启 Codex 生效。" % n)


if __name__ == "__main__":
    sys.exit(main())
'''


HOOKS_EXAMPLE = """{
  "//": "SessionStart 钩子模板 —— 默认未启用（hooks 为实验特性）。",
  "//1": "重命名为 hooks.json，把 command 改成 <插件安装目录>/scripts/check-agents.py 的绝对路径",
  "//2": "并在 ~/.codex/config.toml 的 [features] 段加入 codex_hooks = true",
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume",
        "hooks": [
          {
            "type": "command",
            "command": "python",
            "args": ["<PLUGIN_INSTALL_DIR>/scripts/check-agents.py"],
            "statusMessage": "检查团队成员是否就位",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
"""


# ---------------------------------------------------------------- 工具


def clean_category(raw: str) -> str:
    """wb 的 categoryId 形如 `04-DataAI`，Codex 侧只取语义部分。"""
    c = (raw or "").strip()
    if "-" in c and c.split("-", 1)[0].isdigit():
        c = c.split("-", 1)[1]
    return c or "Other"


def build_origin(pkg: ExpertPackage, extra: dict | None = None) -> dict:
    """溯源信息 —— 版本同步比对的依据。"""
    data = {
        "generator": {"name": C.GENERATOR_NAME, "version": C.GENERATOR_VERSION},
        "builtAt": C.datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {
            "package": pkg.key,
            "path": str(pkg.path),
            "expertType": pkg.expert_type,
            "marketId": pkg.market_id,
            "updatedAt": pkg.updated_at,
        },
    }
    if extra:
        data.update(extra)
    return data


def _marketplace_json(marketplace_name: str, entries: list[dict]) -> dict:
    return {
        "name": marketplace_name,
        "interface": {"displayName": "WorkBuddy 专家迁移市场",
                      "shortDescription": "由 WorkBuddy 专家中心迁移而来的 Codex 专家与专家团"},
        "plugins": entries,
    }


def upsert_marketplace(mp_path: Path, marketplace_name: str, entry: dict) -> None:
    """增量写入 marketplace.json —— 一个聚合市场承载多个独立 plugin source。"""
    data = C.load_json(mp_path) if mp_path.exists() else _marketplace_json(marketplace_name, [])
    data["name"] = marketplace_name
    plugins = [p for p in data.get("plugins", []) if p.get("name") != entry["name"]]
    plugins.append(entry)
    data["plugins"] = sorted(plugins, key=lambda p: p.get("name", ""))
    C.dump_json(mp_path, data)


def _plugin_readme(pkg: ExpertPackage, agents: list[str], skills: list[str]) -> str:
    members = "\n".join(f"- `{a}`" for a in agents)
    skills_l = "\n".join(f"- `{s}`" for s in skills)
    return f"""# {pkg.display_zh or pkg.key}

> 由 `{C.GENERATOR_NAME}` v{C.GENERATOR_VERSION} 从 WorkBuddy 专家包 `{pkg.key}` 生成
> 源版本时间：{pkg.updated_at or "未知"}

{pkg.description_zh}

## 成员 Agent

{members}

## 技能

{skills_l}

## 安装后必做

Codex 插件**装不了子 Agent 定义**（官方规定 agent toml 只能作为松散文件与插件并存），
所以装完插件必须再跑一次落位脚本：

```bash
PLUGIN=~/.codex/plugins/cache/<marketplace>/{pkg.key}/<version>
python $PLUGIN/scripts/install-agents.py
```

并确认 `~/.codex/config.toml` 里有：

```toml
[features]
multi_agent = true

[agents]
max_threads = 4
max_depth = 1
```

**跳过这一步，团队会静默退化为单人串行模式**（skill 仍可用，但无法并行派发成员）。

## 怎么用

```bash
# 团队协作：@ 提及整个插件
@{pkg.key} <你的任务>

# 精确到某个成员：@插件名/技能名
@{pkg.key}/{agents[0] if agents else pkg.key} <你的任务>

# 也可用 $ 直接提及技能
${skills[0] if skills else pkg.key} <你的任务>
```

> Codex 调用规范：**plugin 用 `@名称`，skill 用 `$名称`**。
> Codex **没有** `plugin:skill` 这种前缀语法（那是 Claude Code 的规则）。
"""


def _single_readme(pkg: ExpertPackage, agents: list[str], skills: list[str]) -> str:
    return f"""# {pkg.display_zh or pkg.key}（单专家 · skill 形态）

> 由 `{C.GENERATOR_NAME}` v{C.GENERATOR_VERSION} 从 WorkBuddy 专家包 `{pkg.key}` 生成

{pkg.description_zh}

本专家为**单专家**（{len(agents)} 个角色），按规则采用 **skill 形态**（不封 plugin）。

## 含内容

- 技能：{", ".join("`" + s + "`" for s in skills) or "无"}
- Agent：{", ".join("`" + a + "`" for a in agents) or "无"}

## 安装

```bash
python scripts/install.py
```

脚本会把 `skills/*` 复制到 `~/.codex/skills/`、`agents/*.toml` 复制到 `~/.codex/agents/`，
改前自动备份、内容一致则跳过。

## 怎么用

```bash
# 显式提及技能
${skills[0] if skills else pkg.key} <你的任务>

# 或直接描述任务，按 description 隐式触发
```
"""


# ---------------------------------------------------------------- 打包入口


def pack(pkg: ExpertPackage, converted_root: Path, out_root: Path,
         marketplace_name: str = DEFAULT_MARKETPLACE) -> dict:
    """
    converted_root: convert_package() 的输出（含 skills/ 与 agents/）
    返回描述 dict：{mode, target, files}
    """
    out_root.mkdir(parents=True, exist_ok=True)
    skills = sorted(p.name for p in (converted_root / "skills").iterdir() if p.is_dir())
    agents = sorted(p.stem for p in (converted_root / "agents").glob("*.toml"))
    skipped_agents = {pkg.agent_name} if pkg.is_team else set()  # 团队主理由主 session 扮演

    if pkg.is_team:
        # ---------------- 专家团 → marketplace + plugin
        mp_root = out_root / marketplace_name
        plugin = mp_root / "plugins" / pkg.key
        (plugin / ".codex-plugin").mkdir(parents=True, exist_ok=True)

        # 1) plugin.json
        manifest = {
            "name": pkg.key,
            "version": "1.0.0",
            "description": pkg.description_zh or pkg.display_zh,
            "author": {"name": "WorkBuddy Team"},
            "keywords": [],
            "skills": "./skills/",
            "interface": {
                "displayName": pkg.display_zh or pkg.key,
                "shortDescription": (pkg.description_zh or "")[:60],
                "developerName": "WorkBuddy Team",
                "category": clean_category(pkg.category),
                "capabilities": [],
            },
        }
        C.dump_json(plugin / ".codex-plugin" / "plugin.json", manifest)

        # 2) 技能与 agent（从转换产物搬运）
        for src, dst in ((converted_root / "skills", plugin / "skills"),
                         (converted_root / "agents", plugin / "agents")):
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

        # 3) 落位脚本（内嵌模板，保证包自足）
        tpl = FALLBACK_INSTALL_AGENTS.replace(
            '"__PLACEHOLDER__"', ", ".join(f'"{a}"' for a in sorted(skipped_agents))
        )
        C.write_text(plugin / "scripts" / "install-agents.py", tpl)

        # 4) 钩子模板与说明
        C.write_text(plugin / "hooks" / "hooks.example.json", HOOKS_EXAMPLE)
        C.write_text(plugin / "README.md", _plugin_readme(pkg, agents, skills))

        # 5) 溯源
        C.dump_json(plugin / C.ORIGIN_FILENAME, build_origin(pkg, {
            "mode": "team-plugin",
            "marketplace": marketplace_name,
            "skills": skills,
            "agents": agents,
            "installSkips": sorted(skipped_agents),
        }))

        # 6) 聚合市场清单（增量）
        upsert_marketplace(mp_root / ".agents" / "plugins" / "marketplace.json",
                           marketplace_name,
                           {"name": pkg.key,
                            "source": {"source": "local", "path": f"./plugins/{pkg.key}"},
                            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                            "category": clean_category(pkg.category)})
        return {"mode": "team-plugin", "target": plugin,
                "marketplace": mp_root, "files": len(list(plugin.rglob("*")))}

    # ---------------- 单专家 → 散装 skill
    single = out_root / pkg.key
    for src, dst in ((converted_root / "skills", single / "skills"),
                     (converted_root / "agents", single / "agents")):
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)

    C.write_text(single / "scripts" / "install.py", SINGLE_INSTALL)

    C.write_text(single / "README.md", _single_readme(pkg, agents, skills))
    C.dump_json(single / C.ORIGIN_FILENAME, build_origin(pkg, {
        "mode": "single-skill", "skills": skills, "agents": agents,
    }))
    return {"mode": "single-skill", "target": single, "files": len(list(single.rglob("*")))}
