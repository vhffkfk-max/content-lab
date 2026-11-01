// 연구소 커넥터 — ChatGPT·Claude 에 붙이는 MCP 서버 (Streamable HTTP, 상태 없음, 한 번 요청에 JSON 한 번 응답)
// 데이터: 깃허브 공개 저장소의 output/site/*.json (사이트와 같은 숫자, 읽기만)
// 사용 기록: 도구가 불릴 때마다 '언제·어느 앱·어느 도구·어느 추천 제목을 가져갔나'만 mcp-log 브랜치 log/YYYY-MM.json 에 남김.
//   대화 내용·검색어는 남기지 않음 (저장소가 공개라서). 기록은 usage_audit.py 가 읽어 활용 체크에 넣음.
// 환경변수: MCP_KEY(주소 끝 비밀 문자열, 기록 오염 방지) · GH_LOG_TOKEN(content-lab 저장소 Contents 쓰기, 없으면 기록만 건너뜀)

const REPO = 'vhffkfk-max/content-lab';
const RAW = `https://raw.githubusercontent.com/${REPO}/main/output/site/`;
const LOG_BRANCH = 'mcp-log';
const SERVER = { name: 'content-lab', title: '컨텐츠 연구소', version: '1.0.0' };
const PROTOCOLS = ['2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05'];

async function load(name) {
  try {
    const r = await fetch(RAW + name + '.json', { cache: 'no-store' });
    return r.ok ? await r.json() : null;
  } catch { return null; }
}

const line = (t, n = 80) => { const l = ((t || '').split('\n').find(x => x.trim()) || '').trim(); return l.length > n ? l.slice(0, n) + '…' : l; };

// 모든 추천을 한 목록으로: {id, src, channel, title, text, url}
async function items() {
  const [hn, recs, tg, trd, gp, thx] = await Promise.all(['hot_now', 'recs', 'tg_ai', 'trd_posts', 'growth_plan', 'thx_top'].map(load));
  const out = [];
  const h = Array.isArray(hn) ? hn[0] : null;
  (h?.picks || []).forEach((p, i) => out.push({ id: `hot-${i}`, src: '지금 발행할 거리', channel: p.channel, title: p.title,
    text: `${p.title}\n\n왜 지금: ${p.why_now}\n\n초안:\n${p.draft}`, url: (p.sources || [])[0], at: h.time }));
  (Array.isArray(recs) ? recs : []).slice(0, 8).forEach((r, i) => out.push({ id: `ig-${i}`, src: '인스타 추천', channel: '인스타 카드뉴스',
    title: r.title_idea || r.topic, text: `주제: ${r.topic}\n형식: ${r.format}\n첫 줄: ${r.hook}\n올릴 때: ${r.slot}\n근거: ${r.kind}, 국내 평균 ${r.kr_avg}배(${r.kr_n}개), 해외 ${r.foreign_avg}배(${r.foreign_n}개)` }));
  (tg?.today || []).forEach((t, i) => out.push({ id: `tg-${i}`, src: '텔레그램 문구', channel: '텔레그램 차트보는 말희아빠',
    title: `${(t.time || '').slice(0, 5)} ${t.type || ''} · ${line(t.text, 40)}`, text: `올릴 시간: ${t.time}\n종류: ${t.type}\n\n${t.text}` }));
  (tg?.formulas || []).forEach((f, i) => out.push({ id: `tgf-${i}`, src: '텔레그램 잘 되는 공식', channel: '텔레그램', title: f.name,
    text: `패턴: ${f.pattern}\n언제: ${f.when}\n예시:\n${f.example}` }));
  (trd?.posts || []).forEach((p, i) => out.push({ id: `trd-${i}`, src: '트레이더스 글', channel: `트레이더스 · ${p.room}`, title: p.title || line(p.text, 40),
    text: `방: ${p.room}\n시간: ${p.time}\n\n${p.text}` }));
  (gp?.hooks || []).forEach((k, i) => out.push({ id: `hook-${i}`, src: '코치 첫 줄 카피', channel: k.channel, title: k.text, text: `${k.text}\n\n원리: ${k.principle}` }));
  (gp?.experiments || []).forEach((e, i) => out.push({ id: `exp-${i}`, src: '코치 성장 실험', channel: e.channel, title: e.name,
    text: `가설: ${e.hypothesis}\n방법: ${e.how}\n지표: ${e.metric}\n기간: ${e.days}일` }));
  (Array.isArray(thx) ? thx : []).slice(0, 5).forEach((r, i) => out.push({ id: `thx-${i}`, src: '따라 할 쓰레드', channel: '쓰레드',
    title: line(r.text, 50), text: `@${r.username} · 조회 ${r.views} · 좋아요 ${r.likes}\n\n${r.text}`, url: r.url }));
  return out;
}

const show = it => `[${it.id}] ${it.src} · ${it.channel}\n${it.text}${it.url ? `\n근거: ${it.url}` : ''}`;

const TOOLS = [
  { name: 'lab_today', title: '지금 쓸 거리', description: '컨텐츠 연구소가 2시간마다(07~23시) 고른 지금 발행할 거리 3개(제목·채널·왜 지금·바로 쓸 초안). 경제 글을 쓰기 전에 먼저 부른다.',
    inputSchema: { type: 'object', properties: {} } },
  { name: 'lab_channel', title: '채널별 추천', description: '채널 하나의 오늘 추천 전부. 쓰레드(황소개미)·인스타(카드뉴스)·텔레그램(차트보는 말희아빠 채널 문구·공식)·트레이더스(유료방 방별 글).',
    inputSchema: { type: 'object', properties: { channel: { type: 'string', enum: ['쓰레드', '인스타', '텔레그램', '트레이더스'] } }, required: ['channel'] } },
  { name: 'lab_coach', title: '마케팅 코치', description: '이번 주 성장 계획: 막힌 곳, 성장 실험, 첫 줄 카피, 7일 계획.', inputSchema: { type: 'object', properties: {} } },
  { name: 'lab_my_stats', title: '내 성적', description: '황소개미 쓰레드 진단(팔로워·조회·등급)과 연구소 활용 체크(추천을 실제 글에 얼마나 썼나).', inputSchema: { type: 'object', properties: {} } },
  { name: 'search', title: '연구소 검색', description: '연구소 추천 전체에서 찾기(종목·주제·채널). 결과의 id 로 fetch 하면 전문이 나온다.',
    inputSchema: { type: 'object', properties: { query: { type: 'string' } }, required: ['query'] } },
  { name: 'fetch', title: '추천 전문', description: 'search 결과 id 하나의 전문(초안·근거).', inputSchema: { type: 'object', properties: { id: { type: 'string' } }, required: ['id'] } },
];
TOOLS.forEach(t => { t.annotations = { readOnlyHint: true, openWorldHint: false }; });

async function call(name, args) {
  if (name === 'lab_today') {
    const all = (await items()).filter(i => i.src === '지금 발행할 거리');
    return { text: all.length ? `지금 쓸 거리 (${all[0].at} 기준)\n\n` + all.map(show).join('\n\n---\n\n') : '지금 쓸 거리가 아직 없어요.', used: all };
  }
  if (name === 'lab_channel') {
    const ch = args.channel || '';
    const pick = {
      쓰레드: i => /쓰레드/.test(i.channel) || i.src === '따라 할 쓰레드',
      인스타: i => /인스타/.test(i.channel),
      텔레그램: i => i.src.startsWith('텔레그램') || (i.src === '지금 발행할 거리' && /텔레그램/.test(i.channel)),
      트레이더스: i => i.src === '트레이더스 글',
    }[ch];
    if (!pick) return { text: '채널은 쓰레드·인스타·텔레그램·트레이더스 중 하나예요.', used: [] };
    const all = (await items()).filter(pick);
    return { text: all.length ? all.map(show).join('\n\n---\n\n') : `${ch} 추천이 아직 없어요.`, used: all };
  }
  if (name === 'lab_coach') {
    const g = await load('growth_plan');
    if (!g || Array.isArray(g)) return { text: '마케팅 코치 계획이 아직 없어요.', used: [] };
    const t = [`이번 주 (${g.time})`, g.headline, `막힌 곳: ${g.bottleneck}`, `고칠 점: ${g.bottleneck_fix}`, '',
      '성장 실험:', ...(g.experiments || []).map(e => `- ${e.name} (${e.channel}, ${e.days}일): ${e.how} / 판정: ${e.metric}`), '',
      '첫 줄 카피:', ...(g.hooks || []).map(h => `- [${h.channel}] ${h.text}`), '',
      '7일 계획:', ...(g.calendar || []).map(c => `- ${c.day} ${c.channel}: ${c.idea} (${c.format})`)].join('\n');
    return { text: t, used: (g.experiments || []).slice(0, 1).map(e => ({ src: '코치 성장 실험', title: e.name })) };
  }
  if (name === 'lab_my_stats') {
    const [m, ai, u] = await Promise.all(['thm_meta', 'thm_ai', 'use_audit'].map(load));
    const meta = Array.isArray(m) ? m[0] || {} : {};
    const t = [`황소개미(@bullant_economy) ${meta.updated || ''} 기준: 팔로워 ${meta.followers ?? '–'} · 14일 하루 ${meta.per_day_14d ?? '–'}개 · 조회 중앙값 ${meta.median_views ?? '–'} · 반응률 중앙값 ${meta.median_rate ?? '–'}`,
      ai && !Array.isArray(ai) ? `AI 진단 등급 ${ai.overall_grade}: ${ai.grade_reason || ''}` : '',
      u && !Array.isArray(u) ? `연구소 활용 (${u.time}): 7일 글 ${u.week.posts}개 중 추천에서 ${u.week.posts_used}개. ${u.verdict} 다음에 할 것: ${u.nudge}` : ''].filter(Boolean).join('\n\n');
    return { text: t, used: [] };
  }
  if (name === 'search') {
    const all = await items(), words = String(args.query || '').toLowerCase().split(/\s+/).filter(Boolean);
    const hit = all.map(i => ({ i, s: words.reduce((s, w) => s + ((i.title + ' ' + i.text + ' ' + i.channel + ' ' + i.src).toLowerCase().includes(w) ? 1 : 0), 0) }))
      .filter(x => x.s > 0 || !words.length).sort((a, b) => b.s - a.s).slice(0, 10).map(x => x.i);
    const results = hit.map(i => ({ id: i.id, title: `${i.src} · ${i.title}`, url: i.url || 'https://vhffkfk-max.github.io/content-lab/' }));
    return { text: JSON.stringify({ results }), used: [] };
  }
  if (name === 'fetch') {
    const it = (await items()).find(i => i.id === args.id);
    if (!it) return { text: JSON.stringify({ id: args.id, title: '없음', text: '그 id 의 추천이 지금은 없어요. 2시간마다 바뀌니 search 를 다시 해 주세요.', url: '' }), used: [] };
    return { text: JSON.stringify({ id: it.id, title: it.title, text: show(it), url: it.url || 'https://vhffkfk-max.github.io/content-lab/', metadata: { src: it.src, channel: it.channel } }), used: [it] };
  }
  return null;
}

// ── 사용 기록 (mcp-log 브랜치) ──
function appOf(req) {
  const ua = String(req.headers['user-agent'] || '');
  return /openai|chatgpt/i.test(ua) ? 'ChatGPT' : /claude|anthropic/i.test(ua) ? 'Claude' : '기타';
}
async function logUse(req, tool, used) {
  const token = process.env.GH_LOG_TOKEN;
  if (!token) return;
  const now = new Date(Date.now() + 9 * 3600e3), path = `log/${now.toISOString().slice(0, 7)}.json`;
  const api = `https://api.github.com/repos/${REPO}/contents/${path}`;
  const H = { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'User-Agent': 'content-lab-mcp' };
  const rec = { at: now.toISOString().slice(0, 16).replace('T', ' '), app: appOf(req), ua: String(req.headers['user-agent'] || '').slice(0, 60), tool,
    used: used.slice(0, 10).map(u => ({ src: u.src, title: u.title })) };
  for (let k = 0; k < 3; k++) {   // 동시에 두 번 불리면 sha 가 어긋남 → 다시
    const g = await fetch(`${api}?ref=${LOG_BRANCH}`, { headers: H });
    const cur = g.ok ? await g.json() : null;
    const list = cur ? JSON.parse(Buffer.from(cur.content, 'base64').toString('utf8')) : [];
    list.push(rec);
    const p = await fetch(api, { method: 'PUT', headers: H, body: JSON.stringify({ message: `mcp: ${rec.app} ${tool}`, branch: LOG_BRANCH,
      content: Buffer.from(JSON.stringify(list, null, 0)).toString('base64'), ...(cur ? { sha: cur.sha } : {}) }) });
    if (p.ok || ![409, 422].includes(p.status)) return;
  }
}

const ok = (id, result) => ({ jsonrpc: '2.0', id, result });
const err = (id, code, message) => ({ jsonrpc: '2.0', id, error: { code, message } });

async function handle(req, msg) {
  const { id, method, params = {} } = msg || {};
  if (id === undefined || id === null) return null;   // 알림(notifications/*)은 답 없음
  if (method === 'initialize') {
    const v = PROTOCOLS.includes(params.protocolVersion) ? params.protocolVersion : PROTOCOLS[1];
    return ok(id, { protocolVersion: v, capabilities: { tools: { listChanged: false } }, serverInfo: SERVER,
      instructions: '경제 콘텐츠(쓰레드 황소개미·인스타 카드뉴스·텔레그램 말희아빠·트레이더스 방) 글을 쓸 때 먼저 lab_today 나 lab_channel 로 연구소 추천을 불러와 그 숫자·근거로 쓴다. 숫자를 지어내지 않는다.' });
  }
  if (method === 'ping') return ok(id, {});
  if (method === 'tools/list') return ok(id, { tools: TOOLS });
  if (method === 'tools/call') {
    const r = await call(params.name, params.arguments || {});
    if (!r) return err(id, -32602, `모르는 도구: ${params.name}`);
    try { await logUse(req, params.name, r.used); } catch { /* 기록 실패는 답에 영향 없음 */ }
    return ok(id, { content: [{ type: 'text', text: r.text }], isError: false });
  }
  return err(id, -32601, `지원하지 않는 메서드: ${method}`);
}

export default async function handler(req, res) {
  if (!process.env.MCP_KEY || req.query.key !== process.env.MCP_KEY) return res.status(404).send('Not found');
  if (req.method === 'GET') return res.status(405).setHeader('Allow', 'POST').send('POST only');
  if (req.method === 'DELETE') return res.status(405).send('stateless');
  if (req.method !== 'POST') return res.status(405).send('POST only');
  let body = req.body;
  if (typeof body === 'string') { try { body = JSON.parse(body); } catch { return res.status(400).json(err(null, -32700, 'Parse error')); } }
  if (Array.isArray(body)) {
    const out = (await Promise.all(body.map(m => handle(req, m)))).filter(Boolean);
    return out.length ? res.status(200).json(out) : res.status(202).end();
  }
  const out = await handle(req, body);
  return out ? res.status(200).json(out) : res.status(202).end();
}
