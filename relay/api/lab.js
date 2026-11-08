// 사이트 버튼 중간 서버 — 공용 암호를 확인한 뒤, 정해진 깃허브 요청만 대신 보낸다 (토큰은 여기에만, 사이트에는 없음)
// 환경변수: LAB_KEY(공용 암호) · LAB_OWNER_KEY(인스타 발행 암호, 대표만) · LAB_GH_TOKEN(content-lab 저장소 Contents·Actions 쓰기)

import { timingSafeEqual, createHash } from 'node:crypto';

const REPO = 'vhffkfk-max/content-lab';
const ORIGINS = ['https://vhffkfk-max.github.io'];
const LOCAL = /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/;   // 배포 전 로컬 확인용
const WORKFLOWS = ['draft-create.yml', 'thread-post.yml', 'telegram.yml', 'reanalyze.yml', 'daily.yml', 'card-publish.yml'];
const OWNER_ONLY = ['card-publish.yml'];   // 실제 인스타에 올라가는 버튼
const READ_FILES = ['data/publish_queue.json', 'output/site/thread_posts.json', 'data/feedback.json', 'data/site_usage.json'];
const WRITE_FILES = ['data/feedback.json', 'data/site_usage.json'];

// 쓰레드 글 요청은 main 대신 전용 가지에 파일로 넣는다 — 크롤러 푸시와 안 부딪혀 사라지지 않고, PC(thread_listen.py)가 몇 초 안에 읽어 감
const THREAD_BRANCH = 'lab-requests', THREAD_DIR = 'requests/thpost', RID = /^[a-z0-9]{6,16}$/;

const digest = s => createHash('sha256').update(String(s)).digest();
const same = (a, b) => !!a && !!b && timingSafeEqual(digest(a), digest(b));

// 허용 목록에 있는 요청이면 '보낼 수 있음', 아니면 null. owner 는 발행 암호가 필요한 요청.
// 영상 연구소: 요청은 lab-requests 가지 requests/reel 로, 보드 내용은 reel-previews 가지에서 읽는다
const REEL_DIR = 'requests/reel', REEL_BRANCH = 'reel-previews', REEL_ID = /^[0-9A-Za-z가-힣_]{1,80}$/;
const REEL_ACTIONS = ['board', 'save', 'voice', 'make', 'format', 'hot', 'photo', 'asset', 'duo'];   // hot: 핫코노미 전용 영상 버전 A (주제 → 바로 영상)
const REEL_FORMATS = ['frame', 'neon', 'photo', 'breaking', 'paper', 'split', 'minimal', 'kinetic', 'data', 'ohne'];
const reelText = (v, n) => typeof v === 'string' && v.length <= n;
const reelCut = c => !!c && Number.isInteger(c.i) && c.i >= 0 && c.i < 30 && reelText(c.say, 240) && reelText(c.cap, 240)
  && (c.kick === undefined || reelText(c.kick, 240)) && (c.big === undefined || reelText(c.big, 240))
  && (c.items === undefined || (Array.isArray(c.items) && c.items.length <= 5 && c.items.every(x => reelText(x, 60))));

export function route(method, path) {
  const [p, query = ''] = path.split('?');
  if (method === 'GET' && p === '') return {};
  if (method === 'GET' && p === 'owner') return { owner: true, check: true };   // 발행 암호 확인용, 깃허브로 안 보냄
  let m;
  if (p === 'reel-request') return method === 'POST' && !query ? { reel: true } : null;
  if (p === 'reel-jobs') return method === 'GET' && !query ? { reelJobs: true } : null;
  if ((m = p.match(/^reel-request\/([a-z0-9]+)$/))) return method === 'GET' && RID.test(m[1]) ? { reelStatus: m[1] } : null;
  if ((m = p.match(/^reel-data\/(index\.json|([^/]+)\/board\.json)$/))) {
    const id = m[2] && decodeURIComponent(m[2]);
    return method === 'GET' && !query && (!id || REEL_ID.test(id)) ? { reelData: m[2] ? `${id}/board.json` : 'index.json' } : null;
  }
  if (p === 'thread-request') return method === 'POST' && !query ? { thread: true } : null;
  if ((m = p.match(/^thread-request\/([a-z0-9]+)$/))) return method === 'GET' && RID.test(m[1]) ? { threadStatus: m[1] } : null;
  if ((m = p.match(/^contents\/(.+)$/))) {
    if (method === 'GET' && READ_FILES.includes(m[1])) return {};
    if (method === 'PUT' && WRITE_FILES.includes(m[1]) && !query) return {};
    return null;
  }
  if ((m = p.match(/^actions\/workflows\/([\w.-]+)\/(dispatches|runs)$/)) && WORKFLOWS.includes(m[1])) {
    if (m[2] === 'runs') return method === 'GET' ? {} : null;
    return method === 'POST' && !query ? { owner: OWNER_ONLY.includes(m[1]) } : null;
  }
  return null;
}

// 요청 내용은 서버에서 다시 만든다 (정해진 칸·형식만)
export function threadFile({ rid, idx, styles, slot } = {}, now = new Date()) {
  const ok = RID.test(rid) && [0, 1, 2].includes(Number(idx)) && /^[A-E]{1,5}$/.test(styles) && /^[\d/: ]{0,20}$/.test(slot || '');
  if (!ok) return null;
  const at = new Date(now.getTime() + 9 * 3600e3).toISOString().slice(0, 19) + '+09:00';
  return { rid, idx: Number(idx), styles, slot: slot || '', at };
}

// 요청 내용은 서버에서 다시 만든다 (정해진 칸·형식만)
export function reelFile({ rid, action, id, topic, angle, brand, style, cut, cuts, accept, format, op, query, url, data } = {}, now = new Date()) {
  if (!RID.test(rid) || !REEL_ACTIONS.includes(action)) return null;
  const at = new Date(now.getTime() + 9 * 3600e3).toISOString().slice(0, 19) + '+09:00';
  if (action === 'asset') {   // 자산백배 3자 비교 릴스 (주제 → 바로 영상)
    const t = typeof topic === 'string' ? topic.replace(/\s+/g, ' ').trim() : '', a = typeof angle === 'string' ? angle.replace(/\s+/g, ' ').trim() : '';
    return t.length >= 2 && t.length <= 60 && a.length <= 60 ? { rid, action, topic: t, angle: a, brand: ['asset', 'bull', 'chart', 'malhee'].includes(brand) ? brand : 'asset', at } : null;
  }
  if (action === 'duo') {   // 대화극 릴스: 주제 + 스타일 A~E
    const t = typeof topic === 'string' ? topic.trim() : '';
    return t.length >= 2 && t.length <= 60 && /^[A-E]$/.test(style || '') ? { rid, action, topic: t, style, at } : null;
  }
  if (action === 'board' || action === 'hot') {
    const t = typeof topic === 'string' ? topic.replace(/\s+/g, ' ').trim() : '';
    return t.length >= 2 && t.length <= 60 ? { rid, action, topic: t, at } : null;
  }
  if (!REEL_ID.test(id || '')) return null;
  if (action === 'make') return { rid, action, id, accept: accept === true, at };
  if (action === 'format') return REEL_FORMATS.includes(format) ? { rid, action, id, format, at } : null;
  if (action === 'photo') {   // 컷 사진 바꾸기: 찾기(검색어) · 고르기(위키미디어 주소) · 빼기 · 올리기(사진 파일, 3MB 이하)
    if (!Number.isInteger(cut) || cut < 0 || cut >= 30) return null;
    if (op === 'search') return reelText(query, 80) && query.trim().length >= 2 ? { rid, action, id, cut, op, query: query.trim(), at } : null;
    if (op === 'pick') return typeof url === 'string' && url.length <= 600 && /^https:\/\/upload\.wikimedia\.org\//.test(url) ? { rid, action, id, cut, op, url, at } : null;
    if (op === 'remove') return { rid, action, id, cut, op, at };
    if (op === 'upload') return typeof data === 'string' && data.length <= 4_000_000 && /^[A-Za-z0-9+/=]+$/.test(data) ? { rid, action, id, cut, op, data, at } : null;
    return null;
  }
  if (action === 'voice') return Number.isInteger(cut) && cut >= 0 && cut < 30 ? { rid, action, id, cut, at } : null;
  return Array.isArray(cuts) && cuts.length >= 1 && cuts.length <= 20 && cuts.every(reelCut)
    ? { rid, action, id, cuts: cuts.map(({ i, say, cap, kick, big, items }) => ({ i, say, cap, kick, big, items })), at } : null;
}

export default async function handler(req, res) {
  const origin = req.headers.origin || '';
  if (ORIGINS.includes(origin) || LOCAL.test(origin)) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Vary', 'Origin');
    res.setHeader('Access-Control-Allow-Headers', 'content-type, x-lab-key, x-lab-accept');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, OPTIONS');
  }
  res.setHeader('Cache-Control', 'no-store');
  if (req.method === 'OPTIONS') return res.status(204).end();

  const key = req.headers['x-lab-key'], { LAB_KEY, LAB_OWNER_KEY, LAB_GH_TOKEN } = process.env;
  if (!LAB_GH_TOKEN || !LAB_KEY || !LAB_OWNER_KEY) return res.status(503).json({ error: 'not_configured' });
  const isOwner = same(key, LAB_OWNER_KEY);
  const path = String(req.query.path || ''), rule = route(req.method, path);
  // 암호 없이 받는다 (2026-11-06 대표 요청: 연구소 사이트 암호 전부 없앰). 요청 형식은 route·threadFile·reelFile 이 정해진 칸만 허용하고,
  // 하루 처리량은 PC(local_ai.py · thread_listen.py · reels/reel_listen.py)가 막는다. 발행 암호(owner) 요청만 그대로 확인한다.
  const open = !!rule && !rule.owner;
  if (!open && !isOwner && !same(key, LAB_KEY)) {
    await new Promise(r => setTimeout(r, 800));   // 암호 맞히기를 느리게
    return res.status(401).json({ error: 'bad_key' });
  }
  if (!rule) return res.status(404).json({ error: 'not_allowed' });
  if (rule.owner && !isOwner) return res.status(403).json({ error: 'owner_only' });
  if (rule.check) return res.status(204).end();
  const gh = (p, init = {}) => fetch(`https://api.github.com/repos/${REPO}/${p}`, { cache: 'no-store', ...init,
    headers: { Authorization: `Bearer ${LAB_GH_TOKEN}`, Accept: 'application/vnd.github+json', 'User-Agent': 'content-lab-relay', 'Content-Type': 'application/json' } });
  if (rule.thread) {
    const body = typeof req.body === 'string' ? JSON.parse(req.body || '{}') : req.body;
    const file = threadFile(body);
    if (!file) return res.status(400).json({ error: 'bad_request' });
    const r = await gh(`contents/${THREAD_DIR}/${file.rid}.json`, { method: 'PUT', body: JSON.stringify({ message: 'thread request', branch: THREAD_BRANCH,
      content: Buffer.from(JSON.stringify(file)).toString('base64') }) });
    if (r.status === 401) return res.status(502).json({ error: 'github_token' });
    return r.ok ? res.status(201).json({ rid: file.rid }) : res.status(r.status).json({ error: 'github' });
  }
  if (rule.reel) {
    const body = typeof req.body === 'string' ? JSON.parse(req.body || '{}') : req.body;
    const file = reelFile(body);
    if (!file) return res.status(400).json({ error: 'bad_request' });
    const r = await gh(`contents/${REEL_DIR}/${file.rid}.json`, { method: 'PUT', body: JSON.stringify({ message: 'reel request', branch: THREAD_BRANCH,
      content: Buffer.from(JSON.stringify(file)).toString('base64') }) });
    if (r.status === 401) return res.status(502).json({ error: 'github_token' });
    return r.ok ? res.status(201).json({ rid: file.rid }) : res.status(r.status).json({ error: 'github' });
  }
  if (rule.reelJobs) {   // 어느 기기에서 열어도 PC가 하는 일·기다리는 일이 보이게
    const r = await gh(`contents/${REEL_DIR}?ref=${THREAD_BRANCH}`);
    if (r.status === 401) return res.status(502).json({ error: 'github_token' });
    if (r.status === 404) return res.status(200).json({ jobs: [] });
    if (!r.ok) return res.status(502).json({ error: 'github' });
    const files = (await r.json()).filter(f => f.name.endsWith('.json')).slice(0, 12);
    const jobs = (await Promise.all(files.map(async f => {
      const x = await gh(`contents/${REEL_DIR}/${f.name}?ref=${THREAD_BRANCH}`);
      if (!x.ok) return null;
      const q = JSON.parse(Buffer.from((await x.json()).content, 'base64').toString('utf-8'));
      return { rid: q.rid, action: q.action, topic: q.topic || '', id: q.id || '', at: q.at, picked: q.picked || null, error: q.error || null, auto: !!q.auto };
    }))).filter(Boolean).sort((a, b) => String(a.at).localeCompare(String(b.at)));
    return res.status(200).json({ jobs });
  }
  if (rule.reelStatus) {
    const r = await gh(`contents/${REEL_DIR}/${rule.reelStatus}.json?ref=${THREAD_BRANCH}`);
    if (r.status === 401) return res.status(502).json({ error: 'github_token' });
    if (!r.ok) return res.status(r.status === 404 ? 404 : 502).json({ error: 'none' });
    const { picked, error } = JSON.parse(Buffer.from((await r.json()).content, 'base64').toString('utf-8'));
    return res.status(200).json({ picked: picked || null, error: error || null });
  }
  if (rule.reelData) {
    const r = await gh(`contents/${rule.reelData.split('/').map(encodeURIComponent).join('/')}?ref=${REEL_BRANCH}`);
    if (r.status === 401) return res.status(502).json({ error: 'github_token' });
    if (!r.ok) return res.status(r.status === 404 ? 404 : 502).json({ error: 'none' });
    const data = JSON.parse(Buffer.from((await r.json()).content, 'base64').toString('utf-8'));
    return res.status(200).json(data);
  }
  if (rule.threadStatus) {
    const r = await gh(`contents/${THREAD_DIR}/${rule.threadStatus}.json?ref=${THREAD_BRANCH}`);
    if (r.status === 401) return res.status(502).json({ error: 'github_token' });
    if (!r.ok) return res.status(r.status === 404 ? 404 : 502).json({ error: 'none' });
    const { picked, error } = JSON.parse(Buffer.from((await r.json()).content, 'base64').toString('utf-8'));
    return res.status(200).json({ picked: picked || null, error: error || null });
  }

  const accept = req.headers['x-lab-accept'] === 'raw' ? 'application/vnd.github.raw+json' : 'application/vnd.github+json';
  const body = req.method === 'GET' ? undefined : typeof req.body === 'string' ? req.body : JSON.stringify(req.body || {});
  const r = await fetch(`https://api.github.com/repos/${REPO}${path ? '/' + path : ''}`, {
    method: req.method, body, cache: 'no-store',
    headers: { Authorization: `Bearer ${LAB_GH_TOKEN}`, Accept: accept, 'User-Agent': 'content-lab-relay', 'Content-Type': 'application/json' },
  });
  // 깃허브 토큰이 만료·취소되면 사이트가 암호 탓으로 알지 않게 구분해서 돌려준다
  if (r.status === 401) return res.status(502).json({ error: 'github_token' });
  const text = await r.text();
  res.status(r.status);
  if (r.status === 204) return res.end();
  res.setHeader('Content-Type', r.headers.get('content-type') || 'application/json');
  return res.send(text);
}
