---
name: wechat-channels-download
description: |
  Download WeChat Channels (微信视频号) videos to a local file by resolving a share
  link through the Yuanbao (腾讯元宝) parse API, then fetching and decrypting the CDN
  stream. Load this skill whenever the user provides a 视频号 share link
  (https://weixin.qq.com/sph/xxx or https://channels.weixin.qq.com/finder-preview/pages/sph?id=xxx)
  or asks to 下载/保存/转存/导出 视频号 视频, "转存视频", "解析视频号链接",
  "视频号去水印", "save this 视频号 video", "download this WeChat Channels video",
  or 批量下载视频号内容. Also use it when the user asks how this downloader works or
  asks to build a 视频号转存 service on top of it. Do NOT use it for 公众号 articles,
  小程序 packages, or for downloading ordinary web videos from other platforms
  (use a direct HTTP fetch instead).
---

# 微信视频号视频下载

用 `scripts/wx_sph_download.py` 把视频号分享链接解析并下载成本地 MP4。

## Inputs to collect

调用前先确认这三项，缺哪项问哪项：

1. **分享链接** — 形如 `https://weixin.qq.com/sph/AkHrA7KbiA`。
   缺链接就没法开始，必须先要到。
2. **元宝 Cookie** — **必需**，脚本本身不带任何凭据。
   获取方式见下方「取 Cookie」。若用户已在对话里贴过，直接用。
3. **输出目录** — 可选，默认当前目录。用户说了就用用户的。

用户没提供 Cookie 时**不要伪造、不要跳过、不要改用免鉴权路径**（已验证无效，见 `references/implementation.md` §5）。直接告诉用户怎么取。

## Procedure

**先解析出脚本绝对路径再执行**，不要用 `scripts/...` 相对路径——那个写法只在当前目录恰好是 skill 目录时才成立。

```bash
# 取本 skill 的实际安装目录（换机器/换用户都会自动对上）
SKILL_DIR="${DATA_DIR:-$HOME/.minimax}/skills/wechat-channels-download"
SCRIPT="$SKILL_DIR/scripts/wx_sph_download.py"
```

`DATA_DIR` 指运行时数据目录（默认 `~/.minimax`）；若本 skill 被装成 **agent-private**（`~/.minimax/agents/<agent>/skills/`）或打成 **Plugin**（`<插件包>/skills/`），路径会不同——以 `skill({ name: "wechat-channels-download" })` 返回的 **`Location:`** 头为准，把它所在的目录换成 `scripts/wx_sph_download.py` 即可。
用 `test -f "$SCRIPT" || echo "路径不对，重新取 Location"` 先确认文件存在再往下走。

1. **确认输入**：拿到链接与 Cookie 后，把 Cookie 存到文件再传给脚本。
   原因：Cookie 是登录凭据，留在命令行参数里会进入 shell 历史；存文件权限可控。
   ```bash
   printf '%s' "$COOKIE" > ~/.yuanbao.cookie && chmod 600 ~/.yuanbao.cookie
   ```
   若用户已把 Cookie 存在文件里且权限已收紧，直接用那个文件，不要重复写入。
   若用户已把 Cookie 贴在对话里，写成文件即可，同样不要打印回显。

2. **检查依赖**：一次查全，别等下载中途才炸。
   ```bash
   # 只有一台 python3 时，快速检查
   python3 -c "import ssl, requests; print('py deps OK', requests.__version__)"
   command -v ffprobe || echo "警告：缺 ffprobe，无法做可播放校验"
   ```
   原因：`requests` 用于网络、`ssl` 是 HTTPS 的底层，缺任一都会在解析阶段就报错。
   **机器上有多个 `python3` 时必须挑对**（macOS 上常见 pyenv + homebrew + 系统自带并存）：

   ```bash
   for p in $(which -a python3); do
     $p -c "import ssl, requests" 2>/dev/null && echo "✅ 用这个: $p" || echo "❌ $p"
   done
   ```

   挑第一个能同时 import `ssl` 和 `requests` 的，把它作为 `$PY`，后续步骤里的 `python3` 全部换成 `$PY`。
   只有一个 `python3` 的机器则令 `PY=python3` 即可。

3. **先解析，看清楚要下什么**（可选但推荐）：
   ```bash
   $PY "$SCRIPT" '<链接>' --cookie-file ~/.yuanbao.cookie --info-only
   ```
   原因：先确认作者/描述/视频地址正常，再下载；避免下错内容或对着失效链接空等。

4. **下载**：
   ```bash
   $PY "$SCRIPT" '<链接>' -o <输出目录> --cookie-file ~/.yuanbao.cookie
   ```
   脚本会依次做元宝解析 → feed 信息 → CDN 下载 → 按需解密 → ffprobe 校验。
   注意：同名文件会被**静默覆盖**。下载前用 `ls` 看一下目标路径是否已有文件，若有且用户可能想保留，先改名或换个 `--name`。

5. **确认结果**：读脚本最后一行打印的 `✅ 可播放 ...` 与文件绝对路径。
   原因：这是唯一能证明文件真的可播放的证据。**不要**只看「下载完成」就报告成功。
   想要更强的证据，可再独立跑一次 `ffprobe` 复核。

6. **交付**：把视频文件路径告诉用户；若在会话里可用，用 `<deliver-assets>` 附上文件。

## 取 Cookie

浏览器打开 `https://yuanbao.tencent.com` 并确认已登录，然后：

- **Chrome / Edge**：`⌥⌘I` 打开开发者工具 → **Network** → `⌘R` 刷新 → 点任意一个 `yuanbao.tencent.com` 请求 → 右侧 **Headers** → **Request Headers** → 找 **`cookie:`** 行 → 右键 Copy value
- **Safari**：先在 `Safari → 设置 → 高级` 勾选「显示网页开发者功能」，再按 `⌥⌘I` → 网络 → 点请求 → 标头 → 找 `Cookie`
- 复制后一条命令存文件，避免进入对话记录：
  ```bash
  pbpaste > ~/.yuanbao.cookie && chmod 600 ~/.yuanbao.cookie
  ```

Cookie 过期时元宝返回 **HTTP 401**（body `{"error":{"code":"20000","message":"未知错误"}}`），需要重新登录并重新导出。

## Output contract

- 一个 `.mp4` 文件，路径由 `-o` 决定，文件名默认取视频描述（非法字符已替换）
- 脚本 stdout 的关键行：`✅ 可播放 <大小> <时长> <codec> <分辨率>` 与 `文件: <绝对路径>`
- `--info-only` 时输出 JSON：`author` / `description` / `videoUrl` / `coverUrl` / `decodeKey`
  - `decodeKey` 的取值含义：`0` = 该内容未加密（stdout 显示为 `decodeKey: (无)`），非零整数 = 需用它解密文件头。
    两种表示指向同一语义，判断时按「是否为 0」判断即可。

## Failure handling

| 现象 | 原因 | 处置 |
|---|---|---|
| `元宝返回 401` | Cookie 无效/过期 | 让用户重新登录元宝并重新导出 Cookie，不要绕过 |
| `feed_info 里没有 videoUrl` | 内容已失效或被限制 | 换一条链接重试；告知用户该内容不可用 |
| `视频号返回不可播放: 此内容暂时无法播放` | `exportId` 与 token 不匹配或内容下架 | 重新从头解析（重跑完整命令，不要复用旧的 token） |
| `CDN 返回 HTTP 4xx` | 视频地址过期 | 重新解析后再下 |
| `ffprobe 无法解析` | 缺 `decodeKey` 或加密方式变了 | 先看 `--info-only` 里 `decodeKey` 是否为空；为空则是上游策略变化，需重新研究解密 |
| 导入报 `ModuleNotFoundError: requests` | 缺依赖 | `pip3 install requests`（需用户同意） |
| `Can't connect to HTTPS URL because the SSL module is not available` | 当前解释器的 SSL 模块坏了，**与 Cookie/链接无关** | 见下方「SSL 坏掉」专条 |
| `ImportError: dlopen(...lib-dynload/_ssl...so...)` + `Library not loaded: .../libssl.3.dylib` | pyenv 编译时链接的 openssl keg 被 homebrew 升级掉了（`openssl@3` → `openssl@4`） | 见下方「SSL 坏掉」专条 |

**不要**在这些情况下改脚本去绕开鉴权或改用第三方解析服务——那会把用户的链接送到第三方。

## SSL 坏掉（与链接无关的常见故障）

症状：脚本在第 1 步就抛
`ImportError: Can't connect to HTTPS URL because the SSL module is not available`，
或底层报 `dlopen(..._ssl...so...)` / `Library not loaded: .../libssl.3.dylib`。

根因：机器上有多个 `python3`（macOS 常见 pyenv + homebrew + 系统自带并存），
当前 `python3` 恰好是那个 SSL 坏了的。典型触发场景是 **pyenv 编译时链接的 homebrew openssl
被升级掉了**——旧 keg（`openssl@3`）被移除，pyenv 的 `_ssl.so` 里写死的 rpath 找不到库了。

诊断：

```bash
for p in $(which -a python3); do
  printf "%-40s " "$p"; $p -c "import ssl; print('ssl OK')" 2>&1 | tail -1
done
```

处置，按代价从低到高：

1. **换解释器**（首选，零系统改动）：从上面的列表里挑一个 `ssl OK` 的，
   再确认它有 `requests`（`$p -c "import requests"`），用它执行脚本。
2. **装 requests 到可用解释器**：`$p -m pip install requests --user`（需用户同意）。
   macOS 15+ 的 homebrew python 是 externally-managed，装不了就建 venv：
   `$p -m venv ~/.venvs/wx && ~/.venvs/wx/bin/pip install requests`。
3. **恢复旧 openssl keg**：`brew install openssl@3`（需用户同意）。
   能让 pyenv 的 rpath 重新对上，但只是把被升级掉的旧版装回来，后续 homebrew 仍可能再升级一次。
4. **重编译 pyenv 版本**：`pyenv uninstall <ver> && pyenv install <ver>`（耗时数分钟，需用户同意）。
   会自动链接当前 openssl，一劳永逸。

**无论用哪种方式，装完都要用第 2 步的检查复验 `import ssl, requests` 是否通过。**

## Examples

Input: `帮我下载这个视频号视频 https://weixin.qq.com/sph/AkHrA7KbiA`

Output:
```
[1/4] 元宝解析: https://weixin.qq.com/sph/AkHrA7KbiA
      wx_export_id=export/<base64url 随机串>
[2/4] 获取视频号 feed 信息
      作者: 篮球教练（昵称已脱敏）
      描述: 视频有点长，请耐心看完
[3/4] 下载视频
  下载中 100.0%      10.2MB  3.78MB/s
[4/4] 解密 + 校验
      视频头本身即可解析，无需解密
      ✅ 可播放  10.2MB  124.5s  h264 720x1280

文件: /path/to/out/视频有点长，请耐心看完.mp4
```

Input: `视频号链接能不能批量下载？`

Output: 脚本一次处理一个链接，批量需在外部循环调用。告知用户这一点，并说明 `--info-only` 可先批量探测哪些链接有效。

## 安装位置

本 skill 属于**用户级全局** skill，默认装在 `~/.minimax/skills/wechat-channels-download/`，
本机**所有 agent** 都能看到。其他可选形式：

| 形式 | 路径 | 可见范围 |
|---|---|---|
| 用户级全局（默认） | `~/.minimax/skills/<name>/` | 本机所有 agent |
| Agent 私有 | `~/.minimax/agents/<agent>/skills/<name>/` | 仅该 agent |
| 自定义目录 | `install.sh --dir /any/path` | 取决于运行时是否扫描该路径 |

运行时数据目录若不是 `~/.minimax`（多 profile 场景），**以 `skill({ name: "wechat-channels-download" })`
返回的 `Location:` 头为准**。完整安装步骤见本仓库 `docs/INSTALL.md`。

## 深入资料

- `references/implementation.md` — 完整实现方案：两步接口的请求/响应形状、ISAac64 解密算法细节与对拍结果、免鉴权路径的排查结论、已实测的真实数据
- `scripts/wx_sph_download.py` — 完整脚本（含 `--help`）

## Windows (win32) platform notes

脚本本身跨平台（纯 `requests`，无系统依赖），只有取 Cookie 与写文件两步需要适配：

```powershell
# 存 Cookie（PowerShell）
$cookie | Set-Content -Path "$env:USERPROFILE\.yuanbao.cookie" -NoNewline -Encoding UTF8

# 下载（$SCRIPT 取自上面「取本 skill 的实际安装目录」那一步）
python $SCRIPT "<链接>" -o out --cookie-file "$env:USERPROFILE\.yuanbao.cookie"
```

Chrome/Edge 取 Cookie 的步骤与 macOS 相同（`F12` → Network → 请求 → Headers → Request Headers → `cookie:` 行）。
`pbpaste` 是 macOS 专有，Windows 用 `Get-Clipboard` 替代。
`chmod 600` 在 Windows 无意义；如需限制访问，用文件所在目录的 NTFS 权限。

