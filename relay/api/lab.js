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

const digest = s => createHash('sha256').update(String(s)).digest();
const same = (a, b) => !!a && !!b && timingSafeEqual(digest(a), digest(b));

// 허용 목록에 있는 요청이면 '보낼 수 있음', 아니면 null. owner 는 발행 암호가 필요한 요청.
export function route(method, path) {
  const [p, query = ''] = path.split('?');
  if (method === 'GET' && p === '') return {};
  if (method === 'GET' && p === 'owner') return { owner: true, check: true };   // 발행 암호 확인용, 깃허브로 안 보냄
  let m;
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
  if (!isOwner && !same(key, LAB_KEY)) {
    await new Promise(r => setTimeout(r, 800));   // 암호 맞히기를 느리게
    return res.status(401).json({ error: 'bad_key' });
  }

  const path = String(req.query.path || ''), rule = route(req.method, path);
  if (!rule) return res.status(404).json({ error: 'not_allowed' });
  if (rule.owner && !isOwner) return res.status(403).json({ error: 'owner_only' });
  if (rule.check) return res.status(204).end();

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
