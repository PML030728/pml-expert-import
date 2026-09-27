# pml-expert-import

> 把 WorkBuddy / CodeBuddy 专家中心的**专家**或**专家团**，一键导入到 **OpenAI Codex** 使用。
> Import WorkBuddy experts / expert teams into OpenAI Codex in one command.

在 WorkBuddy 里说一句「把 XX 专家导入 Codex」，即自动完成：
**定位源包 → 双产物转换 → 封装 → 安装 → 校验**全流程。

---

## 为什么需要它

WorkBuddy 的专家包和 Codex 的扩展机制是两套体系，手工迁移要踩一堆坑：

- Codex 的 plugin **装不了** agent 定义（`agents/*.toml` 只能作为松散文件并存投递）
- Codex 的 skill 名必须 kebab-case 且与目录名严格一致，而专家包常见中文技能目录名
- WorkBuddy 的团队协作依赖 `TeamCreate` / `SendMessage` 等专有工具，Codex 里不存在，需换算成 Subagents 协议
- Codex 的 `config.toml` 不允许重复定义 table，直接追加配置段会让整个文件解析失败
- Codex 自动更新会更换 CLI 的 hash 目录，硬编码路径必失效

本工具把这些坑全部固化成了代码。

---

## 安装

```bash
# 1) 下载并解压到你的 skills 目录
#    Codex 用户级:  ~/.codex/skills/
#    WorkBuddy:     ~/.workbuddy/skills/
#    也可放项目级:  .agents/skills/

# 2) 验证
python <skills目录>/pml-expert-import/scripts/pml.py status
```

**依赖**：仅需 Python ≥ 3.11（用到 `tomllib`）。**零第三方依赖**，无绝对路径硬编码，可直接跨机器使用。

---

## 使用

```bash
# 环境自检
python scripts/pml.py status

# 查看可导入的专家（含中文名 / 类型 / 角色数）
python scripts/pml.py list

# 导入指定专家（包名 / 专家 ID / 中文名 三种写法都认）
python scripts/pml.py install "Python 全栈工程师"
python scripts/pml.py install ai-data-copilot

# 批量导入全部已下载的专家
python scripts/pml.py install "全部导入"

# 只转换，不安装（产出到 ./pml-dist 便于检查）
python scripts/pml.py convert "Python 全栈工程师" --out ./out

# 版本比对：源包更新过则提示重建
python scripts/pml.py sync

# 清理交付 zip 与配置备份（默认预演，加 --yes 才执行）
python scripts/pml.py clean --zip-dir ./dist
```

**批量触发词**：`全部导入` / `全部` / `所有` / `批量` / `all`。

---

## 工作原理

### 一个专家 = 双载体

```
WorkBuddy 原始包（唯一真相来源）
  │
  ├── agents/<name>.md ──┬──▶ skills/<name>/SKILL.md   产物 A（知识层）
  │                      └──▶ agents/<name>.toml       产物 B（执行层）
  └── skills/<共享技能>/ ────▶ skills/<共享技能>/         原样搬运 + 命名规范化
```

**为什么必须双载体**：Codex 的 subagent 只能由 toml 定义，**skill 无法被 spawn**；
而 toml 又无法按需加载。所以要保并行能力 + 按需触发，两者缺一不可。
两条产出线**各自直接读源**，互不读取对方输出。

### 按角色数分流

| 角色数 | 判定 | 产物形态 |
|---|---|---|
| 1 | 单专家 | 散装 skill + agent toml |
| ≥2 | 专家团 | 聚合 marketplace + 独立 plugin source |

判定依据是**角色数**（`agents` 数组长度 / `expertType`），不是源包 `skills` 数组长度。

### 团队协作协议的换算

| WorkBuddy | Codex Subagents |
|---|---|
| `TeamCreate` | 无需（父 session 本身即编排者） |
| `Agent` spawn | `spawn_agent("<name>")` |
| `SendMessage` | `report_agent_job_result` |
| 等待 / 追问 | `wait_agent` / `send_input` |

---

## 调用导入后的产物

Codex 官方规范：

| 对象 | 调用方式 |
|---|---|
| Plugin | `@plugin-name`（注入整个插件上下文） |
| Plugin 内的 Skill | `@plugin-name/skill-name` |
| Skill | `$skill-name` |
| 任意 | 自然语言描述，按 `description` 隐式触发 |

> ⚠️ Codex **没有** `plugin:skill` 这种前缀语法（那是 Claude Code 的规则）。

---

## 重要前提

**源包必须已在本地下载**，即只有曾在 WorkBuddy 中**召唤过**的专家才可导入。
不满足时工具会明确提示，不会静默失败。

原因：转换的唯一真相来源是本地源包，没有源包就没有产物。

---

## 目录结构

```
pml-expert-import/
├── SKILL.md                          # 编排层：触发条件与调度步骤
├── README.md                         # 本文件
├── scripts/
│   ├── pml.py                        # 唯一 CLI 入口
│   └── pmllib/                       # 实现层（转换规则全在这里）
│       ├── common.py                 #   路径探测 / 备份 / 幂等 / TOML 安全写入
│       ├── discover.py               #   源发现与专家名解析
│       ├── convert.py                #   双产物生成
│       ├── package.py                #   封装（散装 / plugin + marketplace）
│       ├── install.py                #   安装到 Codex / 清理
│       └── checks.py                 #   规范校验 / 版本同步比对
├── references/
│   ├── pipeline.md                   # 完整导入逻辑（六阶段 + 设计规则 + 踩坑清单）
│   └── implementation-notes.md       # 实现层经验（9 条真实踩坑与解法）
└── assets/templates/                 # 静态骨架
```

---

## 安全设计

- **只读源包**：全程不修改 WorkBuddy 专家包
- **幂等**：内容一致即跳过，重复执行无副作用
- **改前备份**：覆盖前自动备份，且集中存放到 `~/.codex/.pml-backups/`（避免污染被扫描的 skills 目录）
- **清理有边界**：只清本工具产出的 zip 与**本工具命名格式**的配置备份，**绝不触碰**用户手工命名的历史备份与源包本体
- **默认预演**：`clean` 不加 `--yes` 只列清单不执行

---

## License

MIT License · Copyright (c) 2026 pml-expert-import contributors

Permission is hereby granted, free of charge, to any person obtaining a copy of this software
and associated documentation files (the "Software"), to deal in the Software without restriction,
including without limitation the rights to use, copy, modify, merge, publish, distribute,
sublicense, and/or sell copies of the Software, subject to the condition that the above
copyright notice and this permission notice be included in all copies or substantial portions
of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
