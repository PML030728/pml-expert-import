# 实现层经验（踩坑记录）

> 记录 `pml-expert-import` 实现与实跑中真实遇到的问题及解法。
> 与 `pipeline.md`（通用逻辑）互补：这里只讲**代码实现**层面的坑。

---

## 1. Codex CLI 路径会变（必须运行时探测）

**现象**：安装过程中 `codex.exe` 突然调用失败，报 `No such file or directory`。
**原因**：Codex 自动更新，`bin/<hash>/codex.exe` 的 hash 目录整个换掉（本次从
`d23520d1e41bfb24` 变为 `faa963e871dd422c`）。
**解法**：`common.codex_cli()` 三级探测，**绝不硬编码**：

1. PATH 中的 `codex` / `codex.exe`
2. `~/.codex/config.toml` 里的 `CODEX_CLI_PATH`（**必须做存在性校验**，它记录的也是旧路径）
3. 扫描 `~/AppData/Local/OpenAI/Codex/bin/*/codex.exe`，取修改时间最新的一个

实测：第 2 步的路径已失效，第 3 步成功兜住。

---

## 2. 备份不能落在「会被扫描」的目录里

**现象**：`~/.codex/skills/` 出现 `xxx.bak.20260926-205745` 之类的残留，
被 Codex 当成候选 skill 扫到。
**原因**：早期 `copy_item()` 把备份写成 `dst.with_name(name + ".bak.<时间戳>")`，
即**原地备份**。而 `skills/`、`agents/` 是 Codex 的扫描目录。
**解法**：`backup(p, backup_root)` 增加集中备份根；对 Codex 内的落位操作统一传
`~/.codex/.pml-backups/`。

```python
codex_home / C.BACKUP_DIRNAME   # ".pml-backups"
```

**通用原则**：向「会被宿主扫描的目录」写入时，副产品（备份、临时文件）一律挪到目录之外。

---

## 3. frontmatter 解析：`\s` 会跨行污染

**现象**：`description` 被污染成 `en: "Nova：Chief orchestrator for ...`。
**原因**：正则写成 `^{key}\s*:\s*(.+?)\s*$`。`\s` **包含换行**，于是
`displayName:`（值为空）的 `\s*` 吃掉了换行，`(.+?)` 把下一行 `en: "Nova"` 当成了值。
**解法**：分隔符一律用 `[ \t]`，并要求值以非空白开头：

```python
re.search(rf"^{key}[ \t]*:[ \t]*(\S.*?)[ \t]*$", fm, re.M)
```

块标量（`key: |`）单独优先匹配。

---

## 4. 共享技能改名不能与角色 skill 撞名

**现象**：`python-fullstack-engineer` 包里，源技能目录是 `09-python全栈工程师`（中文，必须改名）。
若按「用 agent 名兜底」命名，会得到 `python-fullstack-engineer`——**与从角色 md 生成的角色 skill 同名**，
结果共享技能被静默跳过，**内容丢失且不报错**。
**解法**：
1. 改名时传入「已存在的技能名集合」做避让
2. 兜底名用 `<agent_name>-kit`，冲突再加序号
3. **改名后必须同步改写其 `SKILL.md` 的 frontmatter `name`**，否则 skill 仍不加载
4. 顺手补全缺失的 `description`

**教训**：任何「静默跳过」都要改成显式告警——本例若没跑校验，丢文件都发现不了。

---

## 5. TOML 写入必须做「段内插入」

**现象**：给 `config.toml` 开 `multi_agent` 时，若直接追加 `[features]` 段，
会因 **TOML 不允许重复定义 table** 导致整个配置文件解析失败。
**解法**：`ensure_table_key()` —— 段已存在则把键插进段内，不存在才新建段。

本次实跑：被处理环境的 `config.toml` 已有 `[features]`（含 `goals`/`memories`），
插入后三个键共存，解析正常。

---

## 6. 校验脚本不要写成 `python -c`

**现象**：用 `python -c "...正则..."` 做校验，反斜杠被 shell 吞掉（`\s` → `s`），
导致全部 skill 误报 `FAIL`。
**解法**：校验逻辑一律写成 `.py` 文件再执行。这条对 Bash/Git Bash 环境尤其重要。

---

## 7. 打包 zip 要强制 UTF-8 文件名标志位

否则 Windows 解压含中文名的条目会乱码：

```python
zi = zipfile.ZipInfo(arcname)
zi.flag_bits |= 0x800
```

---

## 8. 告警要去噪

**现象**：工具名审计把「`TeamCreate` 在 Codex 中**不存在**，禁止调用」这类
**我们自己写的说明文字**也报成「残留告警」，每次导入都刷屏。
**解法**：审计时排除否定语境的整行（含「不存在 / 禁止 / 无此 / 不要调用」等词）。

---

## 9. 备份与删除的安全边界

- 备份命名统一用 `config.toml.bak.<YYYYMMDD>-<HHMMSS>`，**便于识别归属**：
  `clean` 只清理严格匹配该格式的文件，用户手工命名的历史备份（`config.toml.bak`、
  `config.toml.bak.20260906`）一律不碰。
- 手工命名的本次备份需通过 `--extra-backup` **显式指定**才会被清理。
- `clean` 默认 dry-run，**必须加 `--yes` 才真正删除**。
