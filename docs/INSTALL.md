# 安装说明

本文档面向**要安装本仓库 Skill 的人**。如果你只是想知道「装到哪」，看下面「二、安装路径」就够。

---

## 一、前置要求

| 要求 | 说明 |
|---|---|
| Git | 仅从 GitHub 安装时需要 |
| SSH key | 私有仓库需要；仓库若设为 public，用 HTTPS 也能拉 |
| Python 3 | 仅部分 skill 需要（本仓库当前的所有 skill 都需要） |
| `requests` | Python 包，Python 3.8+ 直接可用 |
| `ffmpeg` / `ffprobe` | 视频相关 skill 需要，`brew install ffmpeg` / `apt install ffmpeg` |

---

## 二、安装路径

**Skill 装到哪里，决定了哪些 agent 能看到它。** 这是最容易搞混的地方，务必看这一节。

### 2.1 默认：用户级全局（推荐）

```
~/.minimax/skills/<skill-name>/
```

- **本机所有 agent 都能看到**，包括根 agent 和各种子 agent。
- 不指定任何参数时就是这个位置。
- 换设备、重装运行时都不会丢，只要 `~/.minimax` 还在。

```bash
./install.sh                                  # ← 装到这个位置
```

### 2.2 Agent 私有

```
~/.minimax/agents/<agent-name>/skills/<skill-name>/
```

- **只有 `<agent-name>` 这一个 agent 能看到**，其他 agent 完全看不到。
- 适合：某个 agent 专用的、跟它的角色强相关的 skill。
- 需要先在 `~/.minimax/agents/` 下存在该 agent 目录。

```bash
./install.sh --agent mavis
```

### 2.3 自定义目录

```bash
./install.sh --dir /opt/skills
```

注意：运行时扫描哪些额外目录取决于配置，**装到非默认位置不保证能被加载**。
用自定义目录前，先确认你的运行时配置里包含该路径。

### 2.4 多 profile / DATA_DIR 不是 `~/.minimax`

某些配置下运行时数据目录不是 `~/.minimax`。**判断实际生效路径的唯一可靠方式**：

```bash
skill({ name: "<skill-name>" })
```

返回结果里的 **`Location:`** 头就是运行时实际读到的目录。
脚本里请以它为准，不要写死路径。

---

## 三、三种安装方式

### 方式 A：一键脚本（推荐）

```bash
git clone git@github.com:imzdong/my-skills.git
cd my-skills
./install.sh --list                      # 先看有哪些 skill
./install.sh                              # 全部装到默认位置
./install.sh wechat-channels-download     # 只装一个
./install.sh --agent mavis --force        # 装为 agent 私有并覆盖旧版本
```

`install.sh` 会自动：

1. 拷贝 `skills/<name>/` 到目标目录（同名已存在时**默认跳过不覆盖**，避免误删你本地改过的版本）；
2. 探测哪个 `python3` 同时具备 `ssl` 和 `requests`，并打印可用解释器；
3. 提示生效时机与验证方法。

### 方式 B：手动拷贝

```bash
git clone git@github.com:imzdong/my-skills.git
mkdir -p ~/.minimax/skills
cp -R my-skills/skills/wechat-channels-download ~/.minimax/skills/
```

适合不想跑脚本、或想在拷贝前先改点东西的情况。

### 方式 C：直接 clone 到 skills 目录

```bash
git clone git@github.com:imzdong/my-skills.git ~/.minimax/skills/my-skills
```

这样仓库整个躺在 `~/.minimax/skills/my-skills/`，但 **MCode 要求每个 skill 目录根下直接有 `SKILL.md`**，
所以这个方式**不生效**。请用方式 A 或 B。

---

## 四、依赖安装

### 4.1 检查 Python 依赖

```bash
python3 -c "import ssl, requests; print('OK', requests.__version__)"
```

报 `ModuleNotFoundError: requests` → 装它：

```bash
python3 -m pip install requests --user
```

macOS 15+ 的 Homebrew Python 是 externally-managed，会拒绝安装。改用 venv：

```bash
python3 -m venv ~/.venvs/wx
~/.venvs/wx/bin/pip install requests
```

### 4.2 SSL 坏掉（最常见的环境坑）

症状：

```
ImportError: Can't connect to HTTPS URL because the SSL module is not available
```

或底层：

```
ImportError: dlopen(.../_ssl.cpython-312-darwin.so...): Library not loaded: .../libssl.3.dylib
```

**根因**：macOS 上常同时装着 pyenv、Homebrew、系统自带三套 `python3`。
pyenv 编译某个版本时会把 Homebrew 的 openssl 路径写死进 rpath；后来 Homebrew 把
`openssl@3` 升级成了 `openssl@4`，旧 keg 被移除 → pyenv 那个 Python 的 `_ssl` 就再也加载不上了。

诊断：

```bash
for p in $(which -a python3); do
  printf "%-40s " "$p"; $p -c "import ssl; print('ssl OK')" 2>&1 | tail -1
done
```

处置，按代价从低到高：

1. **换解释器**（零系统改动）：从上表挑一个 `ssl OK` 的，再确认它有 `requests`：
   ```bash
   $p -c "import requests" && echo "这个能用"
   ```
   然后用它执行脚本。
2. **装 requests 到可用解释器**：`$p -m pip install requests --user`，或建 venv（见 4.1）。
3. **恢复旧 openssl keg**：`brew install openssl@3`。能让 pyenv 的 rpath 重新对上，
   但 openssl@3 已 EOL，且 Homebrew 后续升级仍可能再触发一次。
4. **重编译 pyenv 版本**（一劳永逸，耗时数分钟）：
   ```bash
   pyenv uninstall 3.12.13 && pyenv install 3.12.13
   ```
   会自动链接当前 openssl。注意：重编译后 site-packages 会被清空，
   `requests` 等纯 Python 包需要重装。

> **原理上更稳的做法**：让 pyenv 编译时链接 Homebrew 的稳定 symlink（`/opt/homebrew/opt/openssl`）
> 而不是版本化的 `openssl@3`：
> ```bash
> PYTHON_CONFIGURE_OPTS="--with-openssl-dir=/opt/homebrew/opt/openssl" pyenv install 3.12.13
> ```

### 4.3 ffmpeg

```bash
brew install ffmpeg          # macOS
sudo apt install ffmpeg      # Debian/Ubuntu
```

`ffprobe` 用于校验产物视频是否真的可播放，缺了它下载仍能完成，但**你无法确认结果可信**。

---

## 五、验证安装

### 5.1 Skill 已被识别

新开一个会话，让 agent 执行：

```
skill({ name: "wechat-channels-download" })
```

- 能返回 SKILL.md 正文 + `Location:` 头 → 装好了 ✅
- 报 `Local skill not found` → 路径不对，回到「二、安装路径」核对
- **注意**：改完 skill 内容后要**新开会话**才生效，skill 在会话启动时加载

### 5.2 脚本能跑

```bash
SCRIPT=~/.minimax/skills/wechat-channels-download/scripts/wx_sph_download.py
PY=$(for p in $(which -a python3); do $p -c "import ssl, requests" 2>/dev/null && echo $p && break; done)
$PY "$SCRIPT" --help
```

---

## 六、需要额外凭据的 Skill

部分 skill 需要登录态才能工作，**凭据一律不进仓库**，由使用者自己在本机提供。

以 `wechat-channels-download` 为例，它需要**元宝（腾讯元宝）Cookie**：

```bash
# 存成文件（权限收紧）
printf '%s' "$COOKIE" > ~/.yuanbao.cookie && chmod 600 ~/.yuanbao.cookie
```

脚本支持 `--cookie-file <路径>` 或环境变量 `YUANBAO_COOKIE`，**脚本本身不含任何凭据**。
详见该 skill 的 `SKILL.md`。

---

## 七、更新与卸载

### 更新

```bash
cd my-skills && git pull
./install.sh --force        # 覆盖式更新已装的 skill
```

`--force` 会**直接删掉目标目录**再拷新版本 —— 你在本地改过的 SKILL.md 会丢失。

### 卸载

```bash
rm -rf ~/.minimax/skills/wechat-channels-download
```

装完删掉也没关系，仓库本体还在 GitHub 上，随时能重装。

---

## 八、常见问题

| 现象 | 原因 | 处置 |
|---|---|---|
| `Local skill not found` | 路径不对，或当前会话在安装前就已启动 | 新开会话；核对 `Location:` 头 |
| 改了 SKILL.md 没生效 | Skill 在会话启动时加载 | 新开会话 |
| `SSL module is not available` | 当前 python3 的 SSL 坏了 | 见 4.2 |
| `ModuleNotFoundError: requests` | 缺依赖 | 见 4.1 |
| 下载成功但提示未加密/不可播放 | 目标平台接口或加密策略变了 | 看该 skill 的 `references/implementation.md` |
