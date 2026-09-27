# WorkBuddy 专家 / 专家团 → Codex 导入逻辑

> 版本 v1.0 ｜ 2026-09-26
> 性质：六阶段流水线通用方法论 + 设计规则集 + 踩坑清单
> 适用范围：把 WorkBuddy / CodeBuddy 专家中心的专家包，迁到 OpenAI Codex 上可用

---

## 〇、总览：六阶段流水线

```
WorkBuddy 专家包
   │
   ├─ P0 定位      找出包在哪（ID → 包名 → 目录）
   ├─ P1 核验      22 个文件一个不少？结构对得上？
   ├─ P2 分流      expertType=agent 还是 team？决定封装形态
   ├─ P3 转换      角色 md → skill + agent toml；工具名改写
   ├─ P4 封装      单专家=散装；专家团=plugin（marketplace 分发）
   ├─ P5 安装      marketplace → plugin → 落位 agents → 开 multi_agent
   └─ P6 验证      名称一致性 / TOML 可解析 / 脚本幂等 / Codex 可见性
   │
Codex 中可用
```

**两条主线的根本差异**：

| | 单专家（agent 型） | 专家团（team 型） |
|---|---|---|
| 原始形态 | 1 个角色 md + 1 个 skill | N 个角色 md + 1 个 skill + 头像组 |
| Codex 载体 | Skill + Agent toml | **Plugin**（内含 N×(Skill + Agent toml)） |
| 分发方式 | 散装文件或轻量 plugin | marketplace 注册 + plugin 安装 |
| 核心难点 | 命名规范、调用入口 | 编排协议换算、plugin 装不了 agent |

---

## P0 · 定位：先找到包

WorkBuddy 专家包的路径规律（`~` = `C:/Users/<用户>/.workbuddy`）：

| 用途 | 路径 |
|---|---|
| 专家 ID → 包名映射 | `~/app/cache/experts/expert-bundle-map.json` |
| 市场全量清单（447 条） | `~/app/cache/experts/manifest.json` |
| 已下载的专家包 | `~/plugins/marketplaces/experts/plugins/<pkg>/` |
| 用户自建专家 | `~/plugins/marketplaces/my-experts/plugins/<pkg>/` |

**操作顺序**：
1. 读 `expert-bundle-map.json` 拿 ID → 包名映射；找不到就用中文名去 `manifest.json` 里搜 `displayName.zh`
2. 从 `manifest.json` 条目里取关键字段：`expertType`（**决定分流**）、`agentName`、`plugin`、`members[]`、`promptFile`
3. 确认本地是否已下载（`plugins/marketplaces/experts/plugins/<pkg>/` 是否存在）——**没下载说明只是"召唤"过但未落盘**

**坑**：`manifest.json` 有 1.1 MB，**不要直接 Read**（超 256 KB 上限），用 Python 解析或 Grep。

```python
import json
d = json.load(open('manifest.json', encoding='utf-8'))
for e in d['experts']:
    if '关键词' in json.dumps(e, ensure_ascii=False):
        print(e['id'], e['expertType'], e.get('plugin'))
```

---

## P1 · 核验：确认包完整

标准包结构（两种类型共用骨架）：

```
<pkg>/
├── .codebuddy-plugin/plugin.json      # 声明 agents / skills / teamInfo / members
├── agents/*.md                        # ★ 角色配置（N 个）
├── skills/<技能名>/SKILL.md            # ★ 配套技能
│   ├── references/                    #   深度资料
│   ├── scripts/                       #   确定性脚本
│   └── templates/                     #   模板
├── avatars/*.png                      # 头像
├── README.md  .downloaded_at
```

**核验动作**：`find <pkg> -type f` 逐项对照上表，记录每个文件的字节数，与 `manifest.json` 条目交叉确认。

实做记录（供参照规模）：
- `python-fullstack-engineer`：7 个文件，1 角色 + 1 skill
- `ai-data-copilot`：22 个文件，6 角色 + 1 skill（含 3 references + 1 script + 1 template）+ 7 头像（约 11 MB）

---

## P2 · 分流：类型决定封装形态

读 `plugin.json` 的 `expertType`：

| expertType | 含义 | Codex 封装 |
|---|---|---|
| `agent` | 单专家 | Skill + Agent toml（散装，或做轻量 plugin） |
| `team` | 专家团 | **Plugin** 封装全部成员 |

判定后确定三件事：
1. **有几个 agent toml**（= `agents/` 下 md 的数量，team 型还要看 `teamInfo.leadAgent`）
2. **主理人怎么处理**（team 型特有，见 P3.3）
3. **是否走 marketplace 分发**（team 型建议走）

---

## P3 · 转换：角色 md → Codex 双载体

### 3.1 为什么必须双载体

| 载体 | 是什么 | 不可替代性 |
|---|---|---|
| **Skill**（`skills/<name>/SKILL.md`） | 专家的知识与方法论 | 可被 `$` 调用/隐式触发，带渐进加载 |
| **Agent**（`agents/<name>.toml`） | 专家的可并行执行实例 | **Codex 的 subagent 只能由 toml 定义，skill 无法被 spawn** |

只做 skill → 丢掉并行能力；只做 toml → 丢掉按需加载与自然语言触发。**两者都要**。

### 3.2 字段映射表

| WorkBuddy 字段 | Codex 落点 | 处理方式 |
|---|---|---|
| `name` | skill 目录名 + `SKILL.md` 的 `name` | **必须 ASCII 化**为 kebab-case，两者严格一致 |
| `description` | skill 的 `description` | 需**重写**：触发词前置 + 补"不适用"边界 |
| `displayName` / `profession` | plugin.json 的 `interface` 或 agent 的 `description` | 中文显示名保留在这里 |
| `maxTurns` | —— | Codex 无对应字段，直接丢弃 |
| `skills: [xxx]` | —— | 由 `~/.codex/skills/` 目录自动发现取代，无需声明 |
| 正文 | `SKILL.md` 正文 **+** agent toml 的 `developer_instructions` | 两份内联，互不依赖 |
| `plugin.json`（WorkBuddy 格式） | `.codex-plugin/plugin.json`（Codex 格式） | 字段体系完全不同，需重写 |
| `teamInfo` | plugin README + 编排 skill 的成员表 | 编制信息转成人类可读表格 |
| `members[]` | `agents/*.toml` + plugin 的 `interface` | 每个成员一个 toml |
| `avatars/*.png` | —— | **Codex 无 agent 头像字段**，仅可作 skill 的 `openai.yaml` 图标 |
| `skills/<中文名>/` | `skills/<kebab-case>/` | 目录改名 + 同步改写所有引用路径 |

### 3.3 工具名换算（team 型必做）

WorkBuddy 的团队协作依赖专有三件套，Codex 有对等能力但工具名不同：

| WorkBuddy | Codex Subagents 协议 | 备注 |
|---|---|---|
| `TeamCreate` | **无对应** | 父 session 本身就是编排者，没有"团队容器"概念 |
| `Agent` spawn(name, subagent_type) | `spawn_agent("<agent-name>")` | Codex 只用单一 `name`，无 `subagent_type` |
| `SendMessage` 回传 | `report_agent_job_result` | 成员结束时返回结构化结果 |
| 主理人等待成员 | `wait_agent` | 回收产出 |
| 主理人追问成员 | `send_input` | 对已派发成员二次下发 |

**改写要点**：
- 逐条替换工具名，**并在主理人配置里显式写明「`TeamCreate`/`SendMessage`/`subagent_type` 在 Codex 中不存在，禁止调用」**——否则模型会沿用旧习惯去调不存在的工具
- 原包每个成员 md 末尾的「SendMessage 回传要求」段落，改写为「结果回报约定（Codex Subagents）」，强调**必须回传完整原文**（主理人依赖它做后续编排）
- 若 `max_depth = 1`（默认），**主理人不能 spawn 主理人**——主理人应由主 session 亲自扮演，其指令内联进编排 skill 与项目 AGENTS.md

### 3.4 命名规范（硬约束）

| 对象 | 规则 | 违规后果 |
|---|---|---|
| Skill `name` | 小写字母+数字+连字符，**必须等于父目录名** | skill 不加载 |
| Plugin `name` | kebab-case，且与**目录名、marketplace 条目名三者一致** | 安装报错 |
| Agent `name` | 建议与文件名一致，用于 `spawn_agent` 定位 | 调度失败 |
| 技能目录 | 中文名（如 `09-python全栈工程师`）一律 ASCII 化 | 部分工具路径异常 |

---

## P4 · 封装：单专家散装 / 专家团 plugin

### 4.1 Codex 插件的边界（官方规范）

```
<plugin>/
├── .codex-plugin/plugin.json    # 必需：name(kebab-case) / version / description
│                                # 可选组件：skills / mcpServers / apps / hooks / interface
├── skills/                      # 可打包 ✓
├── .mcp.json  .app.json         # 可打包 ✓
├── hooks/hooks.json             # 可打包 ✓
├── agents/                      # ✗ 不可打包！
├── scripts/  assets/  docs/
└── README.md
```

**三条致命约束**：
1. **plugin 没有 `agents` 字段** —— agent toml 只能「作为松散文件与插件并存投递」（官方原话），必须由安装脚本额外落位
2. **plugin 没有 `commands` 字段** —— 且 `~/.codex/prompts/` 已被官方弃用，调用入口一律走 skill
3. **`max_depth` 默认 1** —— 子 Agent 不能再派子 Agent

### 4.2 专家团的分发结构

```
<marketplace>/
├── .agents/plugins/marketplace.json     # 市场清单
└── plugins/<plugin-name>/
    ├── .codex-plugin/plugin.json        # 只放这一个 json，别塞别的清单
    ├── skills/                          # 专家能力层（N 个成员 + 共享引擎 + 编排总纲）
    ├── agents/                          # 专家执行层（N 个 toml，需落位）
    ├── hooks/hooks.example.json         # 默认不启用（实验特性）
    ├── scripts/
    │   ├── install-agents.py            # 把 agents/ 落位到 ~/.codex/agents/
    │   ├── enable-multiagent.py         # 合并 config.toml 开启多 Agent
    │   └── check-agents.py              # 就位检测（供启动钩子调用）
    ├── assets/  docs/  README.md
```

`marketplace.json` 要点：`source.path` 相对 **marketplace 根目录**（不是 json 所在目录）；条目 `name` 与 plugin 目录名、manifest `name` 三者必须一致。

---

## P5 · 安装：五步落位

```bash
# ① 备份配置
cp ~/.codex/config.toml ~/.codex/config.toml.bak.before-<name>

# ② 市场源放到惯例位置（与既有 local 市场同级）
cp -r <marketplace-dir> ~/.codex/plugins/local/<name>-marketplace

# ③ 注册市场
codex plugin marketplace add "~/.codex/plugins/local/<name>-marketplace"
codex plugin marketplace list        # 确认已登记

# ④ 安装插件
codex plugin add <plugin>@<marketplace>
codex plugin list                    # 应显示 installed, enabled

# ⑤ 团员落位 + 开启多 Agent
PLUGIN=~/.codex/plugins/cache/<marketplace>/<plugin>/<version>
python $PLUGIN/scripts/install-agents.py
python $PLUGIN/scripts/enable-multiagent.py

# 最后重启 Codex
```

**Codex CLI 位置提示**：不一定在 PATH 里。Windows 桌面版通常在
`C:\Users\<用户>\AppData\Local\OpenAI\Codex\bin\<hash>\codex.exe`，
可用 `~/.codex/config.toml` 里的 `CODEX_CLI_PATH` 反查。

**落位机制说明**：agent toml 必须复制到 `~/.codex/agents/`，Codex 启动时自动扫描该目录。这也是为什么必须有 `install-agents.py`。

---

## P6 · 验证：六项检查

| # | 检查项 | 方法 | 通过标准 |
|---|---|---|---|
| 1 | 名称三方一致 | 比对 marketplace 条目 / plugin 目录 / manifest name | 完全相同 |
| 2 | Skill 合规 | 校验每个 `name` == 父目录名 && kebab-case && 有 description | 全部通过 |
| 3 | Agent 可解析 | `tomllib.load()` 每个 toml | 三项必填字段齐全 |
| 4 | JSON 合法 | `json.load()` 每个 json | 无异常 |
| 5 | 脚本幂等 | 连跑两遍 install 脚本 | 第二遍全跳过 |
| 6 | Codex 可见 | `codex plugin list` | `installed, enabled` |

---

## 附录 A · 踩坑清单（全部实做遇到）

| # | 坑 | 后果 | 对策 |
|---|---|---|---|
| 1 | **中文技能目录名** | Codex skill 不加载 | ASCII 化 + 同步改所有引用 |
| 2 | **TOML 重复定义 table** | 整个 config.toml 解析失败 | 段已存在则**插进段内**，不新增第二段 |
| 3 | **漏跑落位脚本** | **静默退化为单人模式，不报错** | README + 脚本输出双重提示；可选启动钩子 |
| 4 | **plugin 装不了 agent** | 团队无法并行 | 提供 `install-agents.py` 单独落位 |
| 5 | `max_depth=1` | 主理人无法 spawn 主理人 | 主理人由主 session 亲自扮演 |
| 6 | `shutil.copy2` 备份目录 | Windows 抛 `PermissionError` | 目录一律用 `copytree` |
| 7 | 备份文件堆积 | 重复安装产生多份 .bak | 先比内容一致则跳过（幂等） |
| 8 | 平台专属 API 废弃 | 脚本运行报错 | 实例：`pd.api.types.is_categorical_dtype`（pandas 2.x 废弃）→ `isinstance(dtype, pd.CategoricalDtype)` |
| 9 | 模板脚本硬编码 `python3` | Windows 上找不到命令 | 自动探测 `python3` / `python` |
| 10 | `python -c` 传正则 | 反斜杠被 shell 吞掉，校验假 FAIL | **校验逻辑一律写成 .py 文件执行** |
| 11 | 原始平台清单放错位置 | 可能被误扫 | 移出 `.codex-plugin/`，放 `docs/` |
| 12 | skill description 过长 | 启动列表超 8000 字符被截断 | 触发词前置、控制数量（实测 7 个 skill 共 763 字符） |

---

## 附录 B · 交付物清单模板

```
<name>-marketplace/                     # 专家团（单专家则为散装目录）
├── README-安装说明.md
├── 架构设计.md                          # 可选，说明设计取舍
├── .agents/plugins/marketplace.json
└── plugins/<plugin>/
    ├── .codex-plugin/plugin.json
    ├── skills/…  agents/…  scripts/…  hooks/…  assets/…
    └── README.md
```

配套脚本（每个专家团必备）：
- `install-agents.py` —— 团员落位（幂等 + 备份 + `--dry-run` / `--list`）
- `enable-multiagent.py` —— 合并 config.toml（段内插入 + `--dry-run` + 自动备份）
- `check-agents.py` —— 就位检测（**任何情况 exit 0**，不打断会话）

---

## 附录 C · 两次实做对照

| 项 | python-fullstack-engineer | ai-data-copilot |
|---|---|---|
| 类型 | agent（单专家） | team（6 人） |
| 原始文件数 | 7 | 22 |
| Codex 载体 | Skill + 1 agent toml | Plugin + 7 skill + 6 agent toml |
| 团队协议换算 | 不涉及 | TeamCreate/SendMessage/spawn 全量改写 |
| 主理人 | —— | 主 session 亲自扮演，不 spawn |
| 产出体积 | 622 KB（含原始包） | 3.24 MB（插件包） |
| 特有坑 | 中文技能目录名、skill 名规范 | plugin 装不了 agent、max_depth 限制 |

---

## 附录 E · 设计规则集

以下是本方案遵循的设计规则，优先级高于本文档其余部分的描述。

| # | 规则 | 要点 |
|---|---|---|
| E1 | **封装判定** | 单专家（1 个角色）→ 封装为 skill；专家团（多个角色）→ 封装为 plugin。判定依据是 **`agents` 数组长度 / `expertType`**，**不是** `skills` 数组长度（`ai-data-copilot` 的 `skills` 只有 1 个却有 6 个角色，用它判定必然误判） |
| E2 | **主理人** | 由主 session 亲自担任 —— 这正是 Codex 原生 `max_depth=1` 的正确用法（root 可直接 spawn 直接子级），不做额外 spawn |
| E3 | **生成式策略** | **WorkBuddy 原始包为唯一真相来源**；skill 与 agent.toml **都是产物**，二者**禁止互为源**，也不得由对方生成 |
| E4 | **产物自包含** | 每份产物各自完整可独立使用，不互相引用、不依赖对方存在 |
| E5 | **打包结构** | 一个**聚合 marketplace** + 各专家团**独立 plugin source**；源与产物分离，原始包不携带生成产物 |
| E6 | **调用入口** | 采用 Codex 官方规范：plugin 用 `@名称`（或 `@名称/技能名`），skill 用 `$技能名`。**Codex 无 `plugin:skill` 前缀语法** |
| E7 | **版本同步** | wb 侧升级后需同步到 codex。**hook 只做本地轻量提示**，实际同步走**显式命令**；不依赖实验性 hooks 做全自动 |
| E8 | **清理** | 仅清理**本次生成的交付 zip** 与**本次导入产生的备份**；**不碰** wb 专家包本体、用户自建的历史备份 |

---
