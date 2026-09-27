---
name: pml-expert-import
description: 把 WorkBuddy 的专家或专家团一键导入 Codex（CLI/IDE/App）。当用户说「把 XX 专家导入 Codex」「导入专家团」「pml 导入」「全部导入到 Codex」时触发。覆盖定位源包、双产物转换（skill + agent.toml）、封装成 plugin、安装到 Codex、清理与版本同步全流程。仅适用于源包已在本地下载的专家；不适用于导出到 Claude Code / Cursor 等其他平台，也不适用于编写新专家。
version: 1.0.0
category: 开发编程
platforms: WorkBuddy, CodeBuddy
metadata:
  requires: "python>=3.11"
  tags: WorkBuddy, Codex, 专家迁移, skill 转换
---

# pml-expert-import · WorkBuddy 专家 → Codex 导入器

把 WorkBuddy 专家中心的**专家**或**专家团**，按其原生扩展机制导入到 Codex 使用。

**执行层是 `scripts/pml.py`（纯标准库，零依赖），本文件只负责编排与调度。**
不要在对话里手工重写转换逻辑——所有规则都已在代码里固化，直接调脚本。

---

## 一、先决条件（务必先确认）

| 条件 | 说明 | 不满足时的表现 |
|---|---|---|
| 源包已下载到本地 | **只有曾在 WorkBuddy 中召唤过的专家才可导入** | 脚本会明确报「市场里有、但本地未下载」，并提示先召唤一次 |
| Python ≥ 3.11 | `tomllib` 依赖 | 脚本会告警并降级部分校验 |
| Codex 已安装 | 仅专家团需要（要调 codex CLI） | 单专家导入不受影响 |

> 遇到「未下载」提示时，**不要绕过**——请告知用户先在 WorkBuddy 里召唤该专家，
> 待其下载到 `~/.workbuddy/plugins/marketplaces/experts/plugins/` 后再执行导入。

---

## 二、标准执行流程

### 第 1 步 · 环境自检（首次执行必做）

```bash
python scripts/pml.py status
```

确认 wb 根目录、Codex 目录、Codex CLI 均能识别。若 CLI 显示未找到，专家团导入将不可用。

### 第 2 步 · 查看可导入的专家

```bash
python scripts/pml.py list
```

输出每个专家包的**中文名、类型（单专家/专家团）、角色数、别名**。

### 第 3 步 · 执行导入

```bash
# 导入指定专家（支持包名 / 专家 ID / 中文名 三种写法）
python scripts/pml.py install "智数分析专家团"
python scripts/pml.py install ai-data-copilot
python scripts/pml.py install AiDataCopilot

# 批量：导入全部已下载的专家
python scripts/pml.py install "全部导入"
```

**批量模式的识别**：脚本把 `全部导入` / `全部` / `所有` / `批量` / `all` 视为批量指令；
其余一切输入都按「单个专家名」解析。用户说「全部导入」「都导一下」时用批量模式。

### 第 4 步 · 汇报结果

脚本会打印：判定类型（单专家→skill / 专家团→plugin）、产物清单、安装步骤、校验结果。
**把校验是否通过、以及「重启 Codex 生效」明确告诉用户。**

---

## 三、按专家类型的分流（脚本自动判定，此处供理解）

| 角色数 | 判定 | 产物形态 | 安装方式 |
|---|---|---|---|
| 1 | 单专家 | 散装：`skills/<name>/` + `agents/<name>.toml` | 直接落位到 `~/.codex/` |
| ≥2 | 专家团 | marketplace + plugin（含 skills/ agents/ 落位脚本） | 注册市场 → 装插件 → 落位团员 |

判定依据是**角色数（`agents` 数组长度 / `expertType`）**，不是源包 `skills` 数组长度——
源包的 `skills` 只记共享技能，用它判定必然误判。

---

## 四、前提约束：只允许导入「已下载」的专家

**这是硬约束，不可绕过。** 原因：转换的唯一真相来源是本地源包，没有源包就没有产物。

脚本在三种情形下的行为：

1. **查到且已下载** → 正常导入
2. **市场清单里有、本地没有** → 报错并提示「请先在 WorkBuddy 中召唤一次该专家」
3. **市场里也查不到** → 报错并建议用 `list` 查看可用清单

---

## 五、其他命令

```bash
# 只转换不安装（产出到 ./pml-dist，便于检查）
python scripts/pml.py convert "Python 全栈工程师" --out ./out

# 转换 + 封装成可分发的 zip 目录（不动 Codex）
python scripts/pml.py pack "智数分析专家团" --out ./dist

# 版本比对：源更新过则提示重建
python scripts/pml.py sync

# 清理（默认预演，加 --yes 才执行）
python scripts/pml.py clean --zip-dir ./dist --keep-backups 1
```

`clean` **只处理**两类东西：
- 本工具产出的交付 zip
- **pml 命名格式**（`config.toml.bak.<YYYYMMDD>-<HHMMSS>`）的 Codex 配置备份，保留最新 N 份

**绝不触碰**：WorkBuddy 专家包本体、用户手工命名的历史备份（如 `config.toml.bak`）。

---

## 六、常见问题处置

| 现象 | 原因 | 处置 |
|---|---|---|
| 报「本地尚未下载」 | 该专家只被浏览过、未召唤 | 让用户先在 WorkBuddy 召唤一次，再重跑 |
| 报「未找到 Codex CLI」 | CLI 不在 PATH 且无法反查 | 专家团导入不可用；单专家仍可导入 |
| 校验报「name 与目录名不一致」 | 源技能含中文目录名 | 脚本已自动改名并对齐 frontmatter；若仍报错请贴出完整输出 |
| 导入后团队不并行 | `multi_agent` 未开或团员未落位 | 跑 `status` 确认；`config.toml` 需 `[features] multi_agent = true` |
| `sync` 报「源包已不在本地」 | 源包被清理了 | 重新在 WorkBuddy 召唤该专家，再重跑导入 |

---

## 七、目录说明

```
pml-expert-import/
├── SKILL.md              # 本文件（编排层）
├── scripts/
│   ├── pml.py            # 唯一 CLI 入口
│   └── pmllib/           # 实现层（转换规则全在这里，勿在对话中手工重写）
│       ├── common.py     #   路径探测 / 备份 / 幂等 / TOML 安全写入
│       ├── discover.py   #   源发现与专家名解析
│       ├── convert.py    #   双产物生成（E3 核心）
│       ├── package.py    #   封装（单专家散装 / 专家团 plugin+marketplace）
│       ├── install.py    #   安装到 Codex / 清理
│       └── checks.py     #   规范校验 / 版本同步比对
├── references/
│   └── pipeline.md       # 完整导入逻辑与规则集（六阶段 + 规则 + 坑清单）
└── assets/templates/     # 静态骨架
```

**本 skill 可整包上传到其他机器**：零第三方依赖、零绝对路径、解释器运行时探测。
放到 `~/.workbuddy/skills/pml-expert-import/` 即可使用。
