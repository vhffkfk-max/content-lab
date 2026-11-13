"""계정 설정·페르소나·결과 파일 경로."""
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from common import OUTPUT_DIR, ROOT

KST = timezone(timedelta(hours=9))
SITE = OUTPUT_DIR / "site"
TOPICS = SITE / "acc_topics.json"
CONFIG = ROOT / "accounts.config.json"
PERSONA_DIRS = [Path.home() / ".content-lab-ai" / "personas", ROOT / "personas"]

TAGS = ("macro", "kr_stock", "us_stock", "crypto", "realestate", "policy", "politics_domestic", "politics_economy")
TAG_NAMES = {"macro": "거시", "kr_stock": "국내주식", "us_stock": "미국주식", "crypto": "코인", "realestate": "부동산",
             "policy": "정책", "politics_domestic": "국내정치", "politics_economy": "정치·경제"}


def config():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def accounts():
    c = config()
    return [{**c["defaults"], **a} for a in c["accounts"]]


def account(slug):
    return next((a for a in accounts() if a["slug"] == slug), None)


def persona(slug):
    for d in PERSONA_DIRS:
        p = d / f"{slug}.md"
        if p.exists():
            return p.read_text(encoding="utf-8")
    return ""


def election_now(today=None):
    today = today or date.today().isoformat()
    return next((e for e in config().get("election_periods", []) if e["from"] <= today <= e["to"]), None)


def items_path(slug, engine="claude"):
    """Claude 글은 acc_<slug>.json, ChatGPT 글은 acc_<slug>_gpt.json (페이지에서 따로 보임)."""
    return SITE / (f"acc_{slug}_gpt.json" if engine == "gpt" else f"acc_{slug}.json")


def load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def now():
    return datetime.now(KST)
