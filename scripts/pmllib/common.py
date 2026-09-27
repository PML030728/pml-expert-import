# -*- coding: utf-8 -*-
"""
pmllib.common —— 公共工具层

设计约束（为跨机器复用而设，勿破坏）：
  * 仅使用 Python 标准库，无任何第三方依赖
  * 不硬编码任何绝对路径；一切从环境变量、约定位置或参数推导
  * 不假设解释器位置
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- 版本
GENERATOR_NAME = "pml-expert-import"
GENERATOR_VERSION = "1.0.0"
ORIGIN_FILENAME = ".pml-origin.json"

# ---------------------------------------------------------------- 日志


def log(msg: str = "") -> None:
    print(msg, flush=True)


def step(idx: int, total: int, title: str) -> None:
    log(f"\n[{idx}/{total}] {title}")


def ok(msg: str) -> None:
    log(f"  [完成] {msg}")


def skip(msg: str) -> None:
    log(f"  [跳过] {msg}")


def warn(msg: str) -> None:
    log(f"  [注意] {msg}")


def fail(msg: str) -> None:
    log(f"  [失败] {msg}")


# ---------------------------------------------------------------- 路径


def wb_home() -> Path:
    """WorkBuddy 根目录。"""
    env = os.environ.get("WORKBUDDY_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".workbuddy").resolve()


def wb_experts_dir() -> Path:
    """wb 侧已下载的专家包根目录。"""
    return wb_home() / "plugins" / "marketplaces" / "experts" / "plugins"


def wb_manifest_path() -> Path:
    """wb 专家市场全量清单。"""
    return wb_home() / "app" / "cache" / "experts" / "manifest.json"


def wb_bundle_map_path() -> Path:
    """专家 ID → 包名 映射。"""
    return wb_home() / "app" / "cache" / "experts" / "expert-bundle-map.json"


def codex_home() -> Path:
    """Codex 配置目录。"""
    env = os.environ.get("CODEX_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".codex").resolve()


def codex_cli() -> Path | None:
    """
    探测 Codex CLI 可执行文件。不写死路径——依次尝试：
      1. PATH 中的 codex
      2. $CODEX_HOME/config.toml 里记录的 CODEX_CLI_PATH
      3. 桌面版常见安装位置下的最新 hash 目录
    """
    found = shutil.which("codex")
    if found:
        return Path(found)
    found = shutil.which("codex.exe")
    if found:
        return Path(found)

    # 从 config.toml 反查
    cfg = codex_home() / "config.toml"
    if cfg.exists():
        try:
            for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
                if "CODEX_CLI_PATH" in line:
                    cand = line.split("=", 1)[1].strip().strip("'\"")
                    if Path(cand).exists():
                        return Path(cand)
        except Exception:
            pass

    # 桌面版 bin/<hash>/codex.exe，取最新修改的那个
    binroot = Path.home() / "AppData" / "Local" / "OpenAI" / "Codex" / "bin"
    if binroot.is_dir():
        cands = [p / "codex.exe" for p in binroot.iterdir() if p.is_dir()]
        cands = [c for c in cands if c.exists()]
        if cands:
            return max(cands, key=lambda p: p.stat().st_mtime)
    return None


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


# ---------------------------------------------------------------- 文件操作


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_tree(root: Path) -> str:
    """目录内容指纹（相对路径 + 内容），用于幂等判定与版本比对。"""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).replace("\\", "/").encode("utf-8"))
            h.update(p.read_bytes())
    return h.hexdigest()


BACKUP_DIRNAME = ".pml-backups"


def backup(p: Path, backup_root: Path | None = None) -> Path | None:
    """
    备份文件或目录。目录必须用 copytree（copy2 在 Windows 上会抛权限异常）。

    ⚠️ backup_root 给定时集中存放。对 `~/.codex/skills`、`~/.codex/agents` 这类
       **会被扫描的目录**，原地备份会留下 `.bak.*` 垃圾（甚至被 Codex 当成 skill 扫到），
       因此这些位置必须走集中备份。
    """
    if not p.exists():
        return None
    if backup_root is not None:
        backup_root.mkdir(parents=True, exist_ok=True)
        bak = backup_root / f"{p.name}.{stamp()}"
    else:
        bak = p.with_name(f"{p.name}.bak.{stamp()}")
    n = 1
    while bak.exists():
        bak = bak.with_name(f"{bak.name}.{n}")
        n += 1
    if p.is_dir():
        shutil.copytree(p, bak)
    else:
        shutil.copy2(p, bak)
    log(f"    [备份] {p.name} -> {bak}")
    return bak


def same_content(a: Path, b: Path) -> bool:
    if a.is_file() != b.is_file():
        return False
    if a.is_file():
        return a.read_bytes() == b.read_bytes()
    ai = {x.relative_to(a): x for x in a.rglob("*") if x.is_file()}
    bi = {x.relative_to(b): x for x in b.rglob("*") if x.is_file()}
    if ai.keys() != bi.keys():
        return False
    return all(ai[k].read_bytes() == bi[k].read_bytes() for k in ai)


def copy_item(src: Path, dst: Path, label: str = "", dry_run: bool = False,
              backup_root: Path | None = None) -> bool:
    """幂等复制：内容一致则跳过，否则备份后覆盖。返回是否发生了写入。"""
    name = label or src.name
    if not src.exists():
        skip(f"源不存在：{src}")
        return False
    if dst.exists() and same_content(src, dst):
        skip(f"内容已一致：{name}")
        return False
    if dry_run:
        log(f"  [预演] 将写入 {name} -> {dst}")
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        backup(dst, backup_root)
        shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
    shutil.copytree(src, dst) if src.is_dir() else shutil.copy2(src, dst)
    ok(f"{name} -> {dst}")
    return True


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def zip_tree(src: Path, zip_path: Path, arc_prefix: str = "") -> Path:
    """打包目录；强制 UTF-8 文件名标志位，防 Windows 解压中文乱码。"""
    import zipfile

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in sorted(src.rglob("*")):
            if p.is_dir() or "__pycache__" in p.parts:
                continue
            rel = Path(arc_prefix) / p.relative_to(src) if arc_prefix else p.relative_to(src)
            zi = zipfile.ZipInfo(str(rel).replace("\\", "/"))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.flag_bits |= 0x800
            zf.writestr(zi, p.read_bytes())
    return zip_path


# ---------------------------------------------------------------- TOML 安全写入


def ensure_table_key(content: str, table: str, key_name: str, key_block: str):
    """
    确保 [table] 段内存在 key_name。

    ⚠️ TOML 不允许重复定义同一 table。若段已存在，必须把键**插进段内**，
       否则整个配置文件解析失败。

    返回 (新内容, 是否变更, 说明)。
    """
    lines = content.splitlines(keepends=True)
    header = f"[{table}]"
    idx = next((i for i, l in enumerate(lines) if l.strip() == header), None)

    if idx is None:
        return content.rstrip("\n") + f"\n\n{header}\n{key_block}\n", True, f"新建 [{table}] 段"

    end = len(lines)
    for j in range(idx + 1, len(lines)):
        if lines[j].lstrip().startswith("["):
            end = j
            break
    if key_name in "".join(lines[idx + 1:end]):
        return content, False, f"[{table}] 中 {key_name} 已存在"

    lines.insert(idx + 1, key_block + "\n")
    return "".join(lines), True, f"在已有 [{table}] 段内插入 {key_name}"


def load_toml(path: Path) -> dict:
    """读取 TOML；Python 3.11+ 用 tomllib，更低版本降级返回空 dict 并告警。"""
    try:
        import tomllib  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover
        warn("当前 Python < 3.11，缺少 tomllib，跳过 TOML 解析类校验")
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_json(path: Path):
    import json

    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dump_json(path: Path, data) -> None:
    import json

    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def require_py311() -> None:
    if sys.version_info < (3, 11):
        warn(f"当前 Python {sys.version_info.major}.{sys.version_info.minor} < 3.11，"
             f"部分校验能力将降级。建议使用 3.11+。")
