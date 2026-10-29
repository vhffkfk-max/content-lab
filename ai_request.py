"""깃허브 실행(사이트 버튼·매일 06시 수집)이 내 PC에 'Claude 작업'을 맡길 때 쓰는 요청함.

  python ai_request.py daily                  # 06시 수집 끝 → 기획안·해외 아이디어·쓰레드·X 분석
  python ai_request.py social                 # 쓰레드·X 다시 분석
  python ai_request.py tg focus="하락장 대응"  # 텔레그램 오늘 문구 다시
  python ai_request.py trd                    # 트레이더스 방별 글 다시
  python ai_request.py draft topic="환율"      # 카드뉴스 초안

data/ai_requests.json 에 쌓이고, 내 PC의 local_ai.py 가 5분마다 확인해서 Max 구독으로 처리한다.
"""
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone

from common import DATA_DIR

PATH = DATA_DIR / "ai_requests.json"
JOBS = ("daily", "social", "tg", "trd", "draft")


def load():
    return json.loads(PATH.read_text(encoding="utf-8")) if PATH.exists() else []


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in JOBS:
        sys.exit(f"사용법: python ai_request.py {{{'|'.join(JOBS)}}} [키=값 ...]")
    args = dict(a.split("=", 1) for a in sys.argv[2:] if "=" in a and a.split("=", 1)[1])
    rows = load()[-49:]   # 최근 50개만
    rows.append({"id": uuid.uuid4().hex[:12], "job": sys.argv[1], "args": args,
                 "at": datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")})
    PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ PC에 Claude 작업 요청: {sys.argv[1]} {args or ''}")


if __name__ == "__main__":
    main()
