# 新增 Skill 的规范

本仓库每加一个 Skill，目录长这样：

```
skills/
└── <skill-name>/                  # 目录名 = frontmatter 的 name，kebab-case
    ├── SKILL.md                    # 必填。入口：触发词、输入、流程、故障处理
    ├── scripts/                    # 可选。确定性脚本，放这里而不是让 agent 每次重写
    │   └── <tool>.py
    ├── references/                 # 可选。深度资料，按需读，不要塞进 SKILL.md
    │   └── <topic>.md
    └── assets/                     # 可选。模板、图标等静态资源
```

---

## 一、SKILL.md 写法

### frontmatter（只有两个必填字段）

```yaml
---
name: my-skill-name          # 必须 = 目录名，kebab-case
description: |
  一句话说清这个 skill 干什么、什么情况下该用它。
  必须包含具体触发词（中文 + 英文），否则 agent 不会主动加载它。
  同时写明 near-miss：哪些相似但不该用本 skill 的情况。
---
```

**`description` 是唯一决定「agent 会不会想起它」的字段**，比 SKILL.md 正文重要得多。

好的写法：

```yaml
description: |
  Download WeChat Channels (微信视频号) videos to a local file by resolving a share
  link through the Yuanbao parse API. Load this skill whenever the user provides a
  视频号 share link or asks to 下载/保存/转存/导出 视频号 视频, "视频号去水印".
  Do NOT use it for 公众号 articles or 小程序 packages.
```

坏的写法：

```yaml
description: |
  A helper for downloading videos.      # 太泛，agent 无法判断该不该用
```

### 正文结构

```markdown
# 标题

一句话说明这个 skill 解决什么问题。

## Inputs to collect      # 调用前必须先确认的输入，缺哪项问哪项
## Procedure              # 编号步骤，一步一个动作
## Output contract        # 产出物长什么样、脚本 stdout 的关键行
## Failure handling       # 现象 → 原因 → 处置 的表格
## Examples               # 真实输入输出示例
## 深入资料               # 指向 references/
```

---

## 二、三条硬规则

### 1. 不要写死绝对路径

写死的路径在别人的机器上必然失效 —— 这是本仓库踩过的真实坑。

```markdown
❌ 设 `SCRIPT=/Users/<你的用户名>/.minimax/skills/my-skill/scripts/x.py`
✅ 设 `SCRIPT="${DATA_DIR:-$HOME/.minimax}/skills/my-skill/scripts/x.py"`
```

更稳的写法是让 agent 从运行时拿真实路径：

```
用 skill({ name: "my-skill" }) 返回的 Location: 头作为 SKILL_DIR
```

`DATA_DIR` 在某些 profile 下不是 `~/.minimax`，所以**以 `Location:` 为准**。

同理，`references/implementation.md` 里也不要出现 `cd /Users/xxx/某个项目目录`，
改成 `cd <你的工作目录>`。

### 2. 确定性工作下沉到脚本

能被脚本确定完成的事（加密、解析、格式转换、校验），写成 `scripts/` 里的脚本，
**不要让每个 agent 每次都重新实现一遍**。agent 加载 skill 后直接调用脚本，
既快又不会每次生成不同结果。

脚本要求：

- 只从环境变量或参数读凭据，**零硬编码、零打印凭据**
- 有 `--help`
- 失败时给明确的中文错误信息，并说明下一步怎么办
- 关键步骤打印可核验的证据（如「✅ 可播放 10.2MB 124.5s」），让 agent 不用猜

### 3. 深度资料放 references/，别塞正文

SKILL.md 正文控制在 **500 行以内**（lint 硬限制）。详细实现、协议分析、排查记录
放 `references/`，在正文里用链接指过去，让 agent 按需读。

---

## 三、脚本用到的技术约定

- **Python**：只用标准库 + `requests`，不要引入重量级依赖
- **凭据**：环境变量或 `--cookie-file` / `--token-file` 参数，**绝不硬编码**
- **输出目录**：`-o/--outdir` 参数，默认当前目录
- **可移植性**：不依赖特定项目目录结构，任意 cwd 都能跑
- **跨平台**：脚本本身跨平台，平台差异（取 Cookie、chmod）写进 SKILL.md 的平台说明段

---

## 四、Lint 与验收

```bash
# 官方 lint
node ~/.minimax/.builtin-skills/skill-creator/scripts/lint-skill.js skills/<skill-name>/
```

检查项包括：frontmatter 可解析、`name` 是合法 kebab-case 且与目录名一致、
description 含触发提示、无禁用 frontmatter 键、正文不超 500 行、
`references/*.md` 链接全部可解析。

**提交前清单：**

- [ ] `node ~/.minimax/.builtin-skills/skill-creator/scripts/lint-skill.js skills/<skill-name>/` 全绿
- [ ] 目录内无 `__pycache__`、`.DS_Store` 等杂物（已由 `.gitignore` 兜底）
- [ ] `grep -rn "/Users/" skills/<skill-name>/` 无输出（无写死的个人路径）
- [ ] `grep -rniE "(password|token|cookie)\s*=\s*['\"][^'\"]+" skills/<skill-name>/` 无输出（无硬编码凭据）
- [ ] 脚本 `--help` 能正常输出
- [ ] 至少一个链接从头到尾真跑通一遍，产物能被 `ffprobe` 解析
- [ ] README.md 的 Skill 表格里加上新条目
- [ ] commit message 写清楚这个 skill 解决什么问题

---

## 五、写 Skill 时的推荐工作流

1. **先手动做一遍**：把任务真跑通，记下每一步的实际命令和输出。
2. **写成脚本**：把确定性的部分固化成 `scripts/*.py`。
3. **写 SKILL.md**：把你的真实操作过程写成编号步骤，把踩过的坑写进 Failure handling。
4. **跑 lint + 实跑验证**。
5. **提交**。

> 想要更系统的指导，可以用内置的 `skill-creator` skill 走一遍它的流程；
> 它比手写更稳，尤其是 `description` 的触发词设计和评测环节。
