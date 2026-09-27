# -*- coding: utf-8 -*-
"""
pmllib.install —— 安装到 Codex（含清理）

分流：
  * 单专家 → 把 skills/ 与 agents/ 直接落位到 ~/.codex/
  * 专家团 → marketplace 复制到 ~/.codex/plugins/local/ → 注册市场 → 装插件
             → 团员 agent 落位 → 开启 multi_agent
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from . import common as C

# pml 生成的备份命名：config.toml.bak.<YYYYMMDD>-<HHMMSS>
PML_BACKUP_RE = re.compile(r"^config\.toml\.bak\.\d{8}-\d{6}(\.\d+)?$")


# ---------------------------------------------------------------- Codex CLI


def run_codex(args: list[str], timeout: int = 180) -> tuple[int, str]:
    cli = C.codex_cli()
    if cli is None:
        return 127, "未找到 Codex CLI（PATH、config.toml 的 CODEX_CLI_PATH、桌面版安装目录均已尝试）"
    try:
        cp = subprocess.run([str(cli), *args], capture_output=True, text=True,
                            timeout=timeout, encoding="utf-8", errors="replace")
        out = (cp.stdout or "") + (cp.stderr or "")
        return cp.returncode, out
    except subprocess.TimeoutExpired:
        return 124, f"命令超时：codex {' '.join(args)}"
    except Exception as e:  # pragma: no cover
        return 1, f"调用失败：{e}"


def codex_hint() -> str | None:
    cli = C.codex_cli()
    return str(cli) if cli else None


# ---------------------------------------------------------------- 落位 agent


def place_agents(agents_src: Path, codex_home: Path, skip: set[str],
                 dry_run: bool = False) -> list[str]:
    dst_dir = codex_home / "agents"
    placed = []
    for f in sorted(agents_src.glob("*.toml")):
        if f.stem in skip:
            C.skip(f"{f.stem}（主理人由主 session 亲自扮演，默认不装）")
            continue
        if C.copy_item(f, dst_dir / f.name, f"Agent {f.stem}", dry_run,
                       codex_home / C.BACKUP_DIRNAME):
            placed.append(f.stem)
    return placed


def enable_multi_agent(codex_home: Path, dry_run: bool = False) -> None:
    """开启 [features] multi_agent 与 [agents] 并发参数（段已存在则插进段内）。"""
    target = codex_home / "config.toml"
    if not target.exists():
        C.warn(f"{target} 不存在，跳过配置合并")
        return
    content = target.read_text(encoding="utf-8")
    changed = False
    content, c1, m1 = C.ensure_table_key(content, "features", "multi_agent", "multi_agent = true")
    C.ok(m1) if c1 else C.skip(m1)
    content, c2, m2 = C.ensure_table_key(content, "agents", "max_threads",
                                         "max_threads = 4\nmax_depth = 1")
    C.ok(m2) if c2 else C.skip(m2)
    changed = c1 or c2
    if not changed:
        return
    if dry_run:
        C.log("  [预演] 将写回 config.toml")
        return
    C.backup(target)
    target.write_text(content, encoding="utf-8")
    C.ok(f"配置已写回 {target}")


# ---------------------------------------------------------------- 单专家


def install_single(target_dir: Path, codex_home: Path, dry_run: bool = False) -> dict:
    res = {"placed": [], "type": "single"}
    for kind in ("skills", "agents"):
        src = target_dir / kind
        if not src.is_dir():
            continue
        for item in sorted(src.iterdir()):
            bak_root = codex_home / C.BACKUP_DIRNAME
            if kind == "agents" and item.is_file():
                if C.copy_item(item, codex_home / "agents" / item.name,
                               f"Agent {item.stem}", dry_run, bak_root):
                    res["placed"].append(item.stem)
            elif kind == "skills" and item.is_dir():
                if C.copy_item(item, codex_home / "skills" / item.name,
                               f"Skill {item.name}", dry_run, bak_root):
                    res["placed"].append(item.name)
    return res


# ---------------------------------------------------------------- 专家团


def install_team(marketplace_root: Path, plugin_key: str, codex_home: Path,
                 marketplace_name: str, skip_agents: set[str],
                 dry_run: bool = False) -> dict:
    res = {"type": "team", "marketplace": marketplace_name, "steps": []}

    local_dir = codex_home / "plugins" / "local" / f"{marketplace_name}-marketplace"
    if dry_run:
        C.log(f"  [预演] 市场源 -> {local_dir}")
    else:
        if local_dir.exists():
            shutil.rmtree(local_dir)
        local_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(marketplace_root, local_dir)
        C.ok(f"市场源 -> {local_dir}")
    res["steps"].append(f"marketplace -> {local_dir}")

    if dry_run:
        C.log(f"  [预演] codex plugin marketplace add \"{local_dir}\"")
        C.log(f"  [预演] codex plugin add {plugin_key}@{marketplace_name}")
    else:
        rc, out = run_codex(["plugin", "marketplace", "add", str(local_dir)])
        (C.ok if rc == 0 else C.warn)(f"注册市场（rc={rc}）")
        if rc != 0:
            C.log("    " + out.strip().splitlines()[-1] if out.strip() else "")
        res["steps"].append(f"marketplace add rc={rc}")

        rc, out = run_codex(["plugin", "add", f"{plugin_key}@{marketplace_name}"])
        (C.ok if rc == 0 else C.warn)(f"安装插件（rc={rc}）")
        if rc != 0:
            C.log("    " + out.strip().splitlines()[-1] if out.strip() else "")
        res["steps"].append(f"plugin add rc={rc}")

    C.log("  落位团员 Agent：")
    res["placed"] = place_agents(marketplace_root / "plugins" / plugin_key / "agents",
                                 codex_home, skip_agents, dry_run)

    C.log("  开启多 Agent：")
    enable_multi_agent(codex_home, dry_run)
    return res


# ---------------------------------------------------------------- 清理


def clean_backups(codex_home: Path, keep_latest: int = 1, extra: list[Path] | None = None,
                  dry_run: bool = True) -> dict:
    """
    清理 codex 配置备份。
    * 只处理 **pml 命名格式** 的备份（config.toml.bak.<YYYYMMDD>-<HHMMSS>），
      用户自建的历史备份（如 config.toml.bak、config.toml.bak.20260906）一律不碰。
    * extra 用于显式追加（例如手工命名的备份）。
    """
    found = sorted([p for p in codex_home.glob("config.toml.bak.*") if PML_BACKUP_RE.match(p.name)],
                   key=lambda p: p.name)
    victims = found[:-keep_latest] if keep_latest > 0 else found
    keep = found[-keep_latest:] if keep_latest > 0 else []

    if extra:
        for e in extra:
            if e.exists() and e not in victims:
                victims.append(e)

    if dry_run:
        C.log("  [预演] 将删除以下备份：")
    for p in victims:
        if dry_run:
            C.log(f"    - {p.name}  ({p.stat().st_size} B)")
        else:
            p.unlink()
            C.ok(f"已删除 {p.name}")
    for p in keep:
        C.skip(f"保留最新备份 {p.name}")
    return {"deleted": [str(p) for p in victims], "kept": [str(p) for p in keep]}


def clean_zips(paths: list[Path], dry_run: bool = True) -> dict:
    victims = [p for p in paths if p.exists()]
    if dry_run:
        C.log("  [预演] 将删除以下交付 zip：")
    for p in victims:
        if dry_run:
            C.log(f"    - {p.name}  ({p.stat().st_size / 1024 / 1024:.2f} MB)")
        else:
            p.unlink()
            C.ok(f"已删除 {p.name}")
    return {"deleted": [str(p) for p in victims]}
