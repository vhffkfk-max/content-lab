"""마케팅 코치 — 설치한 마케팅 스킬(social·content-strategy·copywriting·marketing-psychology·ab-testing·community-marketing·marketing-loops)의
원칙을 우리 실제 숫자(황소개미·인스타·텔레그램·지금 뜨는 주제·사이트 이용 시간)에 적용해 이번 주 성장 계획을 만든다 → output/site/growth_plan.json

    python growth_coach.py           # 차례(월·목 07시 이후)일 때만 — local_ai.py 가 부름
    python growth_coach.py --force   # 지금 바로
    python growth_coach.py --dry-run # 프롬프트 크기만

내 PC Claude Code(Max 구독, llm.py)라 API 요금 없음. 스킬 원문은 ~/.claude/skills/<이름>/SKILL.md 에서 읽어 시스템 프롬프트에 넣음.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from pydantic import BaseModel

import llm as anthropic
from common import OUTPUT_DIR, ROOT, load_env

KST = timezone(timedelta(hours=9))
SITE = OUTPUT_DIR / "site"
OUT = SITE / "growth_plan.json"
MODEL = "claude-opus-5-5"
SKILLS = ["social", "content-strategy", "copywriting", "marketing-psychology", "ab-testing", "community-marketing", "marketing-loops"]
SKILL_DIR = Path.home() / ".claude" / "skills"
DAYS = (0, 3)   # 월·목

SYSTEM = """너는 한국 경제 콘텐츠 사업(@hotconomy 인스타 카드뉴스, 쓰레드 '황소개미' @bullant_economy, 텔레그램 '차트보는 말희아빠' 채널,
유료 트레이더스 방)의 그로스 마케팅 코치다. 대표는 마케팅 비전문가라 쉬운 한국어로, 바로 할 수 있는 행동으로 말한다.
아래 '마케팅 스킬' 원문은 검증된 프레임워크다. 그 원칙을 우리 숫자에 그대로 적용하고, 어느 스킬의 어느 원칙을 썼는지 skill 칸에 적는다.

규칙:
- 근거는 입력 숫자만. 없는 숫자는 지어내지 말고 '데이터 없음'이라고 적는다.
- 실험 가설은 반드시 반증 가능하게: '무엇을 바꾸면 어떤 지표가 어느 방향으로 얼마나(대략) 바뀐다', 기간과 판정 기준 포함.
- 퍼널: 쓰레드·인스타(발견) → 프로필 방문·팔로우 → 텔레그램 채널 구독 → 트레이더스 방(수익). 이번 주 가장 막힌 한 곳만 고른다.
- 카피는 AI 티('~가 아니라 ~다' 반전, 'A도 B도 C도 없다' 나열, 꼬리 쉼표절)를 쓰지 않는다. 사람 말투, 숫자 포함.
- 투자 권유·수익 보장·리딩방 연상 표현 금지(금융 광고 규제). 공포·과장 낚시 금지.
- site_tips 는 '사이트 이용 시간'을 보고: 많이 보는 메뉴는 더 앞으로, 안 보는데 중요한 메뉴는 왜 봐야 하는지 한 줄로.

## 마케팅 스킬 원문
{skills}"""


class Experiment(BaseModel):
    name: str
    channel: str
    hypothesis: str
    metric: str
    how: str
    days: int
    impact: int        # 1~10
    confidence: int    # 1~10
    ease: int          # 1~10
    skill: str


class Hook(BaseModel):
    channel: str
    text: str
    principle: str


class Day(BaseModel):
    day: str
    channel: str
    idea: str
    format: str


class Plan(BaseModel):
    headline: str
    positioning: str
    bottleneck: str
    bottleneck_fix: str
    experiments: List[Experiment]
    hooks: List[Hook]
    calendar: List[Day]
    community: List[str]
    site_tips: List[str]
    skills_used: List[str]


def rows(name):
    try:
        return json.loads((SITE / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def usage():
    """data/site_usage.json (사이트가 올린 이용 시간) → 최근 7일 메뉴별 분."""
    try:
        d = json.loads((ROOT / "data" / "site_usage.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    since = (datetime.now(KST) - timedelta(days=7)).strftime("%Y-%m-%d")
    tot = {}
    for days in d.get("devices", {}).values():
        for day, pages in days.items():
            if day >= since:
                for p, s in pages.items():
                    tot[p] = tot.get(p, 0) + s
    return [f"{p}: {round(s / 60)}분" for p, s in sorted(tot.items(), key=lambda x: -x[1])]


def context():
    thm, thm_ai = (rows("thm_meta") or [{}])[0], rows("thm_ai") or {}
    hn = (rows("hot_now") or [{}])[0]
    tg = sorted(rows("tg_mine"), key=lambda r: -(r.get("views") or 0))[:8]
    bench = (rows("acc_rank_meta") or [{}])[0].get("bench") or []
    return {
        "황소개미_쓰레드": {k: thm.get(k) for k in ("followers", "per_day_14d", "active_days_14d", "median_views", "median_rate", "trend",
                                                "bench_views", "bench_rate", "best_hour")},
        "황소개미_AI진단": {k: thm_ai.get(k) for k in ("overall_grade", "grade_reason", "identity_line", "feed_issues")} if isinstance(thm_ai, dict) else {},
        "인스타_내계정": (rows("own_meta") or [{}])[0],
        "텔레그램_내채널_조회상위": [{"views": r.get("views"), "forwards": r.get("forwards"), "time": r.get("time"), "text": (r.get("text") or "")[:80]} for r in tg],
        "텔레그램_현황": (rows("tg_meta") or [{}])[0],
        "남의_쓰레드_잘된글": [{"views": r["views"], "followers": r.get("followers"), "hook": r.get("hook"), "text": r["text"][:100]} for r in rows("thx_top")[:6]],
        "벤치마킹_상위계정": bench[:12] if isinstance(bench, list) else [],
        "지금_뜨는_주제": {"summary": hn.get("summary"), "topics": [p.get("topic") for p in hn.get("picks", [])]},
        "30일_추천주제": [r.get("topic") for r in rows("recs")[:5]],
        "연구소_활용체크": {k: (rows("use_audit") or {}).get(k) for k in ("week", "verdict", "by_src")} if isinstance(rows("use_audit"), dict) else "아직 없음",
        "사이트_이용시간_7일": usage() or ["아직 기록 없음 (저장소 연결된 브라우저만 올라옴)"],
    }


def skills_text():
    out = []
    for s in SKILLS:
        f = SKILL_DIR / s / "SKILL.md"
        if f.exists():
            out.append(f"### 스킬: {s}\n" + f.read_text(encoding="utf-8")[:14000])
    return "\n\n".join(out)


def due(force):
    if force:
        return True
    now = datetime.now(KST)
    if now.weekday() not in DAYS or now.hour < 7:
        return False
    last = rows("growth_plan")
    return not (isinstance(last, dict) and last.get("date") == now.strftime("%Y-%m-%d"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    load_env()
    if not (a.dry_run or due(a.force)):
        return
    sk = skills_text()
    prompt = "우리 숫자:\n" + json.dumps(context(), ensure_ascii=False, indent=1) + "\n\n이번 주 성장 계획을 만들어 줘. 실험 3개, 훅 10개, 7일 캘린더."
    if a.dry_run:
        return print(f"스킬 {len(sk):,}자 · 데이터 {len(prompt):,}자\n{prompt[:2500]}")
    if not anthropic.ready():
        return print("⚠️ Claude Code 가 없어요 — 건너뜀")
    r = anthropic.Anthropic().messages.parse(model=MODEL, max_tokens=16000, system=SYSTEM.format(skills=sk), output_config={"effort": "medium"},
                                             messages=[{"role": "user", "content": prompt}], output_format=Plan)
    if r.parsed_output is None:
        return print(f"⚠️ 결과를 못 받았어요(stop_reason={r.stop_reason})")
    now = datetime.now(KST)
    plan = {"date": now.strftime("%Y-%m-%d"), "time": now.strftime("%m/%d %H:%M"), **r.parsed_output.model_dump()}
    plan["experiments"].sort(key=lambda e: -(e["impact"] * e["confidence"] * e["ease"]))
    OUT.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ 마케팅 코치: {plan['headline'][:60]} · 실험 {len(plan['experiments'])}개 · 입력 {r.usage.input_tokens:,} / 출력 {r.usage.output_tokens:,} 토큰")


if __name__ == "__main__":
    main()
