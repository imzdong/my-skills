# 微信视频号视频下载 —— 实现方案

> 最后更新：2026-11-18
> 配套脚本：`wx_sph_download.py`
> 已封装为 Skill：`wechat-channels-download`（见文末）

---

## 1. 目标与结论

用纯 Python 在本地下载微信视频号视频（输入形如 `https://weixin.qq.com/sph/xxxx` 的分享链接），无需安装任何二进制程序、无需安装根证书、无需修改系统代理。

**核心结论：元宝（yuanbao.tencent.com）接口是必需的**，但原因不是"接口刁钻"，而是——

> 换取视频地址所需的 `generalToken`，**只由元宝签发**。

---

## 2. 整体链路

```
分享链接
   │
   ▼
① 元宝解析      POST https://yuanbao.tencent.com/api/weixin/get_parse_result
   │            body: {"type":"video_channel_url","url":<链接>,"scene":1}
   │            需要 yuanbao.tencent.com 的登录 Cookie
   │            ← 返回 data.wx_export_id / data.playable_url
   │
   ▼  从 playable_url 的 query 里取 token 与 eid
② 视频号详情    POST https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info
   │            body: {"baseReq":{"generalToken":<token>},"exportId":<eid>}
   │            Referer 必须是 /finder-preview/pages/feed?…&token=…&eid=…
   │            ← 返回 data.feedInfo.videoUrl / h264VideoInfo.videoUrl / h265VideoInfo.videoUrl
   │               以及 data.authorInfo.nickname、feedInfo.description、coverUrl
   │
   ▼
③ CDN 下载      GET <videoUrl>（finder.video.qq.com/…/stodownload?encfilekey=…）
   │            实测不校验 Referer，支持 Range 断点续传
   │
   ▼
④ 解密 + 校验   若响应带 decodeKey → ISAac64 解密文件头 131072 字节
                再用 ffprobe 验证是否可播放
```

---

## 3. 关键实现细节

### 3.1 第一步：元宝解析

**请求**

| 项 | 值 |
|---|---|
| Method / URL | `POST https://yuanbao.tencent.com/api/weixin/get_parse_result` |
| Body | `{"type":"video_channel_url","url":"<分享链接>","scene":1}` |
| 关键 Header | `cookie`（登录态）、`origin`、`referer`、`accept`、`content-type`、`user-agent` |

> **实测结论：除登录 Cookie 外，只需要浏览器基础头。**
> 上游 `wx_channels_download` 在此处塞了一堆硬编码头（`x-device-id`、`t-userid`、`x-id`、
> `x-hy92`、`x-hy93`、`x-agentid`、`x-commit-tag` 等），那些是**上游作者本人设备/账号的指纹**，
> 不是协议要求。本实现已实测验证：去掉全部设备指纹头后仍返回 **HTTP 200**，
> 且 `wx_export_id` 与 `playable_url` 与带完整头时**完全一致**。
> 因此本脚本**刻意不带**这些头 —— 复制别人的 device-id 等于冒充另一个账号的设备。

**响应**

```jsonc
{
  "data": {
    "wx_export_id": "export/<base64url 随机串>",
    "playable_url": "https://...?token=<generalToken>&eid=<exportId>",
    "cover_url": "...",
    "author": "..."
  }
}
```

`generalToken` 与 `exportId` 从 `playable_url` 的 query 参数里取：
`token` → generalToken，`eid` → exportId。

**失败特征**：无 Cookie / Cookie 过期 → HTTP **401**，body `{"error":{"code":"20000","message":"未知错误"}}`。

### 3.2 第二步：视频号 feed 信息

**请求**

| 项 | 值 |
|---|---|
| Method / URL | `POST https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info?_rid=<hexTime>-<8位随机hex>&_pageUrl=<encoded>` |
| Body | `{"baseReq":{"generalToken":"<token>"},"exportId":"<eid>"}` |
| Referer | `https://channels.weixin.qq.com/finder-preview/pages/feed?entry_card_type=48&comment_scene=39&appid=0&token=<token>&entry_scene=0&eid=<eid>` |

`_rid` 格式：`format(int(time.time()), "x")` + `-` + 8 位随机 hex。

**响应关键字段**

```
data.feedInfo.h264VideoInfo.videoUrl   ← 优先用这个（H.264 兼容性最好）
data.feedInfo.videoUrl                 ← 其次
data.feedInfo.h265VideoInfo.videoUrl   ← 最后
data.feedInfo.description / coverUrl / createtime
data.authorInfo.nickname
```

**失败特征**：`data.errMsg` 非空（如 `{"type":2,"title":"此内容暂时无法播放"}`）→ 内容失效或需要额外授权。

> **注意**：该接口成功时返回 **HTTP 201**（不是 200）。用 `raise_for_status()` 判断成败不受影响（201 也算 2xx），
> 但如果自己写状态码断言，**不要只接受 200**。

### 3.3 第三步：CDN 下载

- 视频地址形如 `https://finder.video.qq.com/251/20302/stodownload?encfilekey=…&token=…&hy=SZ&idx=1&m=…`
- **实测不校验 Referer**，但仍带上 `Referer: https://channels.weixin.qq.com/` 更稳妥
- **支持 Range**，脚本已实现断点续传（`.part` 临时文件 + `Range: bytes=<offset>-`）
- 删除 `X-snsvideoflag` 查询参数（与上游 `CleanVideoURL` 行为一致）

### 3.4 第四步：解密

**关键事实：只有文件头 131072 字节（128KB）被加密**，其余字节原样存放。
这不是推测——上游 `wx_channels_download` 的 `DecryptReader` 中，`limit`(=encLimit) 之后的字节直接透传不解密；`encLimit` 硬编码为 `131072`。

**算法**：ISAac64 伪随机流 XOR（原始实现来自 `Hanson/WechatSphDecrypt`）

```
密钥流：每 8 字节取一次 ISAacRandom()，按 BigEndian 拆成 8 字节与文件字节 XOR
```

**状态结构**

```python
RandCtx64 = { RandCnt, Seed[256], MM[256], AA, BB, CC }
```

**初始化** `rand64Init(key)`

1. `Seed[0] = key`，其余为 0
2. `a..h` 全部置 `golden = 0x9e3779b97f4a7c13`
3. 4 轮 `mix()`
4. 遍历 `Seed`，每 8 个一组加上对应 `Seed` 值 → `mix()` → 写入 `MM`
5. 再遍历 `MM`，同样处理一次 → 写回 `MM`
6. 最后执行一次 `isaac64()`

**取数** `ISAacRandom()`

```
result = Seed[RandCnt]
若 RandCnt == 0: 执行 isaac64()，RandCnt = 255
否则:           RandCnt--
```

**核心轮** `isaac64()`

```python
CC += 1
BB += CC
for i in range(256):
    AA = { i%4==0: ~(AA ^ (AA<<21)),
           i%4==1: AA ^ (AA>>5),
           i%4==2: AA ^ (AA<<12),
           i%4==3: AA ^ (AA>>33) }[i%4]
    AA += MM[(i+128) % 256]
    x  = MM[i]
    y  = MM[(x>>3) % 256] + AA + BB
    MM[i] = y
    BB = MM[(y>>11) % 256] + x
    Seed[i] = BB
```

**`mix()`（26 行，注意不是 8 行）**

```
a-=e; f^=h>>9; h+=a; b-=f; g^=a<<9; a+=b; c-=g; h^=b>>23; b+=c;
d-=h; a^=c<<15; c+=d; e-=a; b^=d>>14; d+=e; f-=b; c^=e<<20; e+=f;
g-=c; d^=f>>17; f+=g; h-=d; e^=g<<14; g+=h;
```

**移植注意**：Go 的 `uint64` 是溢出回绕语义，Python 必须每步 `& 0xFFFFFFFFFFFFFFFF`。

**decodeKey 的位置**：`decodeKey` **不在**元宝返回的 `feedInfo` 里，而在更深层（`objectDesc.media[].decodeKey`）。脚本用递归查找 `decodeKey` / `decode_key` 兜住所有层级。

---

## 4. 实测验证

### 4.1 解密算法 —— 与 C 参考实现字节级对拍

把 Go 源码转写为 C（利用 C 原生 `uint64` 溢出语义），编译成参考实现，与 Python 逐字节比对：

| decodeKey | 结果 |
|---|---|
| `0` | ✅ MATCH |
| `1` | ✅ MATCH |
| `1234567890123` | ✅ MATCH |
| `987654321987654321` | ✅ MATCH |
| `2^63` | ✅ MATCH |
| `2^64 - 1` | ✅ MATCH |
| `131072` | ✅ MATCH |
| `0xdeadbeefcafe` | ✅ MATCH |

另测：加密→解密 roundtrip 字节完全一致；`encLimit` 之后字节原样保留 ✅

### 4.2 端到端链路自检

用 ffmpeg 生成真 MP4，按视频号方式加密前 131072 字节，跑完整流程：

```
加密后 ffprobe: ❌ 不可解析（符合预期）
解密后 ffprobe: ✅ 可播放  duration=3.000000
字节完全一致: ✅    encLimit 之后原样保留: ✅
```

### 4.3 真实链接实测

输入 `https://weixin.qq.com/sph/AkHrA7KbiA`：

```
[1/4] 元宝解析 → wx_export_id ✅  generalToken ✅
[2/4] feed 信息 → 作者: 篮球教练（昵称已脱敏）
      描述: 视频有点长，请耐心看完
[3/4] 下载 10.2MB @ 3.78MB/s
[4/4] ✅ 可播放  10.2MB  124.5s  h264 720x1280 (+aac)
```

抽帧核验：60 秒处画面为完整的篮球投篮教学视频，与作者名吻合（非花屏/非黑屏）。

> **注意**：本次实测该视频 `decodeKey` 为空，视频头本身即可解析，**未触发解密**。
> 解密路径本身已通过 §4.1 / §4.2 独立验证，遇到带 `decodeKey` 的内容会自动启用。

### 4.4 独立复现验证（第二次实现）

为确认方案不依赖任何「只有作者本人才知道」的隐性知识，另起一个干净环境从零复现（不参考本项目代码，只参考公开上游源码）：

- 自行调研上游 → 自行实现 4 阶段流水线 → 产出视频
- 产物 **SHA-256 与本项目产物完全一致**：`c0a336c13045ad3733d92e0ce67e5e0bca8e4242c0ea9fa77639c721c6b8a5f6`
- 额外验证：ISAac64 对拍 8/8 ✅、roundtrip 字节一致 ✅、Range 续传 ✅（预置 1MiB `.part` 只补拉剩余部分，结果字节一致）

复现过程中发现的两条事实，已回写进本实现：

1. **设备指纹头非必需**（见 §3.1）→ 本脚本已精简
2. **`get_feed_info` 成功返回 HTTP 201**（见 §3.2）→ 用 `raise_for_status()` 不受影响

---

## 5. 免鉴权路径的排查结论

曾尝试绕开元宝，直接从分享链接拿视频地址。**全部失败**，记录如下以免重复踩坑：

| 尝试 | 结果 |
|---|---|
| 元宝接口不带 Cookie | ❌ 401 |
| 元宝游客 Cookie（首页获取） | ❌ 401（首页根本不 Set-Cookie） |
| 直连 `weixin.qq.com/sph/xxx` → 301 到 finder-preview | ⚠️ 能拿**标题/作者/封面/点赞数**，**拿不到 videoUrl** |
| `get_feed_info` 用 `shortUri` 免鉴权 | ⚠️ 同上，只有元数据 |
| 换微信 MicroMessenger UA | ❌ 仍只有元数据 |
| 加 `needVideoUrl` / `withVideo` / `baseReq.scene` / `entryScene` 等参数变体 | ❌ 仍只有元数据 |
| 换 Referer（/feed?es=64 vs /sph） | ❌ 无差别 |
| 试 `get_feed_detail` / `get_media_info` / `get_video_url` 等邻近接口 | ❌ `请求异常` |
| 从封面 URL 反推视频地址（改 idx / 去 hy / 换路径段） | ❌ 路径段有效但 key 不同源，400 |
| 用 `exportId` + 空 token 复调 | ❌ `此内容暂时无法播放`（type 2） |

**结论**：视频地址与 `generalToken` 绑定，只能由元宝发放。这与上游 `wx_channels_download` 的实现一致。

---

## 6. 用法

### 6.1 获取元宝 Cookie

浏览器（Chrome / Edge）：

1. 打开 `https://yuanbao.tencent.com`，确认已登录
2. `⌥⌘I` 打开开发者工具 → **Network** 标签
3. `⌘R` 刷新
4. 点任意一个 `yuanbao.tencent.com` 请求
5. 右侧 **Headers** → **Request Headers** → 找 **`cookie:`** 行 → 右键 Copy value

Safari：先在 `Safari → 设置 → 高级` 勾选「显示网页开发者功能」，再按 `⌥⌘I`。

**推荐存文件，避免 Cookie 进入对话记录：**

```bash
pbpaste > ~/.yuanbao.cookie && chmod 600 ~/.yuanbao.cookie
```

### 6.2 运行

```bash
cd <你的工作目录>   # 任意目录，脚本本身不依赖特定项目结构

# 方式 A：Cookie 文件
python3 <skill目录>/scripts/wx_sph_download.py 'https://weixin.qq.com/sph/AkHrA7KbiA' -o out/ \
    --cookie-file ~/.yuanbao.cookie

# 方式 B：环境变量
export YUANBAO_COOKIE='xxx=yyy; ...'
python3 <skill目录>/scripts/wx_sph_download.py 'https://weixin.qq.com/sph/AkHrA7KbiA' -o out/
```

### 6.3 参数

| 参数 | 说明 |
|---|---|
| `url` | 视频号分享链接（必填） |
| `-o/--outdir` | 输出目录，默认当前目录 |
| `--cookie` / `--cookie-file` | 元宝 Cookie；也可用环境变量 `YUANBAO_COOKIE` |
| `--name` | 输出文件名（不含扩展名），默认取视频描述 |
| `--info-only` | 只解析不下载，打印 JSON |
| `--no-decrypt` | 跳过解密 |
| `--video-url` | 跳过解析，直接用视频地址下载（调试用） |
| `--decode-key` | 配合 `--video-url` 的解密密钥 |
| `--timeout` | 单次 HTTP 超时秒数，默认 30 |

### 6.4 安全约定

- Cookie **只从环境变量或文件读取**，脚本内零硬编码（已 grep 验证 `hy_token` / `qimei` 出现 0 次）
- 脚本**不打印 Cookie 内容**
- 建议用 `--cookie-file` + `chmod 600`

---

## 7. 已知限制与后续方向

### 7.1 当前限制

- 依赖元宝 Cookie，**Cookie 过期需重新导出**（这是长期最大成本）
- 未支持图文（图片）类型的内容批量导出
- 未做并发下载（一次一个视频）

### 7.2 服务化方向（粉丝转存）

基于已确认的事实，技术上完全可行，且比原估计简单——**不需要装根证书、不需要改系统代理、不需要对象存储**。核心就是一个 Python 服务 + 边下边解密边转发。

建议路线：

1. **最小形态**：Flask 起 `/download?url=xxx`，H5 页面输入链接直接下载，公众号自定义菜单挂过去
2. **载体**：H5 优先（未认证个人订阅号无客服消息接口、无法异步推送结果；小程序需备案域名且审核严）
3. **成本对比**：元宝 Cookie 需长期续命；商业解析 API（按量计费，直接返回 `download_url` + `decode_key`）在粉丝量上来后可能更划算

### 7.3 合规提醒

视频号 ToS 禁止未授权下载，微信已对违规第三方平台提起过司法程序。

**建议第一阶段只开放「自己的号 + 白名单作者」**，不要一上来开放任意链接——这是账号被封的实操风险，不是道德说教。

---

## 8. 上游参考

| 来源 | 用途 |
|---|---|
| [`ltaoo/wx_channels_download`](https://github.com/ltaoo/wx_channels_download) | 主参考。`pkg/scraper/wxchannels/yuanbao.go`（两步解析）、`decrypt.go`（ISAac64）、`reader.go`（DecryptReader 的 limit/offset 语义）、`decryptor.go`（边下边解密边转发） |
| [`Hanson/WechatSphDecrypt`](https://github.com/Hanson/WechatSphDecrypt) | ISAac64 原始实现 |
| `internal/adapter/wxchannels/model.go` | `shared_video_profile_to_channels_object` 构造 media 时不含 DecodeKey → 元宝路径的视频通常未加密 |
| `internal/workers/sph/worker.js` | Cloudflare Worker 版两步解析，JS 参考实现 |

> ⚠️ 上游原版程序会安装自签根证书到系统钥匙串并修改系统代理，本方案**刻意不采用**该做法。
