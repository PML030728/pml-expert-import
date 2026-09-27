#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pml-expert-import —— WorkBuddy 专家 / 专家团 → Codex 导入器

在 WorkBuddy 里说一句「把 XX 专家导入 Codex」，本脚本即完成
「定位源包 → 双产物转换 → 封装 → 安装 → 校验」全流程。

命令：
  status                                        环境自检
  list                                          列出可导入的专家（已下载的）
  convert <专家名|全部导入> [--out DIR]           只转换（产出 skill + agent.toml）
  pack    <专家名|全部导入> [--out DIR]           转换并封装（单专家→散装 / 专家团→marketplace+plugin）
  install <专家名|全部导入> [--out DIR]           一条龙：转换 → 封装 → 安装到 Codex
  sync    [--check]                             版本比对（源有更新则提示重建）
  clean   [--yes]                               清理本次交付 zip 与 pml 产生的配置备份

专家名支持三种写法：包名 / 专家 ID / 中文名。

约束：源包必须已在本地下载（= 曾在 WorkBuddy 中召唤过）。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pmllib import checks, common as C, convert, discover, install, package  # noqa: E402

BATCH_WORDS = {
    "全部导入", "全部", "所有", "所有专家", "全部专家", "全部专家团",
    "all", "--all", "*", "批量导入", "批量",
}


def is_batch(q: str) -> bool:
    return (q or "").strip().lower() in BATCH_WORDS


def resolve_targets(query: str) -> tuple[list, str | None]:
    """
    返回 (包列表, 错误提示)。批量时返回全部；单个查不到时给出「未下载」提示。
    """
    if is_batch(query):
        pkgs = discover.resolve_all()
        return (pkgs, None) if pkgs else ([], "wb 侧没有已下载的专家包")
    pkg = discover.resolve(query)
    if pkg:
        return [pkg], None
    hint = discover.market_only_hint(query)
    if hint:
        return [], hint
    return [], (f"未找到专家「{query}」。可用 `list` 查看 wb 侧已下载（= 曾召唤过）的专家。"
                f"\n  注意：只有曾在 WorkBuddy 中召唤过、源包已下载到本地的专家才允许导入。")


# ---------------------------------------------------------------- 命令


def cmd_status(_a) -> int:
    C.log("=" * 64)
    C.log(f"{C.GENERATOR_NAME} v{C.GENERATOR_VERSION} · 环境自检")
    C.log("=" * 64)
    C.log(f"  Python            : {sys.version.split()[0]}")
    C.log(f"  WorkBuddy 根目录   : {C.wb_home()}  {'存在' if C.wb_home().exists() else '不存在'}")
    C.log(f"  专家包目录         : {C.wb_experts_dir()}  {'存在' if C.wb_experts_dir().exists() else '不存在'}")
    C.log(f"  市场清单           : {C.wb_manifest_path()}  {'存在' if C.wb_manifest_path().exists() else '不存在'}")
    C.log(f"  Codex 配置目录     : {C.codex_home()}  {'存在' if C.codex_home().exists() else '不存在'}")
    cli = C.codex_cli()
    C.log(f"  Codex CLI         : {cli if cli else '未找到（专家团安装将不可用）'}")
    pkgs = discover.resolve_all()
    C.log(f"  可导入专家包       : {len(pkgs)} 个")
    C.log("")
    if not pkgs:
        C.warn("没有可导入的专家包。请先在 WorkBuddy 中召唤一次目标专家，使其下载到本地。")
    return 0


def cmd_list(_a) -> int:
    C.log(discover.list_available())
    return 0


def _build(pkg, out_root: Path):
    """转换 + 封装，返回 (转换产物目录, 封装结果)。"""
    build_dir = out_root / "_build" / pkg.key
    if build_dir.exists():
        shutil.rmtree(build_dir)
    conv = convert.convert_package(pkg, build_dir)
    packed = package.pack(pkg, build_dir, out_root)
    return build_dir, packed, conv


def _report_convert(pkg, conv) -> None:
    C.log(f"  角色数 {pkg.role_count} → 判定为 {'专家团（plugin）' if pkg.is_team else '单专家（skill）'}")
    C.log(f"  产物 A（skill）: {', '.join(conv['skills'])}")
    C.log(f"  产物 B（agent）: {', '.join(conv['agents'])}")
    if conv["shared"]:
        C.log(f"  共享技能      : {', '.join(conv['shared'])}")
    for n in dict.fromkeys(conv["notes"]):
        C.warn(n)


def cmd_convert(a) -> int:
    pkgs, err = resolve_targets(a.query)
    if err:
        C.fail(err); return 1
    out_root = Path(a.out).resolve()
    for pkg in pkgs:
        C.log(f"\n=== 转换 {pkg.label()} ===")
        _, _, conv = _build(pkg, out_root)
        _report_convert(pkg, conv)
        checks.print_report(out_root / "_build" / pkg.key, checks.verify_package(out_root / "_build" / pkg.key))
    C.log(f"\n产物目录：{out_root}")
    return 0


def cmd_pack(a) -> int:
    pkgs, err = resolve_targets(a.query)
    if err:
        C.fail(err); return 1
    out_root = Path(a.out).resolve()
    for pkg in pkgs:
        C.log(f"\n=== 封装 {pkg.label()} ===")
        _, packed, conv = _build(pkg, out_root)
        _report_convert(pkg, conv)
        C.log(f"  模式：{packed['mode']}")
        C.log(f"  产物：{packed['target']}")
        if packed.get("marketplace"):
            C.log(f"  市场：{packed['marketplace']}")
        checks.print_report(packed["target"], checks.verify_package(packed["target"]))
    C.log(f"\n分发目录：{out_root}（可整体打包 zip 手动分发）")
    return 0


def cmd_install(a) -> int:
    pkgs, err = resolve_targets(a.query)
    if err:
        C.fail(err); return 1
    out_root = Path(a.out).resolve()
    home = C.codex_home()
    C.log("=" * 64)
    C.log(f"{C.GENERATOR_NAME} v{C.GENERATOR_VERSION} · 导入 Codex")
    C.log(f"目标：{len(pkgs)} 个专家包　Codex 目录：{home}")
    if a.dry_run:
        C.log("模式：DRY-RUN（不落盘）")
    C.log("=" * 64)

    results = []
    for i, pkg in enumerate(pkgs, 1):
        C.step(i, len(pkgs), f"{pkg.label()}")
        _, packed, conv = _build(pkg, out_root)
        _report_convert(pkg, conv)

        if pkg.is_team:
            if install.codex_hint() is None and not a.dry_run:
                C.fail("未找到 Codex CLI，无法注册市场与安装插件")
                results.append({"pkg": pkg.key, "ok": False})
                continue
            C.log("  安装：")
            install.install_team(packed["marketplace"], pkg.key, home,
                                 package.DEFAULT_MARKETPLACE,
                                 {pkg.agent_name}, a.dry_run)
        else:
            C.log("  落位：")
            install.install_single(packed["target"], home, a.dry_run)

        rep = checks.verify_package(packed["target"])
        checks.print_report(packed["target"], rep)
        results.append({"pkg": pkg.key, "ok": rep["ok"]})

    C.log("\n" + "=" * 64)
    okn = sum(1 for r in results if r["ok"])
    C.log(f"完成：{okn}/{len(results)} 个通过校验")
    C.log("若装了专家团，请确认 ~/.codex/config.toml 有 [features] multi_agent = true，然后重启 Codex。")
    C.log("=" * 64)
    return 0 if okn == len(results) else 1


def cmd_sync(a) -> int:
    rows = checks.sync_check(Path(a.universe).resolve() if a.universe else None)
    if not rows:
        C.warn("未发现带溯源信息（.pml-origin.json）的已建产物。")
        return 0
    C.log(f"检查 {len(rows)} 个已建产物：")
    outdated = 0
    for r in rows:
        if not r["present"]:
            C.warn(f"{r['package']}: 源包已不在本地（可能被清理），无法比对")
        elif r["outdated"]:
            outdated += 1
            C.warn(f"{r['package']}: 源已更新 → 建议重建"
                   f"（产物建于 {r['built_updatedAt']}，源现为 {r['source_updatedAt']}）")
            if not a.check:
                C.log(f"      重建命令：pml.py install {r['package']}")
        else:
            C.ok(f"{r['package']}: 已是最新")
    C.log(f"\n需要重建：{outdated} 个")
    return 0


def cmd_clean(a) -> int:
    home = Path(a.codex_home).resolve() if a.codex_home else C.codex_home()
    dry = not a.yes
    C.log("=" * 64)
    C.log(f"清理（{'预演，加 --yes 才真正执行' if dry else '执行中'}）")
    C.log("=" * 64)

    zips = [Path(p) for p in (a.zip or [])]
    if a.zip_dir:
        zips += [p for p in Path(a.zip_dir).resolve().glob("*.zip")]
    C.log(f"\n交付 zip：{len(zips)} 个")
    if zips:
        install.clean_zips(zips, dry)
    else:
        C.skip("未指定 --zip/--zip-dir，跳过")

    extra = [Path(p) for p in (a.extra_backup or [])]
    C.log(f"\n配置备份（保留最新 {a.keep_backups} 份）")
    install.clean_backups(home, a.keep_backups, extra, dry)

    if dry:
        C.log("\n以上为预演。确认无误后加 --yes 执行。")
    return 0


# ---------------------------------------------------------------- 入口


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pml.py",
        description="WorkBuddy 专家 / 专家团 → Codex 导入器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='专家名支持包名 / 专家 ID / 中文名；输入「全部导入」则处理全部已下载专家。',
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="环境自检").set_defaults(func=cmd_status)

    sub.add_parser("list", help="列出可导入的专家").set_defaults(func=cmd_list)

    for name, fn, helptext in (
        ("convert", cmd_convert, "只转换，不封装不安装"),
        ("pack", cmd_pack, "转换并封装为可分发的包"),
        ("install", cmd_install, "一条龙：转换 → 封装 → 安装到 Codex"),
    ):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("query", help="专家名（包名 / 专家 ID / 中文名）或「全部导入」")
        sp.add_argument("--out", default="pml-dist", help="输出目录，默认 ./pml-dist")
        if name == "install":
            sp.add_argument("--dry-run", action="store_true", help="只预演，不落盘")
        sp.set_defaults(func=fn)

    sp = sub.add_parser("sync", help="版本比对")
    sp.add_argument("--check", action="store_true", help="只报告，不给重建命令")
    sp.add_argument("--universe", default=None, help="限定扫描目录")
    sp.set_defaults(func=cmd_sync)

    sp = sub.add_parser("clean", help="清理交付 zip 与配置备份")
    sp.add_argument("--yes", action="store_true", help="真正执行（默认只预演）")
    sp.add_argument("--zip", action="append", help="指定要删的 zip（可重复）")
    sp.add_argument("--zip-dir", default=None, help="删除该目录下所有 zip")
    sp.add_argument("--keep-backups", type=int, default=1, help="保留最新几份备份，默认 1")
    sp.add_argument("--extra-backup", action="append",
                    help="额外指定要删的备份（如手工命名的），可重复")
    sp.add_argument("--codex-home", default=None)
    sp.set_defaults(func=cmd_clean)

    return p


def main() -> int:
    C.require_py311()
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
