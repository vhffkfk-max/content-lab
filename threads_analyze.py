"""팀이 모은 쓰레드 글과 자동 수집 인기 글을 Claude로 분석해 output/site/threads_ai.json 에 저장한다.

    python threads_analyze.py            # ANTHROPIC_API_KEY 필요
    python threads_analyze.py --dry-run  # API 호출 없이 프롬프트만 출력
새 글·수정이 없으면 다시 분석하지 않는다 (비용 절약). 실패하면 지난 결과를 그대로 둔다.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import List

from common import DEFAULT_DB, OUTPUT_DIR, connect, load_env

MODEL = "claude-opus-5-5"
OUT = OUTPUT_DIR / "site" / "threads_ai.json"

SYSTEM = """당신은 한국 경제 크리에이터 @hotconomy 의 쓰레드(Threads) 전략가입니다.
팀이 직접 골라 모은 글과 자동 수집한 경제 키워드 인기 글(memo가 '자동 수집'으로 시작, 조회수·팔로워·확산배수·반응률 포함)을 분석해서, 왜 잘 됐는지와 우리 계정이 따라 쓸 수 있는 공식을 뽑습니다.
확산배수(조회 ÷ 팔로워)가 높은 글은 팔로워 밖으로 퍼진 글이니 '왜 퍼졌나'를 우선 설명합니다.

규칙:
- 모두 한국어. 이모지 금지. 데이터에 없는 수치는 지어내지 말고 [확인]으로 비웁니다.
- 원문을 그대로 베끼지 않습니다. rewrite 는 같은 '구조와 훅 방식'만 빌려 @hotconomy 의 경제 주제로 새로 씁니다.
- 특정 종목 매수·매도 권유, 수익 보장, 매수 시점 암시를 쓰지 않습니다. 주식·코인·부동산 글 마지막에는 투자 권유가 아니라는 한 줄을 넣습니다.
- 좋아요·답글 수가 주어진 글은 반응이 큰 글에 더 무게를 둡니다. 수치가 없으면 팀이 고른 글이라는 점만 근거로 씁니다.
- summary: 모은 글 전체에서 보이는 공통점 3줄 (각 줄 60자 안팎).
- formulas: 따라 쓸 수 있는 쓰레드 글 공식 3~5개. name(짧은 이름), pattern(구조를 한 줄로, 예: '반전 한 줄 → 숫자 하나 → 질문'),
  example_hook(우리 계정용 첫 문장 예시), when(언제 쓰면 좋은지), sources(근거가 된 글 번호들).
- posts: 각 글마다 no(번호 그대로), hook_type(첫 문장 방식), why(왜 반응이 좋았는지 1~2문장), structure(구조 한 줄),
  rewrite(우리 계정용으로 다시 쓴 쓰레드 글 1~3개, 각 300자 이내)."""


def load_posts(db):
    conn = connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "threads_saved" not in tables:
        return []
    since = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(timespec="seconds")
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM threads_saved WHERE first_seen >= ? AND text != '' ORDER BY first_seen DESC LIMIT 25", (since,))]
    if "threads_apify" in tables:
        # 자동 수집 글: 이번 주 따라 할 글 TOP + 점수 상위 (조회수·확산배수 기준, 팀 링크로 이미 들어온 글은 빼고)
        import threads_score
        sec = threads_score.section(conn, datetime.now(timezone.utc))
        seen = {r["link"].rstrip("/").rsplit("/", 1)[-1] for r in rows}
        picked, ids = [], set()
        for h in sec["top"] + sec["rising"][:5] + sec["hot"]:
            if h["id"] in ids or h["url"].rstrip("/").rsplit("/", 1)[-1] in seen:
                continue
            ids.add(h["id"])
            memo = (f"자동 수집 · 조회 {h['views']:,} · 팔로워 {h['followers'] or 0:,} · 확산 {h['spread']}배 · 반응률 {h['rate']}%"
                    if h["views"] else "자동 수집 · 조회수 대기")
            picked.append({"id": h["id"], "link": h["url"], "author": h["username"], "text": h["text"], "likes": h["likes"],
                           "replies": h["replies"], "reposts": h["reposts"], "memo": memo})
        rows += picked[:12]
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    args = ap.parse_args()
    load_env()
    posts = load_posts(args.db)
    if not posts:
        print("팀이 모은 쓰레드 글이 아직 없어요 — 분석을 건너뛰어요.")
        return
    items = [{"no": i, "author": p["author"], "likes": p["likes"], "replies": p["replies"], "reposts": p["reposts"],
              "memo": p["memo"], "text": p["text"][:1500]} for i, p in enumerate(posts, 1)]
    digest = hashlib.sha1(json.dumps(items, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    prompt = "팀이 모은 쓰레드 글:\n" + json.dumps(items, ensure_ascii=False, indent=1)
    if args.dry_run:
        print(SYSTEM, "\n\n", prompt[:3000])
        return
    if OUT.exists() and json.loads(OUT.read_text(encoding="utf-8")).get("digest") == digest:
        print("새로 모은 쓰레드 글이 없어 지난 분석을 그대로 써요.")
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY 가 없어 쓰레드 분석을 건너뛰어요 — 지난 결과를 유지해요.")
        return

    import anthropic
    from pydantic import BaseModel

    class Formula(BaseModel):
        name: str
        pattern: str
        example_hook: str
        when: str
        sources: List[int]

    class PostNote(BaseModel):
        no: int
        hook_type: str
        why: str
        structure: str
        rewrite: List[str]

    class Analysis(BaseModel):
        summary: List[str]
        formulas: List[Formula]
        posts: List[PostNote]

    client = anthropic.Anthropic()
    try:
        response = client.messages.parse(model=MODEL, max_tokens=16000, system=SYSTEM,
                                         messages=[{"role": "user", "content": prompt}], output_format=Analysis)
    except anthropic.APIStatusError as e:
        print(f"⚠️ Claude API 오류({e.status_code}): {e.message} — 지난 결과를 유지해요.")
        return
    except anthropic.APIConnectionError:
        print("⚠️ Claude API 연결 실패 — 지난 결과를 유지해요.")
        return
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        print(f"⚠️ 결과를 받지 못했어요(stop_reason={response.stop_reason}) — 지난 결과를 유지해요.")
        return
    a = response.parsed_output
    by_no = {i: p for i, p in enumerate(posts, 1)}
    notes = [{**n.model_dump(), "id": by_no[n.no]["id"]} for n in a.posts if n.no in by_no]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"digest": digest, "analyzed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "count": len(posts), "summary": a.summary,
                               "formulas": [f.model_dump() for f in a.formulas], "posts": notes},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    u = response.usage
    print(f"✅ 쓰레드 글 {len(posts)}개 분석 · 공식 {len(a.formulas)}개 (입력 {u.input_tokens:,} / 출력 {u.output_tokens:,} 토큰)")


if __name__ == "__main__":
    sys.exit(main())
