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
import re
import time
import urllib.request
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageFilter

DIR = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(DIR, "weather_cache.json")
LAT, LON = 23.1248, 113.3616
CITY = "广州市天河区"

# ---- 历史上的今天：来自 GitHub 公开数据集 PrintNow/TodayInHistory ----
# 该文件是约 4MB 的扁平 JSON，且个别条目含非法 \u 转义，严格 json.load 会崩。
# 故改用「按日期正则抽取当日条目 + 逐条解析」的稳健方式，坏条目直接跳过。
HISTORY_URL = "https://raw.githubusercontent.com/PrintNow/TodayInHistory/master/history_in_today.json"
HISTORY_CACHE = os.path.join(DIR, "_history_cache.json")
HISTORY_MAX_AGE = 30 * 86400  # 30 天刷新一次（内容基本不变）
HIST_PAT = re.compile(
    r'\{"year":"(-?\d+)","month":"(\d+)","day":"(\d+)","type":(\d+),"data":"((?:[^"\\]|\\.)*)"\}')
CN_KW = [
    "中国", "中华", "华夏", "神州", "九州", "中土",
    "北京", "上海", "天津", "重庆", "广州", "深圳", "南京", "西安", "杭州", "成都", "武汉",
    "苏州", "无锡", "宁波", "福州", "厦门", "昆明", "贵阳", "拉萨", "乌鲁木齐", "银川", "西宁",
    "兰州", "南昌", "长沙", "郑州", "合肥", "太原", "石家庄", "南宁", "海口", "呼和浩特", "台北",
    "广东", "广西", "四川", "湖北", "湖南", "山东", "山西", "河南", "河北", "江苏", "浙江", "福建",
    "安徽", "江西", "陕西", "云南", "贵州", "甘肃", "青海", "辽宁", "吉林", "黑龙江", "海南",
    "西藏", "新疆", "内蒙古", "宁夏", "澳门",
    "清朝", "清代", "明朝", "明代", "唐朝", "唐代", "宋朝", "宋代", "秦朝", "秦代", "汉朝", "汉代",
    "元朝", "元代", "隋朝", "隋代", "晋朝", "晋代", "周朝", "周代", "三国时期", "三国时代", "蜀汉", "曹魏", "孙吴",
    "辽朝", "辽国", "金朝", "金国", "西夏", "南北朝", "五代十国",
    "秦始皇", "汉武帝", "唐太宗", "武则天", "成吉思汗", "康熙", "乾隆", "慈禧", "诸葛亮", "关羽",
    "岳飞", "文天祥", "郑和", "郑成功", "孔子", "老子", "孟子", "李白", "杜甫", "苏轼", "白居易",
    "王羲之", "司马迁", "祖冲之", "张衡", "李时珍", "孙武", "庄子", "墨子",
    "毛泽东", "蒋介石", "孙中山", "周恩来", "邓小平", "国民党", "共产党", "红军", "解放军",
    "八路军", "新四军", "故宫", "长城", "黄河", "长江", "珠江", "京杭", "丝绸之路", "兵马俑",
    "莫高窟", "黄山", "泰山", "抗战", "甲午", "鸦片战争", "义和团", "太平天国", "辛亥", "长征",
    "北伐", "西安事变", "九一八", "七七", "南京大屠杀", "抗日战争", "科举", "翰林", "状元", "进士",
]

FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",                       # macOS
    "/System/Library/Fonts/STHeiti Light.ttc",                  # macOS
    "/System/Library/Fonts/Hiragino Sans GB.ttc",               # macOS
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",   # Linux CI / Ubuntu
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",            # Linux 文泉驿
]
BLACK, WHITE, GRAY = 0, 255, 150

WMO = {0: "晴", 1: "晴", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
       51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨", 56: "冻雨", 57: "冻雨",
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


def load_history_text():
    """返回历史事件 JSON 原始文本；优先本地缓存，失败联网拉取，再失败回退缓存。"""
    if os.path.exists(HISTORY_CACHE) and (time.time() - os.path.getmtime(HISTORY_CACHE)) < HISTORY_MAX_AGE:
        try:
            return open(HISTORY_CACHE, encoding="utf-8").read()
        except Exception:
            pass
    try:
        req = urllib.request.Request(HISTORY_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            txt = r.read().decode("utf-8")
        try:
            open(HISTORY_CACHE, "w", encoding="utf-8").write(txt)
        except Exception:
            pass
        return txt
    except Exception:
        if os.path.exists(HISTORY_CACHE):
            try:
                return open(HISTORY_CACHE, encoding="utf-8").read()
            except Exception:
                pass
        return ""


def history_for(month, day):
    """取某月某日的历史事件，返回事件字符串列表（每条独立成行，含末尾句号）。

    仅取 type=1 历史事件（剔除人物生卒），优先涉华事件，不足则外国补齐。
    整文件有非法 \\u 转义，故按日期正则抽取当日条目、逐条解析，坏条目跳过。"""
    txt = load_history_text()
    if not txt:
        return ""
    m, d = str(month), str(day)
    cn, other = [], []
    for mm in HIST_PAT.finditer(txt):
        y, mo, dd, ty, data = mm.groups()
        if mo != m or dd != d or ty != "1":
            continue
        try:
            t = json.loads('{"data":"%s"}' % data)["data"]
        except Exception:
            # 个别条目含非法转义，手工解码可用的 \uXXXX，仍有残留则跳过该条
            t = re.sub(r"\\u([0-9a-fA-F]{4})", lambda x: chr(int(x.group(1), 16)), data)
            t = t.replace('\\"', '"').replace("\\/", "/").replace("\\\\", "\\")
            if "\\u" in t:
                continue
        t = t.strip().rstrip("。；;！!？?")
        if not t:
            continue
        item = (y, t)
        if any(k in t for k in CN_KW):
            cn.append(item)
        else:
            other.append(item)
    if not cn and not other:
        return []
    # 选取策略：涉华优先、同池内短的优先；贪心凑 3 条，总长控制在三行预算内，
    # 给「历史上的今天」更大展示空间（约 27 字/行 × 3 行，扣除分隔符）
    budget = 75
    cand = sorted(cn, key=lambda x: len(x[1])) + sorted(other, key=lambda x: len(x[1]))
    picked, used = [], 0
    for y, t in cand:
        if len(picked) >= 3:
            break
        add = len(t) + (1 if picked else 0)
        if used + add <= budget:
            picked.append((y, t))
            used += add
    if not picked and cand:
        y, t = cand[0]
        picked = [(y, t[:budget] + "…")]
    parts = []
    for y, t in picked:
        try:
            yi = int(y)
            yl = ("公元前" + str(-yi) + "年") if yi < 0 else (str(yi) + "年")
        except Exception:
            yl = ""
        parts.append((yl + " " + t).strip() if yl else t)
    if parts:
        parts[-1] = parts[-1] + "。"   # 末尾句号
    return parts   # 返回事件列表，每条独立成行


def wrap_text(d, text, f, max_w):
    """中文按字符折行（无空格），返回行列表。"""
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if d.textlength(cur + ch, font=f) <= max_w:
            cur += ch
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


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
    d.text((S(30), T(122)), str(temp), font=font(T(196)), fill=BLACK)
    tb = d.textbbox((0, 0), str(temp), font=font(T(196)))
    d.text((S(36) + (tb[2] - tb[0]), T(152)), "°", font=font(T(84)), fill=BLACK)
    cur_wx = WMO.get(c["weather_code"], "—")
    draw_icon(img, icon_kind(c["weather_code"]), S(600), T(204), S(140), lw=max(4, S(5)))
    text_c(d, S(600), T(298), cur_wx, font(T(38)))
    detail = "体感 %s°   湿度 %s%%   风 %s km/h" % (
        round(c["apparent_temperature"]), c["relative_humidity_2m"], round(c["wind_speed_10m"]))
    d.text((S(36), T(358)), detail, font=font(T(28)), fill=BLACK)
    d.line([(S(36), T(408)), (w - S(36), T(408))], fill=BLACK, width=max(2, S(3)))

    # ===== 三天预报（今天/明天/后天 自带标签，无需标题） =====
    names = ["今天", "明天", "后天"]
    row_y = [T(460), T(580), T(700)]
    for i in range(3):
        y = row_y[i]
        dt = datetime.strptime(dl["time"][i], "%Y-%m-%d")
        label = "%s  %d/%d" % (names[i], dt.month, dt.day)
        d.text((S(36), y + T(12)), label, font=font(T(38)), fill=BLACK)
        d.text((S(38), y + T(66)), "周" + WEEK[dt.weekday()], font=font(T(25)), fill=GRAY)

        draw_icon(img, icon_kind(dl["weather_code"][i]), S(320), y + T(46), S(70), lw=max(3, S(4)))
        d = ImageDraw.Draw(img)
        d.text((S(400), y + T(28)), WMO.get(dl["weather_code"][i], "—"), font=font(T(32)), fill=BLACK)
        pop = dl.get("precipitation_probability_max", [None] * 3)[i]
        d.text((S(400), y + T(74)), "降水 %s%%" % (pop if pop is not None else "—"),
               font=font(T(23)), fill=GRAY)

        hi, lo = round(dl["temperature_2m_max"][i]), round(dl["temperature_2m_min"][i])
        text_r(d, (w - S(36), y + T(6)), "%d° / %d°" % (hi, lo), font(T(48)))
        if i < 2:   # 后天行下方不画灰线，由历史块的黑粗分隔线接替
            d.line([(S(36), y + T(116)), (w - S(36), y + T(116))], fill=GRAY, width=max(1, S(2)))

    # ===== 历史上的今天（屏保展示） =====
    try:
        today_dt = datetime.strptime(dl["time"][0], "%Y-%m-%d")
        hist = history_for(today_dt.month, today_dt.day)
    except Exception:
        hist = ""

    # ===== 历史上的今天（独立区块，更大空间） =====
    d.line([(S(36), T(824)), (w - S(36), T(824))], fill=BLACK, width=max(2, S(3)))
    y = T(834)
    d.text((S(36), y), "历史上的今天", font=font(T(32)), fill=BLACK)
    y += T(40)
    if hist:
        hf = font(T(32))
        lines = []
        for ev in hist:
            # 每条历史事件独立换行；超 3 行则停止，保证不越界
            wl = wrap_text(d, ev, hf, w - 2 * S(36))
            if lines and len(lines) + len(wl) > 3:
                break
            lines.extend(wl)
            if len(lines) >= 3:
                break
        for ln in lines[:3]:
            d.text((S(36), y), ln, font=hf, fill=BLACK)
            y += T(40)
        y += T(10)
    else:
        y += T(10)
    y = min(y, T(1000))   # 更新时间行保险上限，防止贴到 1024 底边被裁
    sr = dl["sunrise"][0][-5:]
    ss = dl["sunset"][0][-5:]
    upd = fetched[-5:] if len(fetched) >= 5 else fetched  # 只取 HH:MM
    d.text((S(36), y), "日出 %s   日落 %s   更新 %s%s" % (sr, ss, upd, "" if live else " (缓存)"),
           font=font(T(21)), fill=BLACK)
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
