#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信视频号视频下载脚本（本地版，纯 Python + requests）

解析链路（与 wx_channels_download 的元宝路径一致）：
  1) 元宝解析   POST https://yuanbao.tencent.com/api/weixin/get_parse_result
                 body: {"type":"video_channel_url","url":<分享链接>,"scene":1}
                 -> data.wx_export_id / data.playable_url(含 token、eid)
  2) 视频号详情 POST https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info
                 body: {"baseReq":{"generalToken":<token>},"exportId":<eid>}
                 -> data.feedInfo.videoUrl / h264VideoInfo.videoUrl / h265VideoInfo.videoUrl
  3) CDN 下载 + ISAac64 解密（仅文件头 131072 字节）

用法：
    # 方式 A：环境变量（推荐，别把 Cookie 贴进聊天记录）
    export YUANBAO_COOKIE='xxx=yyy; zzz=www'
    python3 wx_sph_download.py 'https://weixin.qq.com/sph/AkHrA7KbiA' -o out/

    # 方式 B：Cookie 存文件（更安全，脚本不会打印）
    python3 wx_sph_download.py 'https://weixin.qq.com/sph/AkHrA7KbiA' -o out/ \
        --cookie-file ~/.yuanbao.cookie

    # 只看解析结果，不下载
    python3 wx_sph_download.py 'https://weixin.qq.com/sph/AkHrA7KbiA' --info-only

Cookie 获取方法（Chrome / Edge / Safari 通用）：
    打开 https://yuanbao.tencent.com  →  F12 → Network → 任意请求 →
    Request Headers → 复制 "Cookie:" 整行的值。
"""

import argparse
import json
import os
import random
import re
import sys
import time
from urllib.parse import quote, urlparse, parse_qs

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")

YUANBAO_PARSE_URL = "https://yuanbao.tencent.com/api/weixin/get_parse_result"
FEED_INFO_URL = "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info"

# 视频号只加密文件头这一段（wx_channels_download 里写死的 131072）
ENC_LIMIT = 131072


# --------------------------------------------------------------------------
# ISAac64 解密（移植自 ltaoo/wx_channels_download 的 pkg/scraper/wxchannels/decrypt.go，
#               原始算法出自 Hanson/WechatSphDecrypt）
# --------------------------------------------------------------------------
M64 = 0xFFFFFFFFFFFFFFFF


class ISAac64:
    def __init__(self, enc_key: int):
        self.rand_cnt = 255
        self.AA = 0
        self.BB = 0
        self.CC = 0
        self.seed = [0] * 256
        self.mm = [0] * 256
        self._rand64_init(enc_key & M64)

    @staticmethod
    def _mix(v):
        a, b, c, d, e, f, g, h = v
        a = (a - e) & M64
        f ^= (h >> 9)
        h = (h + a) & M64
        b = (b - f) & M64
        g ^= (a << 9) & M64
        a = (a + b) & M64
        c = (c - g) & M64
        h ^= (b >> 23)
        b = (b + c) & M64
        d = (d - h) & M64
        a ^= (c << 15) & M64
        c = (c + d) & M64
        e = (e - a) & M64
        b ^= (d >> 14)
        d = (d + e) & M64
        f = (f - b) & M64
        c ^= (e << 20) & M64
        e = (e + f) & M64
        g = (g - c) & M64
        d ^= (f >> 17)
        f = (f + g) & M64
        h = (h - d) & M64
        e ^= (g << 14) & M64
        g = (g + h) & M64
        return [x & M64 for x in (a, b, c, d, e, f, g, h)]

    def _rand64_init(self, enc_key: int):
        golden = 0x9E3779B97F4A7C15
        v = [golden] * 8
        self.seed[0] = enc_key
        for i in range(1, 256):
            self.seed[i] = 0

        for _ in range(4):
            v = self._mix(v)

        for i in range(0, 256, 8):
            v = [(v[j] + self.seed[i + j]) & M64 for j in range(8)]
            v = self._mix(v)
            self.mm[i:i + 8] = v

        for i in range(0, 256, 8):
            v = [(v[j] + self.mm[i + j]) & M64 for j in range(8)]
            v = self._mix(v)
            self.mm[i:i + 8] = v

        self._isaac64()

    def _isaac64(self):
        self.CC = (self.CC + 1) & M64
        self.BB = (self.BB + self.CC) & M64
        for i in range(256):
            if i % 4 == 0:
                self.AA = (~(self.AA ^ ((self.AA << 21) & M64))) & M64
            elif i % 4 == 1:
                self.AA ^= (self.AA >> 5)
            elif i % 4 == 2:
                self.AA = (self.AA ^ ((self.AA << 12) & M64)) & M64
            else:
                self.AA ^= (self.AA >> 33)
            self.AA = (self.AA + self.mm[(i + 128) % 256]) & M64
            x = self.mm[i]
            y = (self.mm[(x >> 3) % 256] + self.AA + self.BB) & M64
            self.mm[i] = y
            self.BB = (self.mm[(y >> 11) % 256] + x) & M64
            self.seed[i] = self.BB

    def random64(self) -> int:
        result = self.seed[self.rand_cnt]
        if self.rand_cnt == 0:
            self._isaac64()
            self.rand_cnt = 255
        else:
            self.rand_cnt -= 1
        return result

    def keystream(self, nbytes: int) -> bytes:
        out = bytearray()
        while len(out) < nbytes:
            out += self.random64().to_bytes(8, "big")
        return bytes(out[:nbytes])


def decrypt_head(data: bytes, key: int, limit: int = ENC_LIMIT) -> bytes:
    """解密文件头 limit 字节，其余原样返回。"""
    if not data or key == 0 or limit <= 0:
        return data
    limit = min(limit, len(data))
    gen = ISAac64(key)
    ks = gen.keystream(limit)
    head = bytes(b ^ k for b, k in zip(data[:limit], ks))
    return head + data[limit:]


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------
def gen_rid() -> str:
    return format(int(time.time()), "x") + "-" + "".join(
        random.choice("0123456789abcdef") for _ in range(8))


def yuanbao_headers(cookie: str) -> dict:
    """元宝解析请求头。

    实测确认：除登录 Cookie 外，只需要浏览器基础头即可成功（HTTP 200）。
    上游 wx_channels_download 里那批 x-device-id / t-userid / x-hy92 等
    是「上游作者本人设备」的指纹，并非协议必需；复制它们等于冒充别的账号设备，
    因此这里刻意不带。
    """
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "content-type": "application/json",
        "origin": "https://yuanbao.tencent.com",
        "referer": "https://yuanbao.tencent.com/",
        "user-agent": UA,
        "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "cookie": cookie,
    }


def feed_info_headers(token: str, eid: str) -> dict:
    referer = ("https://channels.weixin.qq.com/finder-preview/pages/feed"
               f"?entry_card_type=48&comment_scene=39&appid=0&token={quote(token, safe='')}"
               f"&entry_scene=0&eid={quote(eid, safe='')}")
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Content-Type": "application/json",
        "Origin": "https://channels.weixin.qq.com",
        "Referer": referer,
        "User-Agent": UA,
        "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }


# --------------------------------------------------------------------------
# 步骤 1：元宝解析
# --------------------------------------------------------------------------
def yuanbao_parse(share_url: str, cookie: str, timeout: int = 30) -> dict:
    payload = {"type": "video_channel_url", "url": share_url, "scene": 1}
    r = requests.post(YUANBAO_PARSE_URL, json=payload,
                      headers=yuanbao_headers(cookie), timeout=timeout)
    if r.status_code == 401:
        raise RuntimeError(
            "元宝返回 401：Cookie 无效或已过期。"
            "请重新登录 yuanbao.tencent.com 并重新导出 Cookie。")
    r.raise_for_status()
    body = r.json()
    data = body.get("data") or {}
    if not data.get("wx_export_id"):
        raise RuntimeError(f"元宝解析失败: {json.dumps(body, ensure_ascii=False)[:400]}")
    return data


# --------------------------------------------------------------------------
# 步骤 2：视频号 feed 信息
# --------------------------------------------------------------------------
def fetch_feed_info(eid: str, token: str, timeout: int = 30) -> dict:
    url = (f"{FEED_INFO_URL}?_rid={gen_rid()}"
           "&_pageUrl=https:%2F%2Fchannels.weixin.qq.com%2Ffinder-preview%2Fpages%2Ffeed")
    payload = {"baseReq": {"generalToken": token}, "exportId": eid}
    r = requests.post(url, json=payload, headers=feed_info_headers(token, eid),
                      timeout=timeout)
    r.raise_for_status()
    body = r.json()
    err = (body.get("data") or {}).get("errMsg") or {}
    if err.get("type") or (err.get("title") or err.get("content")):
        msg = ": ".join(x for x in [err.get("title"), err.get("content")] if x)
        raise RuntimeError(f"视频号返回不可播放: {msg or err}")
    return body


def fetch_feed_info_by_short_uri(short_id: str, timeout: int = 30) -> dict:
    """免鉴权直连：只能拿到标题/作者/封面等元数据，拿不到视频地址。"""
    url = (f"{FEED_INFO_URL}?_rid={gen_rid()}"
           "&_pageUrl=https:%2F%2Fchannels.weixin.qq.com%2Ffinder-preview%2Fpages%2Ffeed")
    referer = f"https://channels.weixin.qq.com/finder-preview/pages/sph?id={short_id}"
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://channels.weixin.qq.com",
        "Referer": referer,
        "User-Agent": UA,
    }
    r = requests.post(url, json={"baseReq": {"generalToken": ""}, "shortUri": short_id},
                      headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def find_keys(obj, names):
    """递归查找任意层级的字段（decodeKey 可能藏在 mediaList / objectDesc.media 里）。"""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in names and v not in (None, "", 0):
                found.append((k, v))
            found.extend(find_keys(v, names))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(find_keys(item, names))
    return found


def pick_video_url(feed_info: dict) -> str:
    for path in (("h264VideoInfo", "videoUrl"), ("videoUrl",), ("h265VideoInfo", "videoUrl")):
        cur = feed_info
        for key in path:
            if not isinstance(cur, dict):
                cur = None
                break
            cur = cur.get(key)
        if isinstance(cur, str) and cur.strip():
            return cur.strip()
    return ""


def clean_video_url(url: str) -> str:
    """删除 X-snsvideoflag 参数（与仓库 CleanVideoURL 一致）。"""
    try:
        parts = urlparse(url)
        q = parse_qs(parts.query, keep_blank_values=True)
        q.pop("X-snsvideoflag", None)
        new_q = "&".join(f"{k}={v[0]}" for k, v in q.items())
        return f"{parts.scheme}://{parts.netloc}{parts.path}" + (f"?{new_q}" if new_q else "")
    except Exception:
        return url


# --------------------------------------------------------------------------
# 步骤 3：下载
# --------------------------------------------------------------------------
def download(video_url: str, dest: str, referer: str = "https://channels.weixin.qq.com/",
             session: requests.Session = None) -> str:
    session = session or requests.Session()
    headers = {
        "User-Agent": UA,
        "Referer": referer,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    tmp = dest + ".part"
    offset = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    h = dict(headers)
    if offset:
        h["Range"] = f"bytes={offset}-"
    with session.get(video_url, headers=h, stream=True, timeout=60) as r:
        if r.status_code in (301, 302, 307, 308):
            r = session.get(r.headers["Location"], headers=headers, stream=True, timeout=60)
        if r.status_code == 416 and offset:
            os.rename(tmp, dest)
            return dest
        if r.status_code not in (200, 206):
            raise RuntimeError(f"CDN 返回 HTTP {r.status_code}: {r.text[:200]}")
        mode = "ab" if (offset and r.status_code == 206) else "wb"
        if mode == "wb":
            offset = 0
        total = int(r.headers.get("Content-Length") or 0) + offset
        done = offset
        t0 = time.time()
        with open(tmp, mode) as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100.0 / total
                    speed = done / max(time.time() - t0, 1e-6) / 1024 / 1024
                    sys.stdout.write(f"\r  下载中 {pct:5.1f}%  {done/1024/1024:7.1f}MB  {speed:4.2f}MB/s")
                    sys.stdout.flush()
    if total:
        sys.stdout.write("\n")
    os.rename(tmp, dest)
    return dest


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------
def ffprobe(path: str):
    import subprocess
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration,size,format_name:stream=codec_name,width,height",
             "-of", "json", path],
            capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            return None
        return json.loads(out.stdout)
    except Exception:
        return None


def safe_name(text: str, fallback: str = "video") -> str:
    text = (text or "").strip().replace("\n", " ")
    text = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return (text[:60] or fallback)


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def load_cookie(args) -> str:
    if args.cookie:
        return args.cookie.strip()
    if args.cookie_file:
        path = os.path.expanduser(args.cookie_file)
        if not os.path.exists(path):
            raise SystemExit(f"Cookie 文件不存在: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    cookie = os.environ.get("YUANBAO_COOKIE", "").strip()
    if cookie:
        return cookie
    raise SystemExit(
        "没有找到元宝 Cookie。请用 --cookie-file / --cookie / 环境变量 YUANBAO_COOKIE 提供之一。\n"
        "获取方式：yuanbao.tencent.com 登录后 F12 → Network → 任一请求 → Request Headers → 复制 Cookie 行")


def main():
    ap = argparse.ArgumentParser(
        description="微信视频号视频下载（元宝解析 + CDN 下载 + ISAac64 解密）")
    ap.add_argument("url", help="视频号分享链接，如 https://weixin.qq.com/sph/xxxx")
    ap.add_argument("-o", "--outdir", default=".", help="输出目录（默认当前目录）")
    ap.add_argument("--cookie", help="元宝 Cookie 字符串")
    ap.add_argument("--cookie-file", help="元宝 Cookie 文件路径")
    ap.add_argument("--name", help="输出文件名（不含扩展名）")
    ap.add_argument("--info-only", action="store_true", help="只解析不下载")
    ap.add_argument("--no-decrypt", action="store_true", help="跳过解密（默认会解密）")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--video-url", help="跳过解析，直接用视频地址下载（调试用）")
    ap.add_argument("--decode-key", help="配合 --video-url 使用的解密密钥（十进制）")
    args = ap.parse_args()

    if args.video_url:
        key = 0
        if args.decode_key:
            try:
                key = int(str(args.decode_key).strip())
            except ValueError:
                raise SystemExit("--decode-key 必须是十进制整数")
        print("[1/4] 直接下载模式（跳过解析）")
        do_download(args, args.video_url, key, "", "", args.name or "video")
        return

    share_url = args.url.strip()
    cookie = load_cookie(args)

    print(f"[1/4] 元宝解析: {share_url}")
    data = yuanbao_parse(share_url, cookie, timeout=args.timeout)
    export_id = data.get("wx_export_id", "")
    playable = data.get("playable_url", "") or ""
    q = parse_qs(urlparse(playable).query)
    token = (q.get("token") or [""])[0]
    eid = (q.get("eid") or [""])[0]
    print(f"      wx_export_id={export_id}")
    print(f"      generalToken={token[:18]}...  eid={eid}")
    if not token or not eid:
        raise SystemExit("playable_url 里没解析出 token/eid，元宝返回可能异常。")

    print("[2/4] 获取视频号 feed 信息")
    body = fetch_feed_info(eid, token, timeout=args.timeout)
    feed_info = (body.get("data") or {}).get("feedInfo") or {}
    video_url = pick_video_url(feed_info)
    if not video_url:
        raise SystemExit("feed_info 里没有 videoUrl，可能该内容已失效或需要其它授权。")

    author = ((body.get("data") or {}).get("authorInfo") or {}).get("nickname", "")
    desc = feed_info.get("description", "")
    cover = feed_info.get("coverUrl", "")
    print(f"      作者: {author}")
    print(f"      描述: {desc[:60]}")
    print(f"      视频: {video_url[:110]}...")

    # decodeKey 可能藏在任意层级
    key_hits = find_keys(body, {"decodeKey", "decode_key"})
    decode_key = 0
    for _k, v in key_hits:
        try:
            decode_key = int(str(v).strip())
            break
        except Exception:
            continue
    print(f"      decodeKey: {decode_key if decode_key else '(无)'}")

    if args.info_only:
        print(json.dumps({"author": author, "description": desc,
                          "videoUrl": video_url, "coverUrl": cover,
                          "decodeKey": decode_key}, ensure_ascii=False, indent=2))
        return

    os.makedirs(args.outdir, exist_ok=True)
    name = args.name or safe_name(desc or author or "video")
    do_download(args, video_url, decode_key, author, desc, name)


def do_download(args, video_url, decode_key, author, desc, name):
    os.makedirs(args.outdir, exist_ok=True)
    # --name 若已带 .mp4 后缀则不重复追加，避免出现 xxx.mp4.mp4
    if name.lower().endswith(".mp4"):
        name = name[:-4]
    dest = os.path.join(args.outdir, f"{name}.mp4")

    print("[3/4] 下载视频")
    clean = clean_video_url(video_url)
    try:
        download(clean, dest)
    except RuntimeError:
        print("      清理参数后失败，改用原始 URL 重试")
        download(video_url, dest)

    print("[4/4] 解密 + 校验")
    size = os.path.getsize(dest) / 1024 / 1024

    def decrypt_in_place(path):
        with open(path, "rb") as f:
            head = f.read(ENC_LIMIT)
        with open(path, "r+b") as f:
            f.write(decrypt_head(head, decode_key, ENC_LIMIT))

    info = ffprobe(dest)
    if info:
        print("      视频头本身即可解析，无需解密")
    elif decode_key and not args.no_decrypt:
        decrypt_in_place(dest)
        print(f"      已解密文件头 {ENC_LIMIT} 字节")
        info = ffprobe(dest)
    else:
        print("      无 decodeKey，跳过解密")

    if info:
        dur = float(info.get("format", {}).get("duration") or 0)
        streams = info.get("streams", [])
        v = next((s for s in streams if s.get("codec_name", "").startswith(("h264", "h265", "hevc", "avc"))), None)
        print(f"      ✅ 可播放  {size:.1f}MB  {dur:.1f}s  " +
              (f"{v.get('codec_name')} {v.get('width')}x{v.get('height')}" if v else ""))
    else:
        print(f"      ⚠️  ffprobe 无法解析（{size:.1f}MB）。"
              "该内容可能需要其它授权，或视频号改了加密方式。")
    print(f"\n文件: {os.path.abspath(dest)}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已中断")
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:
        print(f"\n❌ 失败: {type(e).__name__}: {e}")
        sys.exit(1)
