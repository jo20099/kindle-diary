#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_kindle.py — 把「雪碧的成长日记」云端数据同步到 Kindle 信息屏仓库。

数据来源：public_family_snapshot(<分享码>) 返回的快照 JSON（含 homework / custom_tasks /
task_logs / praise）。该快照可由云端数据库工具读取后存为 snapshot.json 传入本脚本。

映射规则：
  - homework        -> days[date].homework    （科目：内容，换行转空格，空内容跳过）
  - custom_tasks    -> days[date].checklist   （未归档任务；当天有打卡量则附「（今日N）」）
  - praise (A+/表扬) -> days[date].diary      （落到底部「成长日记」区，标注在校表现）
  - 原有 weather / 顶部标题等：从仓库现有 data.json 合并保留，只更新 days。

用法：
  python3 sync_kindle.py snapshot.json
需环境变量 GITHUB_TOKEN（对 jo20099/kindle-diary 有 Contents 读写权限）。
"""
import sys, json, base64, os, re, time, urllib.request, urllib.error

REPO = "jo20099/kindle-diary"
PATH = "data.json"
BRANCH = "main"
SUBJ = {"chinese": "语文", "math": "数学", "english": "英语"}

# ---- 历史上的今天：来自 GitHub 公开数据集 PrintNow/TodayInHistory ----
HISTORY_URL = "https://raw.githubusercontent.com/PrintNow/TodayInHistory/master/history_in_today.json"
HISTORY_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_hot_cache.json")
HISTORY_MAX_AGE = 30 * 86400  # 30 天刷新一次（内容基本不变）

# 判断历史事件是否与中国/华人相关（方案A+：在 type=1 中优先展示涉华事件）。
# 用词尽量"中国专属"，避免"皇帝""王朝"等在国际史也出现的通用词造成误判。
CN_KW = [
    "中国","中华","华夏","神州","九州","中土",
    "北京","上海","天津","重庆","广州","深圳","南京","西安","杭州","成都","武汉",
    "苏州","无锡","宁波","福州","厦门","昆明","贵阳","拉萨","乌鲁木齐","银川","西宁",
    "兰州","南昌","长沙","郑州","合肥","太原","石家庄","南宁","海口","呼和浩特","台北",
    "广东","广西","四川","湖北","湖南","山东","山西","河南","河北","江苏","浙江","福建",
    "安徽","江西","陕西","云南","贵州","甘肃","青海","辽宁","吉林","黑龙江","海南",
    "西藏","新疆","内蒙古","宁夏","澳门",
    "清朝","清代","明朝","明代","唐朝","唐代","宋朝","宋代","秦朝","秦代","汉朝","汉代",
    "元朝","元代","隋朝","隋代","晋朝","晋代","周朝","周代","三国时期","三国时代","蜀汉","曹魏","孙吴",
    "辽朝","辽国","金朝","金国","西夏","南北朝","五代十国",
    "秦始皇","汉武帝","唐太宗","武则天","成吉思汗","康熙","乾隆","慈禧","诸葛亮","关羽",
    "岳飞","文天祥","郑和","郑成功","孔子","老子","孟子","李白","杜甫","苏轼","白居易",
    "王羲之","司马迁","祖冲之","张衡","李时珍","孙武","庄子","墨子",
    "毛泽东","蒋介石","孙中山","周恩来","邓小平","国民党","共产党","红军","解放军",
    "八路军","新四军","故宫","长城","黄河","长江","珠江","京杭","丝绸之路","兵马俑",
    "莫高窟","黄山","泰山","抗战","甲午","鸦片战争","义和团","太平天国","辛亥","长征",
    "北伐","西安事变","九一八","七七","南京大屠杀","抗日战争","科举","翰林","状元","进士",
]

def load_history():
    """返回全量历史事件 list；优先用本地缓存，失败则联网拉取，再失败回退缓存。"""
    if os.path.exists(HISTORY_CACHE) and (time.time() - os.path.getmtime(HISTORY_CACHE)) < HISTORY_MAX_AGE:
        try:
            return json.load(open(HISTORY_CACHE, encoding="utf-8"))
        except Exception:
            pass
    try:
        req = urllib.request.Request(HISTORY_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=45) as r:
            data = json.loads(r.read().decode("utf-8"))
        try:
            json.dump(data, open(HISTORY_CACHE, "w", encoding="utf-8"))
        except Exception:
            pass
        return data
    except Exception:
        if os.path.exists(HISTORY_CACHE):
            try:
                return json.load(open(HISTORY_CACHE, encoding="utf-8"))
            except Exception:
                pass
        return None

def history_for(month, day, data):
    """取某月某日的历史事件文本，拼接成一句「历史上的今天」。

    方案A+：仅取 type=1 历史事件（过滤人物生卒 type2/type3）；在历史事件中
    **优先展示与中国/华人相关的事件**，涉华不足时再用外国事件补齐，让孩子
    看到的更多是本国历史。仍不显示纯人物生卒。"""
    if not data:
        return ""
    m, d = str(month), str(day)
    cn_items, other_items = [], []
    for x in data:
        # 仅保留历史事件，剔除名人出生/逝世等纯人物条目
        if str(x.get("type")) != "1":
            continue
        if str(x.get("month")) == m and str(x.get("day")) == d:
            t = (x.get("data") or "").strip()
            t = t.rstrip("。；;！!？?")  # 去掉末尾标点，统一在句尾加。
            y = (x.get("year") or "").strip()
            if t:
                item = (y, t)
                if any(k in t for k in CN_KW):
                    cn_items.append(item)
                else:
                    other_items.append(item)
    if not cn_items and not other_items:
        return ""
    # 优先涉华，不足 2 条时用外国事件补齐
    picked = (cn_items + other_items)[:2]
    parts = []
    for y, t in picked:
        try:
            yi = int(y)
            ylabel = ("公元前" + str(-yi) + "年") if yi < 0 else (str(yi) + "年")
        except Exception:
            ylabel = ""
        parts.append((ylabel + " " + t).strip() if ylabel else t)
    return "📜 历史上的今天：" + "；".join(parts) + "。"

def dkey(d):
    """把各种日期格式归一为 YYYY-MM-DD。"""
    if d is None:
        return ""
    s = str(d)
    return s[:10]

def transform(snap):
    days = {}

    def day(d):
        d = dkey(d)
        return days.setdefault(d, {"homework": [], "checklist": [], "diary": ""})

    # 1) 作业
    for h in snap.get("homework", []) or []:
        content = (h.get("content") or "").replace("\n", " ").strip()
        if not content:
            continue
        subj = SUBJ.get(h.get("subject"), h.get("subject") or "")
        day(h.get("record_date"))["homework"].append(f"{subj}：{content}")

    # 2) 自定义任务 -> 打卡清单；按当天 task_log 标注进度
    logs = {}  # task_id -> {date: qty}
    for l in snap.get("task_logs", []) or []:
        logs.setdefault(l.get("task_id"), {})[dkey(l.get("log_date"))] = l.get("qty") or 0
    for t in snap.get("custom_tasks", []) or []:
        name = (t.get("title") or t.get("name") or "任务").strip()
        if not name:
            continue
        tid = t.get("id")
        qtys = logs.get(tid, {})
        # 出现在：有作业/表扬的日期，以及该任务有打卡记录的日期
        dates = set(dkey(h.get("record_date")) for h in snap.get("homework", []) or [])
        dates |= set(dkey(p.get("record_date")) for p in snap.get("praise", []) or [])
        dates |= set(qtys.keys())
        for d in dates:
            qty = qtys.get(d, 0)
            label = name + (f"（今日{qty}）" if qty else "")
            chk = day(d)["checklist"]
            if label not in chk:
                chk.append(label)

    # 3) 表扬 -> 成长日记（底部区）
    bydate = {}
    for p in snap.get("praise", []) or []:
        d = dkey(p.get("record_date"))
        info = bydate.setdefault(d, {"aplus": 0, "written": []})
        if p.get("ptype") == "aplus":
            info["aplus"] += 1
        elif p.get("ptype") == "written":
            note = (p.get("note") or "").strip()
            note = re.sub(r"^(表扬|书面表扬|口头表扬)[：: ]*", "", note)  # 去掉与分类重复的前缀
            if note:
                info["written"].append(note)
    for d, info in bydate.items():
        parts = []
        if info["aplus"]:
            parts.append(f"A+ ×{info['aplus']}")
        if info["written"]:
            parts.append("书面表扬 ×" + str(len(info["written"])) + "（" + "；".join(info["written"]) + "）")
        if parts:
            day(d)["diary"] = "在校表现：" + "；".join(parts)

    return days

def github_get(token):
    url = f"https://api.github.com/repos/{REPO}/contents/{PATH}?ref={BRANCH}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise

def github_put(token, content_b64, sha):
    url = f"https://api.github.com/repos/{REPO}/contents/{PATH}"
    body = {
        "message": "sync: update days from 雪碧的成长日记",
        "content": content_b64,
        "branch": BRANCH,
    }
    if sha:
        body["sha"] = sha
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    }, method="PUT")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode("utf-8")

def main():
    if len(sys.argv) < 2:
        print("usage: python3 sync_kindle.py snapshot.json"); sys.exit(2)
    with open(sys.argv[1], encoding="utf-8") as f:
        snap = json.load(f)
    if isinstance(snap, list):
        snap = snap[0] if snap else {}
    # 兼容 public_family_snapshot 的返回结构：[{"public_family_snapshot": {...}}]
    if isinstance(snap, dict) and "public_family_snapshot" in snap:
        snap = snap["public_family_snapshot"]
    if not snap.get("ok"):
        print("snapshot 状态异常（ok != true），未同步。", file=sys.stderr); sys.exit(1)

    new_days = transform(snap)

    # 成长日记为空时，按日期补「历史上的今天」
    try:
        hist = load_history()
        for date, v in new_days.items():
            if not v.get("diary"):
                try:
                    _, mm, dd = date.split("-")
                    htext = history_for(int(mm), int(dd), hist)
                    if htext:
                        v["diary"] = htext
                except Exception:
                    pass
    except Exception:
        pass

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        # 兼容：本地 .github_token 文件（与脚本同目录）
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".github_token"), encoding="utf-8") as f:
                token = f.read().strip()
        except Exception:
            token = None
    if not token:
        # 无 token 时只输出结果，便于本地验证
        print(json.dumps({"days": new_days}, ensure_ascii=False, indent=2))
        return

    existing = github_get(token)
    if existing:
        cur = json.loads(base64.b64decode(existing["content"]).decode("utf-8"))
        cur_days = cur.get("days", {}) or {}
        # 按日期合并：sprite 每日数据为主，覆盖同名日期；保留 Kindle 独有日期（如手动录入）
        for d, v in new_days.items():
            cur_days[d] = v
        cur["days"] = cur_days
        new_data = cur
        sha = existing.get("sha")
    else:
        new_data = {"days": new_days}
        sha = None

    content_b64 = base64.b64encode(
        json.dumps(new_data, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("ascii")
    status, resp = github_put(token, content_b64, sha)
    print(f"github commit: HTTP {status}")
    print(resp[:300])

if __name__ == "__main__":
    main()
