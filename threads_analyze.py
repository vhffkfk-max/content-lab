"""쓰레드 반응 좋은 경제 글을 Claude로 분석해 output/site/threads_ai.json 에 저장한다.

대상: 이번 주 따라 할 글 TOP 5 + 조회수 TOP + 공유·리포스트 TOP + 댓글 TOP (threads_score.py) + 팀이 모은 글.
글마다 '왜 조회·공유·댓글이 많았나'를 분석하고, 랭킹별 공통점, 따라 쓸 공식, (TOP·팀 글은) 우리 말투 초안을 쓴다.

    python threads_analyze.py            # ANTHROPIC_API_KEY 필요
    python threads_analyze.py --dry-run  # API 호출 없이 프롬프트만 출력
입력이 같으면 다시 분석하지 않는다 (비용 절약). 실패하면 지난 결과를 그대로 둔다.
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
LISTS = {"top": "따라 할 글 TOP", "views": "조회수 TOP", "shared": "공유·리포스트 TOP", "replied": "댓글 TOP", "team": "팀이 모은 글"}

SYSTEM = """당신은 한국 경제 크리에이터 @hotconomy 의 쓰레드(Threads) 전략가입니다.
경제(주식·코인·금리·환율·부동산·경제 뉴스) 쓰레드 글 중 조회수, 공유·리포스트, 댓글이 많았던 글을 받아
'왜 그렇게 반응했는지'를 구체적으로 분석하고, 우리 계정이 따라 쓸 수 있게 정리합니다.

입력 글마다 lists(어느 랭킹에 들었나), 조회·팔로워·확산배수(조회÷팔로워)·반응률·좋아요·답글·리포스트·인용·공유 수가 있습니다.
- 조회수 TOP 글: 왜 많이 노출됐나 (주제의 시의성, 첫 줄, 팔로워 밖으로 퍼진 정도=확산배수)
- 공유·리포스트 TOP 글: 왜 남에게 보내고 싶었나 (저장·전달할 정보, 정리형, 숫자, 남에게 알려주고 싶은 소식)
- 댓글 TOP 글: 왜 말을 걸고 싶었나 (질문, 논쟁 거리, 의견이 갈리는 주장, 경험 공유 유도)
- press=true 는 언론사 계정입니다. 언론 글은 '소식 자체'의 힘인지 '전달 방식'의 힘인지 구분해 주세요.

규칙:
- 모두 한국어. 이모지 금지. 데이터에 없는 수치는 지어내지 말고 [확인]으로 비웁니다.
- 원문을 그대로 베끼지 않습니다. rewrite 는 같은 '구조와 훅 방식'만 빌려 @hotconomy 의 경제 주제로 새로 씁니다.
- 특정 종목 매수·매도 권유, 수익 보장, 매수 시점 암시를 쓰지 않습니다. 주식·코인·부동산 글 마지막에는 투자 권유가 아니라는 한 줄을 넣습니다.
- summary: 받은 글 전체의 공통점 3줄 (각 60자 안팎).
- patterns: 랭킹마다(조회수 TOP, 공유·리포스트 TOP, 댓글 TOP) 공통 이유 3줄씩. list 는 그 랭킹 이름 그대로.
- formulas: 따라 쓸 수 있는 쓰레드 글 공식 3~5개. name, pattern(구조 한 줄, 예: '숫자 한 줄 → 이유 3개 → 질문'),
  example_hook(우리 계정용 첫 문장 예시), when(언제 쓰나), sources(근거 글 번호들).
- posts: 받은 글 각각에 no(번호 그대로), hook_type(첫 문장 방식), trigger(반응을 끈 장치 10자 안팎, 예: '숫자 정리', '편 가르기 질문', '속보 요약'),
  why(왜 조회·공유·댓글이 많았는지 2~3문장, 그 글이 든 랭킹에 맞춰 구체적으로, 수치 근거 포함), structure(구조 한 줄),
  rewrite(draft=true 인 글만 우리 계정용 쓰레드 글 1~2개, 각 300자 이내. draft=false 면 빈 목록)."""


def load_posts(db):
    conn = connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    rows = []
    if "threads_saved" in tables:
        since = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(timespec="seconds")
        for r in conn.execute("SELECT * FROM threads_saved WHERE first_seen >= ? AND text != '' ORDER BY first_seen DESC LIMIT 15", (since,)):
            rows.append({"id": r["id"], "code": (r["link"] or "").rstrip("/").rsplit("/", 1)[-1], "lists": ["team"], "draft": True,
                         "author": r["author"], "text": r["text"], "likes": r["likes"], "replies": r["replies"], "reposts": r["reposts"],
                         "memo": r["memo"] or ""})
    if "threads_apify" in tables:
        import threads_score
        sec = threads_score.section(conn, datetime.now(timezone.utc))
        by_code = {r["code"]: r for r in rows}
        groups = [("top", sec["top"])] + [(k, [h for h in sec["rank"] if h["list"] == k]) for k in ("views", "shared", "replied")]
        for key, hs in groups:
            for h in hs:
                code = h["url"].rstrip("/").rsplit("/", 1)[-1]
                if code in by_code:
                    if key not in by_code[code]["lists"]:
                        by_code[code]["lists"].append(key)
                    by_code[code]["draft"] = by_code[code]["draft"] or key == "top"
                    continue
                row = {"id": h["id"], "code": code, "lists": [key], "draft": key == "top", "author": h["username"],
                       "press": h.get("press", False), "text": h["text"], "followers": h["followers"], "views": h["views"],
                       "spread": h["spread"], "rate": h["rate"], "likes": h["likes"], "replies": h["replies"], "reposts": h["reposts"],
                       "quotes": h["quotes"], "shares": h["shares"]}
                rows.append(row)
                by_code[code] = row
    return rows[:45]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    args = ap.parse_args()
    load_env()
    posts = load_posts(args.db)
    if not posts:
        print("분석할 쓰레드 글이 아직 없어요 — 분석을 건너뛰어요.")
        return
    keys = ("author", "press", "followers", "views", "spread", "rate", "likes", "replies", "reposts", "quotes", "shares", "memo", "draft")
    items = [{"no": i, "lists": [LISTS[k] for k in p["lists"]], **{k: p[k] for k in keys if p.get(k) not in (None, "")},
              "text": p["text"][:1200]} for i, p in enumerate(posts, 1)]
    digest = hashlib.sha1(json.dumps(items, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    prompt = "분석할 쓰레드 글:\n" + json.dumps(items, ensure_ascii=False, indent=1)
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

    class Pattern(BaseModel):
        list: str
        reasons: List[str]

    class PostNote(BaseModel):
        no: int
        hook_type: str
        trigger: str
        why: str
        structure: str
        rewrite: List[str]

    class Analysis(BaseModel):
        summary: List[str]
        patterns: List[Pattern]
        formulas: List[Formula]
        posts: List[PostNote]

    client = anthropic.Anthropic()
    try:
        response = client.messages.parse(model=MODEL, max_tokens=32000, system=SYSTEM,
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
                               "count": len(posts), "summary": a.summary, "patterns": [p.model_dump() for p in a.patterns],
                               "formulas": [f.model_dump() for f in a.formulas], "posts": notes},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    u = response.usage
    print(f"✅ 쓰레드 글 {len(posts)}개 분석 · 공식 {len(a.formulas)}개 (입력 {u.input_tokens:,} / 출력 {u.output_tokens:,} 토큰)")


if __name__ == "__main__":
    sys.exit(main())
