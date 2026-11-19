# my-skills

个人 Skill 仓库 —— 存放自研的 [MCode / MiniMax Code](https://www.minimaxi.com) Skill，供自己在多台机器上安装，或分享给其他 agent 使用。

每个 Skill 都是一个独立目录，含 `SKILL.md`（入口与流程）、`scripts/`（确定性脚本）、`references/`（深度资料）。仓库按 `skills/<skill-name>/` 组织，与 MCode Plugin 的目录约定一致，因此将来也可以直接打包成 Plugin 上架。

## 目录结构

```
my-skills/
├── README.md                       # 本文件：仓库总览
├── install.sh                      # 一键安装脚本
├── .gitignore
├── docs/
│   ├── INSTALL.md                  # 安装说明：路径规则、依赖、验证、卸载
│   └── ADD-A-SKILL.md              # 新增 Skill 的规范与检查清单
└── skills/
    └── wechat-channels-download/   # Skill 本体
        ├── SKILL.md                # 入口：触发词、输入要求、执行流程、故障处理
        ├── scripts/
        │   └── wx_sph_download.py  # 视频号解析 + 下载 + 解密脚本
        └── references/
            └── implementation.md   # 实现方案：接口形状、加密算法、排查记录
```

## 已收录的 Skill

| Skill | 用途 | 触发词示例 |
|---|---|---|
| [`wechat-channels-download`](skills/wechat-channels-download/) | 把微信视频号（WeChat Channels）分享链接解析并下载成本地 MP4，自动处理 CDN 加密 | 「下载这个视频号视频」「视频号去水印」「转存视频号链接」 |

> 每个 Skill 的详细用法见它自己的 `SKILL.md`，本表只做索引。

## 快速安装

```bash
git clone git@github.com:imzdong/my-skills.git
cd my-skills
./install.sh                        # 装全部
./install.sh wechat-channels-download   # 只装指定 skill
./install.sh --list                 # 看可装哪些
```

也可以完全手动 —— 把 `skills/<skill-name>/` 整个目录拷到目标位置即可：

```bash
mkdir -p ~/.minimax/skills
cp -R skills/wechat-channels-download ~/.minimax/skills/
```

## 安装到哪里

**这是最常被问的问题，规则如下：**

| 场景 | 路径 | 可见范围 |
|---|---|---|
| **默认**（不指定） | `~/.minimax/skills/<skill-name>/` | **本机所有 agent** |
| Agent 私有 | `~/.minimax/agents/<agent>/skills/<skill-name>/` | 仅该 agent |
| 自定义目录 | `--dir /any/path` | 取决于运行时是否扫描该路径 |

命令行等价写法：

```bash
./install.sh --agent mavis       # → ~/.minimax/agents/mavis/skills/<name>/
./install.sh --dir /opt/skills  # → /opt/skills/<name>/
```

> `~/.minimax` 是默认运行时数据目录（`DATA_DIR`）。若你用了多 profile，真实数据目录可能不同 ——
> 以 `skill({ name: "<skill-name>" })` 返回的 **`Location:`** 头为准，那里就是实际生效的路径。

**生效时机：下一个会话生效**，不需要重启运行时。

## 依赖

Skill 依赖什么，写在各自的 `SKILL.md` 里。本仓库当前的依赖：

| 依赖 | 用途 | 必需性 |
|---|---|---|
| Python 3 + `requests` | 网络请求 | 必需 |
| Python 3 + `ssl` | HTTPS 底层（**最易踩坑项**） | 必需 |
| `ffmpeg` / `ffprobe` | 视频校验、剪辑 | 部分 skill 必需 |

macOS 上多个 `python3` 并存时（pyenv + homebrew + 系统自带），**务必挑对解释器**：

```bash
for p in $(which -a python3); do
  $p -c "import ssl, requests" 2>/dev/null && echo "✅ 用这个: $p"
done
```

详见 [docs/INSTALL.md](docs/INSTALL.md)。

## 新增 Skill

见 [docs/ADD-A-SKILL.md](docs/ADD-A-SKILL.md) —— 包含目录规范、`SKILL.md` frontmatter 要求、lint 命令和提交前检查清单。

## License

仅供个人学习与内部使用。各 Skill 涉及第三方平台时，请自行确保符合目标平台的服务条款。
