/**
 * Cloudflare Worker：雪碧日记 → Kindle 屏 数据中转
 *
 * 作用：Kindle 页面（公网）无法直连云端快照接口（有 Origin 白名单，带浏览器 Origin 一律 403），
 *      由这个 Worker 在服务端带 key 拉快照，转换成与 data.json 同结构的数据，加 CORS 返回。
 * 部署：Cloudflare 控制台 → Workers & Pages → Create Worker → 粘贴本文件 → Deploy。
 *      部署后得到一个 https://<名字>.<账号>.workers.dev 地址，填进 index.html 的 WORKER_URL。
 *
 * 页面用法：
 *   GET  /                  → {"days": {...}, "generatedAt": "..."}
 *   GET  /?raw=1            → 原始快照（排查用）
 */

const SNAPSHOT_URL = 'https://sprite-diary.app.workbuddy.host/.cloud/database/rest/rpc/public_family_snapshot';
const ACCESS_KEY = 'wbpk_TqAAsuPoi1djlCKK73zp3v_v6fnHLZ75eshBQfV5k1VtvyutiGW74Xb';
const HISTORY_URL = 'https://jo20099.github.io/kindle-diary/data.json';  // 历史日期兜底（快照只覆盖近 15 天）

const SUBJ = { chinese: '语文', math: '数学', english: '英语' };
const ORDER = ['chinese', 'math', 'english'];   // Kindle 屏固定 语文 → 数学 → 英语
const STATUS = { todo: 1, done: 1, corrected: 1 };

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': '*',
  'Cache-Control': 'no-store',
};

const dkey = (d) => (d == null ? '' : String(d).slice(0, 10));

function buildDays(snap) {
  const days = {};
  const day = (d) => {
    const k = dkey(d);
    if (!days[k]) days[k] = { homework: [], checklist: [], diary: '' };
    return days[k];
  };

  // 1) 作业 + 三科状态
  for (const h of snap.homework || []) {
    const content = String(h.content || '').replace(/\n/g, ' ').trim();
    const sk = h.subject || '';
    const subj = SUBJ[sk] || sk;
    const d = day(h.record_date);
    if (content) {
      const rank = ORDER.indexOf(sk);
      if (!d._hw) d._hw = [];
      d._hw.push({ r: rank < 0 ? 90 : rank, i: d._hw.length, t: subj + '：' + content });
    }
    if (SUBJ[sk]) {
      const st = h.status || 'todo';
      if (!d.hwStatus) d.hwStatus = {};
      d.hwStatus[sk] = STATUS[st] ? st : 'todo';
    }
  }
  for (const k in days) {
    const d = days[k];
    if (d._hw) {
      d._hw.sort((a, b) => (a.r - b.r) || (a.i - b.i));
      d.homework = d._hw.map((x) => x.t);
      delete d._hw;
    }
  }

  // 2) 自定义任务 → 打卡清单
  const logs = {};
  for (const l of snap.task_logs || []) {
    if (!logs[l.task_id]) logs[l.task_id] = {};
    logs[l.task_id][dkey(l.log_date)] = l.qty || 0;
  }
  const base = new Set();
  for (const h of snap.homework || []) base.add(dkey(h.record_date));
  for (const p of snap.praise || []) base.add(dkey(p.record_date));

  for (const t of snap.custom_tasks || []) {
    const name = String(t.title || t.name || '任务').trim();
    if (!name) continue;
    const qtys = logs[t.id] || {};
    const dates = new Set(base);
    for (const k in qtys) dates.add(k);
    for (const d of dates) {
      const qty = qtys[d] || 0;
      const label = name + (qty ? '（今日' + qty + '）' : '');
      const chk = day(d).checklist;
      if (chk.indexOf(label) < 0) chk.push(label);
    }
  }

  // 3) 表扬 → 成长日记
  const bydate = {};
  for (const p of snap.praise || []) {
    const d = dkey(p.record_date);
    if (!bydate[d]) bydate[d] = { aplus: 0, written: [] };
    const info = bydate[d];
    if (p.ptype === 'aplus') info.aplus++;
    else if (p.ptype === 'written') {
      const note = String(p.note || '').trim().replace(/^(表扬|书面表扬|口头表扬)[：: ]*/, '');
      if (note) info.written.push(note);
    }
  }
  for (const d in bydate) {
    const info = bydate[d], parts = [];
    if (info.aplus) parts.push('A+ ×' + info.aplus);
    if (info.written.length) parts.push('书面表扬 ×' + info.written.length + '（' + info.written.join('；') + '）');
    if (parts.length) day(d).diary = '在校表现：' + parts.join('；');
  }

  return days;
}

function mergeHistory(days, history) {
  const old = (history && history.days) || {};
  for (const d in old) {
    if (!days[d]) { days[d] = old[d]; continue; }
    if (!days[d].diary && old[d] && old[d].diary) days[d].diary = old[d].diary;
  }
  return days;
}

function json(obj, status, extra) {
  return new Response(JSON.stringify(obj), {
    status: status || 200,
    headers: Object.assign({ 'Content-Type': 'application/json; charset=utf-8' }, CORS, extra || {}),
  });
}

export default {
  async fetch(req) {
    if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: CORS });
    try {
      const r = await fetch(SNAPSHOT_URL + '?p_code=KINDLE', {
        headers: { 'x-wb-webapp-access-key': ACCESS_KEY },
        cf: { cacheTtl: 0 },
      });
      if (!r.ok) return json({ error: 'snapshot HTTP ' + r.status }, 502);
      const snap = await r.json();
      if (new URL(req.url).searchParams.get('raw')) return json(snap, 200);
      if (!snap || !snap.ok) return json({ error: 'snapshot ok != true' }, 502);

      const days = buildDays(snap);

      // 历史兜底：快照只覆盖近 15 天，更早的日期从线上 data.json 补齐（失败不影响主流程）
      try {
        const hr = await fetch(HISTORY_URL + '?t=' + Date.now(), { cf: { cacheTtl: 0 } });
        if (hr.ok) mergeHistory(days, await hr.json());
      } catch (e) { /* 忽略 */ }

      return json({ days, generatedAt: new Date().toISOString() });
    } catch (e) {
      return json({ error: String(e) }, 502);
    }
  },
};
