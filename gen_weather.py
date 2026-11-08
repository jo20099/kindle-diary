#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 PW2 熄屏天气预报图（758x1024 灰阶 L，墨水屏友好）。

数据源 Open-Meteo（免费无密钥），广州市天河区。
联网失败时自动用 weather_cache.json 里上一次成功的数据。
用法:
  python gen_weather.py                      # 生成 weather_screensaver.png
  python gen_weather.py --w 1264 --h 1680   # 高分屏（kpw5/6）
"""
import argparse
import json
import math
import os
import urllib.request
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageFilter

DIR = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(DIR, "weather_cache.json")
LAT, LON = 23.1248, 113.3616
CITY = "广州市天河区"

FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",                       # macOS
    "/System/Library/Fonts/STHeiti Light.ttc",                  # macOS
    "/System/Library/Fonts/Hiragino Sans GB.ttc",               # macOS
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",   # Linux CI / Ubuntu
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",            # Linux 文泉驿
]
BLACK, WHITE, GRAY = 0, 255, 150

WMO = {0: "晴", 1: "晴间多云", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
       51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨", 56: "冻毛毛雨", 57: "冻毛毛雨",
       61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "冻雨",
       71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
       80: "阵雨", 81: "阵雨", 82: "强阵雨", 85: "阵雪", 86: "阵雪",
       95: "雷阵雨", 96: "雷阵雨", 99: "雷冰雹"}
WEEK = "一二三四五六日"


def font(size, index=0):
    last = None
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size, index=index)
        except Exception as e:
            last = e
            for idx in (1, 2, 3):
                try:
                    return ImageFont.truetype(path, size, index=idx)
                except Exception:
                    pass
    raise RuntimeError("找不到中文字体: %s" % last)


def fetch():
    url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
           "&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m"
           "&daily=weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,precipitation_probability_max"
           "&timezone=auto&forecast_days=3") % (LAT, LON)
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            j = json.load(r)
        data = {"current": j["current"], "daily": j["daily"],
                "fetched": datetime.now().strftime("%Y-%m-%d %H:%M")}
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data, True
    except Exception as e:
        if os.path.exists(CACHE):
            with open(CACHE, encoding="utf-8") as f:
                return json.load(f), False
        raise RuntimeError("天气拉取失败且无缓存: %s" % e)


def icon_kind(code):
    if code in (0, 1):
        return "sun"
    if code == 2:
        return "suncloud"
    if code == 3:
        return "cloud"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77 or 85 <= code <= 86:
        return "snow"
    if 95 <= code <= 99:
        return "storm"
    return "cloud"


def draw_sun(img, cx, cy, r, lw):
    d = ImageDraw.Draw(img)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=BLACK, width=lw)
    for i in range(8):
        a = math.radians(i * 45)
        x1, y1 = cx + (r + 8) * math.cos(a), cy + (r + 8) * math.sin(a)
        x2, y2 = cx + (r + 22) * math.cos(a), cy + (r + 22) * math.sin(a)
        d.line([(x1, y1), (x2, y2)], fill=BLACK, width=lw)


def draw_cloud(img, cx, cy, s, lw):
    """蒙版法：云 = 三圆 + 底部矩形 的并集，先填白遮住下层，再只描外轮廓。"""
    W, H = img.size
    m = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(m)
    r = s * 0.34
    md.ellipse([cx - s * 0.62, cy - r * 0.75, cx - s * 0.62 + 2 * r, cy - r * 0.75 + 2 * r], fill=255)
    md.ellipse([cx - s * 0.16, cy - r * 1.55, cx - s * 0.16 + 2.3 * r, cy - r * 1.55 + 2.3 * r], fill=255)
    md.ellipse([cx + s * 0.30, cy - r * 0.80, cx + s * 0.30 + 1.9 * r, cy - r * 0.80 + 1.9 * r], fill=255)
    md.rectangle([cx - s * 0.62, cy + r * 0.15, cx + s * 0.72, cy + r * 0.95], fill=255)
    outer = m.filter(ImageFilter.MaxFilter(2 * lw + 1))
    ring = ImageChops.subtract(outer, m)          # 只留外圈描边
    white = Image.new("L", (W, H), WHITE)
    black = Image.new("L", (W, H), BLACK)
    img.paste(white, (0, 0), m)                   # 云内部纯白
    img.paste(black, (0, 0), ring)                # 云轮廓纯黑


def draw_icon(img, kind, cx, cy, s, lw=5):
    d = ImageDraw.Draw(img)
    if kind == "sun":
        draw_sun(img, cx, cy, s * 0.42, lw)
    elif kind == "suncloud":
        draw_sun(img, cx - s * 0.38, cy - s * 0.34, s * 0.26, lw)
        draw_cloud(img, cx + s * 0.12, cy + s * 0.16, s * 0.78, lw)
    elif kind == "cloud":
        draw_cloud(img, cx, cy, s * 0.95, lw)
    elif kind == "fog":
        draw_cloud(img, cx, cy - s * 0.20, s * 0.80, lw)
        d = ImageDraw.Draw(img)
        for i in range(3):
            yy = cy + s * 0.48 + i * s * 0.17
            d.line([(cx - s * 0.55, yy), (cx + s * 0.55 - i * s * 0.12, yy)], fill=BLACK, width=lw)
    elif kind == "rain":
        draw_cloud(img, cx, cy - s * 0.20, s * 0.80, lw)
        d = ImageDraw.Draw(img)
        for i in range(4):
            x = cx - s * 0.40 + i * s * 0.26
            d.line([(x, cy + s * 0.40), (x - s * 0.10, cy + s * 0.76)], fill=BLACK, width=lw)
    elif kind == "snow":
        draw_cloud(img, cx, cy - s * 0.20, s * 0.80, lw)
        d = ImageDraw.Draw(img)
        for i in range(4):
            x = cx - s * 0.40 + i * s * 0.26
            yy = cy + s * 0.58
            d.line([(x - 8, yy), (x + 8, yy)], fill=BLACK, width=lw)
            d.line([(x, yy - 8), (x, yy + 8)], fill=BLACK, width=lw)
    elif kind == "storm":
        draw_cloud(img, cx, cy - s * 0.22, s * 0.80, lw)
        d = ImageDraw.Draw(img)
        d.line([(cx + s * 0.06, cy + s * 0.32), (cx - s * 0.14, cy + s * 0.58),
                (cx + s * 0.04, cy + s * 0.58), (cx - s * 0.12, cy + s * 0.88)],
               fill=BLACK, width=lw + 2, joint="curve")


def text_r(d, xy, s, f, fill=BLACK):
    """右对齐绘制"""
    b = d.textbbox((0, 0), s, font=f)
    d.text((xy[0] - (b[2] - b[0]), xy[1]), s, font=f, fill=fill)


def text_c(d, cx, y, s, f, fill=BLACK):
    b = d.textbbox((0, 0), s, font=f)
    d.text((cx - (b[2] - b[0]) / 2, y), s, font=f, fill=fill)


def render(data, w, h, live):
    img = Image.new("L", (w, h), WHITE)
    d = ImageDraw.Draw(img)
    sx, sy = w / 758.0, h / 1024.0  # 高分屏缩放
    def S(v): return int(v * sx)
    def T(v): return int(v * sy)
    c = data["current"]
    dl = data["daily"]
    fetched = data.get("fetched", "")

    # ===== 顶部黑标题栏 =====
    bar = T(112)
    d.rectangle([0, 0, w, bar], fill=BLACK)
    d.text((S(36), T(16)), CITY, font=font(T(46)), fill=WHITE)
    stamp = data.get("fetched", "")[:10]
    try:
        wd = "周" + WEEK[datetime.strptime(stamp, "%Y-%m-%d").weekday()]
    except Exception:
        wd = ""
    d.text((S(38), T(72)), "天气预报  %s %s" % (stamp, wd), font=font(T(26)), fill=WHITE)

    # ===== 当前实况 =====
    temp = round(c["temperature_2m"])
    d.text((S(30), T(140)), str(temp), font=font(T(196)), fill=BLACK)
    tb = d.textbbox((0, 0), str(temp), font=font(T(196)))
    d.text((S(36) + (tb[2] - tb[0]), T(170)), "°", font=font(T(84)), fill=BLACK)
    cur_wx = WMO.get(c["weather_code"], "—")
    draw_icon(img, icon_kind(c["weather_code"]), S(600), T(210), S(140), lw=max(4, S(5)))
    text_c(d, S(600), T(304), cur_wx, font(T(38)))
    detail = "体感 %s°   湿度 %s%%   风 %s km/h" % (
        round(c["apparent_temperature"]), c["relative_humidity_2m"], round(c["wind_speed_10m"]))
    d.text((S(36), T(352)), detail, font=font(T(28)), fill=BLACK)
    d.line([(S(36), T(404)), (w - S(36), T(404))], fill=BLACK, width=max(2, S(3)))

    # ===== 三天预报 =====
    d.text((S(36), T(420)), "最近三天", font=font(T(36)), fill=BLACK)
    names = ["今天", "明天", "后天"]
    row_y = [T(486), T(626), T(766)]
    for i in range(3):
        y = row_y[i]
        dt = datetime.strptime(dl["time"][i], "%Y-%m-%d")
        label = "%s  %d/%d" % (names[i], dt.month, dt.day)
        d.text((S(36), y + T(14)), label, font=font(T(40)), fill=BLACK)
        d.text((S(38), y + T(70)), "周" + WEEK[dt.weekday()], font=font(T(26)), fill=GRAY)

        draw_icon(img, icon_kind(dl["weather_code"][i]), S(320), y + T(48), S(74), lw=max(3, S(4)))
        d = ImageDraw.Draw(img)
        d.text((S(400), y + T(30)), WMO.get(dl["weather_code"][i], "—"), font=font(T(34)), fill=BLACK)
        pop = dl.get("precipitation_probability_max", [None] * 3)[i]
        d.text((S(400), y + T(78)), "降水 %s%%" % (pop if pop is not None else "—"),
               font=font(T(24)), fill=GRAY)

        hi, lo = round(dl["temperature_2m_max"][i]), round(dl["temperature_2m_min"][i])
        text_r(d, (w - S(36), y + T(8)), "%d° / %d°" % (hi, lo), font(T(52)))
        d.line([(S(36), y + T(126)), (w - S(36), y + T(126))], fill=GRAY, width=max(1, S(2)))

    # ===== 底部信息 =====
    d.line([(S(36), T(910)), (w - S(36), T(910))], fill=BLACK, width=max(2, S(3)))
    sr = dl["sunrise"][0][-5:]
    ss = dl["sunset"][0][-5:]
    d.text((S(36), T(924)), "日出 %s   日落 %s" % (sr, ss), font=font(T(28)), fill=BLACK)
    d.text((S(36), T(962)), "更新 %s · 数据 Open-Meteo%s" % (fetched, "" if live else " (缓存)"),
           font=font(T(22)), fill=GRAY)
    d.text((S(36), T(992)), "熄屏为静态快照，连电脑可刷新", font=font(T(20)), fill=GRAY)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--w", type=int, default=758)
    ap.add_argument("--h", type=int, default=1024)
    ap.add_argument("--out", default=os.path.join(DIR, "weather_screensaver.png"))
    args = ap.parse_args()
    data, live = fetch()
    img = render(data, args.w, args.h, live)
    img.save(args.out)
    print("已生成 %s (%dx%d, %s数据)" % (args.out, args.w, args.h, "实时" if live else "缓存"))


if __name__ == "__main__":
    main()
