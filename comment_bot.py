"""댓글 기회 봇 1단계 — 쓰레드·인스타 글 링크를 텔레그램 봇에 보내면 댓글 3안(A 숫자 보강, B 다른 각도, C 질문)을 돌려준다.

    python comment_bot.py                 # 봇 켜기 (여분 PC에서 계속 켜 두기: comment_bot_install.ps1)
    python comment_bot.py --test <링크>   # 텔레그램 없이 화면에 3안만 출력
    python comment_bot.py --set-key       # Anthropic API 키를 .env 에 저장 (화면에 안 보이게 입력)

봇: 연구소 알림 봇(TELEGRAM_BOT_TOKEN)을 같이 쓰고, TELEGRAM_CHAT_ID(대표 본인)가 보낸 메시지에만 반응한다.
안전 규칙 (작업지시서): 댓글은 절대 자동으로 올리지 않는다(고르기·붙여 넣기는 사람) / 계정당 하루 15개 /
  같은 글에 다른 계정 두 개 금지 / 최근 고른 댓글 50개와 비슷하면 다시 만든다 / 키·토큰은 .env 에만.
기록: data/comment_bot.db (PC에만, 저장소에 안 올림) — 날짜, 링크, 작성자, 추천 계정, 고른 유형, 댓글.
"""
import argparse
import difflib
import getpass
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

from common import ROOT, load_env
from post_reader import find_link, read

MODEL = "claude-sonnet-5-5"
KST = timezone(timedelta(hours=9))
DB = ROOT / "data" / "comment_bot.db"
CFG = json.loads((ROOT / "config" / "comment_accounts.json").read_text(encoding="utf-8"))
TYPES = {"A": "숫자 보강", "B": "다른 각도", "C": "질문"}
LOG = ROOT / "data" / "comment_bot.log"

SYSTEM = """너는 한국 경제 SNS에서 남의 글에 댓글을 달아 존재감을 키우는 코치다.
목표는 두 가지다. 글 주인이 "이 댓글 고맙다"고 느끼게 하고, 댓글을 본 독자가 "이 사람 뭘 좀 아네" 하고 프로필을 누르게 하는 것.

댓글 3개를 서로 다른 유형으로 쓴다.
A 숫자 보강: 원글에 없는 숫자나 사실 하나를 더해 글을 풍성하게 만든다. 확실하지 않은 숫자는 절대 지어내지 말고, 모르면 "확인 필요"를 note에 적는다.
B 다른 각도: 먼저 동의하고, 정중하게 다른 경우나 리스크 하나를 덧붙인다. 공격적이거나 가르치는 말투 금지.
C 질문: 글 주인이 답하고 싶어지는 구체적인 질문 하나. 예/아니오로 끝나는 질문 금지.

규칙
- 각 댓글 2~3줄, 80자 안팎. 짧을수록 좋다.
- 링크, 해시태그, 이모지, "제 계정", "팔로우" 같은 홍보 표현 절대 금지.
- 특정 종목 매수,매도 권유, 수익 보장 표현 금지.
- 상위 답글에 이미 나온 내용은 반복하지 않는다.
- AI처럼 보이는 표현 금지: "좋은 인사이트네요", "흥미로운 관점", 빈칸 표시, 과한 칭찬.
- 나열은 가운뎃점 대신 쉼표.
- 원글이 외국어여도 댓글은 원글과 같은 언어로 쓴다.

어느 계정으로 달지 하나 고른다.
{accounts}
댓글 말투는 고른 계정에 맞춘다."""


def system_prompt():
    return SYSTEM.format(accounts="\n".join(f"{a['name']}: {a['fit']}. {a['tone']}." for a in CFG["accounts"]))


# ── 기록 ──
def db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.executescript("""CREATE TABLE IF NOT EXISTS drafts (id INTEGER PRIMARY KEY, created_at TEXT, url TEXT, author TEXT,
                         platform TEXT, topic TEXT, account TEXT, a TEXT, b TEXT, c TEXT, note TEXT, post TEXT);
                       CREATE TABLE IF NOT EXISTS picks (id INTEGER PRIMARY KEY, picked_at TEXT, draft_id INTEGER, url TEXT,
                         author TEXT, account TEXT, type TEXT, comment TEXT);""")
    return c


def picked_account(c, url):
    r = c.execute("SELECT account FROM picks WHERE url=? ORDER BY id DESC LIMIT 1", (url,)).fetchone()
    return r[0] if r else None


def picks_today(c, account):
    day = datetime.now(KST).strftime("%Y-%m-%d")
    return c.execute("SELECT COUNT(*) FROM picks WHERE account=? AND picked_at LIKE ?", (account, day + "%")).fetchone()[0]


def recent_comments(c, n=50):
    return [r[0] for r in c.execute("SELECT comment FROM picks ORDER BY id DESC LIMIT ?", (n,))]


def too_similar(text, olds, cut=0.6):
    return any(difflib.SequenceMatcher(None, text, o).ratio() >= cut for o in olds)


# ── 댓글 만들기 ──
def short_n(v):
    if v is None:
        return "–"
    return f"{v / 10000:.1f}만".replace(".0만", "만") if v >= 10000 else f"{v / 1000:.1f}천".replace(".0천", "천") if v >= 1000 else str(v)


def age(post):
    if post.get("posted_at"):
        m = int((time.time() - post["posted_at"]) // 60)
        return f"{m}분" if m < 60 else f"{m // 60}시간" if m < 1440 else f"{m // 1440}일"
    return post.get("date") or "?"


def generate(post, avoid=(), fixed_account=None):
    import anthropic
    from pydantic import BaseModel

    class Out(BaseModel):
        topic: str
        account: str
        A: str
        B: str
        C: str
        note: str

    msg = (f"플랫폼: {post['platform']}\n작성자: @{post['author']}\n올린 지: {age(post)}\n"
           f"조회 {short_n(post.get('views'))} / 좋아요 {short_n(post.get('likes'))} / 답글 {short_n(post.get('replies'))}\n\n"
           f"[본문]\n{post['text'][:3000]}\n\n[이미 달린 상위 답글]\n" + ("\n".join(post.get("top_replies") or []) or "(없음)"))
    if fixed_account:
        msg += f"\n\n이 글에는 이미 '{fixed_account}' 계정으로 댓글을 골랐어요. account 는 반드시 '{fixed_account}' 로 하세요."
    if avoid:
        msg += "\n\n아래 문장들과 겹치지 않게, 완전히 다른 내용과 표현으로 쓰세요:\n" + "\n".join(f"- {a}" for a in avoid)
    r = anthropic.Anthropic().messages.parse(model=MODEL, max_tokens=1500, system=system_prompt(),
                                             messages=[{"role": "user", "content": msg}], output_format=Out)
    out = r.parsed_output.model_dump()
    names = [a["name"] for a in CFG["accounts"]]
    if fixed_account or out["account"] not in names:
        out["account"] = fixed_account or names[0]
    return out


def make(c, post, avoid=()):
    fixed = picked_account(c, post["url"])
    olds = recent_comments(c)
    out = generate(post, avoid, fixed)
    clash = [out[k] for k in TYPES if too_similar(out[k], olds)]
    if clash:   # 예전에 고른 댓글과 비슷하면 한 번 다시
        out = generate(post, list(avoid) + clash + olds[:10], fixed)
    cur = c.execute("INSERT INTO drafts (created_at, url, author, platform, topic, account, a, b, c, note, post) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (datetime.now(KST).isoformat(timespec="seconds"), post["url"], post["author"], post["platform"],
                     out["topic"], out["account"], out["A"], out["B"], out["C"], out["note"], json.dumps(post, ensure_ascii=False)))
    c.commit()
    return cur.lastrowid, out, fixed


def reply_text(post, out, fixed):
    head = f"작성자 @{post['author']} · 올린 지 {age(post)}"
    if post.get("views") is not None:
        head += f" · 조회 {short_n(post['views'])}"
    lines = [head, f"주제: {out['topic']}", f"댓글 달 계정 추천: {out['account']}"]
    if fixed:
        lines.append(f"(이미 {fixed}(으)로 고른 글이라 같은 계정으로만 만들었어요)")
    for k, name in TYPES.items():
        lines += ["", f"{k} {name}", out[k]]
    if out.get("note"):
        lines += ["", f"확인 필요: {out['note']}"]
    return "\n".join(lines)


# ── 텔레그램 ──
class Bot:
    def __init__(self):
        self.token, self.owner = os.environ["TELEGRAM_BOT_TOKEN"], int(os.environ["TELEGRAM_CHAT_ID"])
        self.api = f"https://api.telegram.org/bot{self.token}"

    def call(self, method, **params):
        r = requests.post(f"{self.api}/{method}", json=params, timeout=70)
        return r.json()

    def say(self, text, buttons=None):
        p = {"chat_id": self.owner, "text": text[:4000], "disable_web_page_preview": True}
        if buttons:
            p["reply_markup"] = {"inline_keyboard": buttons}
        return self.call("sendMessage", **p)


def buttons(did):
    return [[{"text": f"{k} 선택", "callback_data": f"pick:{did}:{k}"} for k in TYPES],
            [{"text": "다시 만들기", "callback_data": f"redo:{did}"}]]


def handle_link(bot, c, url, pasted=None):
    bot.say("읽는 중…")
    post = read(url)
    if not post and pasted is None:
        return "need_text"
    if pasted is not None:
        post = post or {"platform": "threads" if "threads" in url else "instagram", "url": url,
                        "author": url.split("@")[-1].split("/")[0] if "@" in url else "?", "text": pasted,
                        "posted_at": None, "date": None, "views": None, "likes": None, "replies": None, "top_replies": []}
        post["text"] = post["text"] or pasted
    if picked_account(c, post["url"]):
        bot.say(f"이미 {picked_account(c, post['url'])}(으)로 고른 글이에요. 같은 글에 다른 계정으로는 달지 마세요.")
    did, out, fixed = make(c, post)
    bot.say(reply_text(post, out, fixed), buttons(did))
    return "ok"


def handle_pick(bot, c, did, kind):
    row = c.execute("SELECT url, author, account, a, b, c FROM drafts WHERE id=?", (did,)).fetchone()
    if not row:
        return bot.say("지난 안을 찾지 못했어요. 링크를 다시 보내 주세요.")
    url, author, account, *abc = row
    other = picked_account(c, url)
    if other and other != account:
        return bot.say(f"이 글은 이미 {other}(으)로 골랐어요. 같은 글에 계정 두 개는 안 돼요.")
    limit = CFG.get("daily_limit_per_account", 15)
    if picks_today(c, account) >= limit:
        return bot.say(f"오늘 {account} 댓글 {limit}개를 다 골랐어요. 오늘은 그만 달아요.")
    comment = abc["ABC".index(kind)]
    c.execute("INSERT INTO picks (picked_at, draft_id, url, author, account, type, comment) VALUES (?,?,?,?,?,?,?)",
              (datetime.now(KST).isoformat(timespec="seconds"), did, url, author, account, TYPES[kind], comment))
    c.commit()
    bot.say(comment)
    bot.say(f"↑ 길게 눌러 복사해서 {account} 계정으로 직접 붙여 넣으세요. (오늘 {account} {picks_today(c, account)}/{limit})")


def handle_redo(bot, c, did):
    row = c.execute("SELECT a, b, c, post FROM drafts WHERE id=?", (did,)).fetchone()
    if not row:
        return bot.say("지난 안을 찾지 못했어요. 링크를 다시 보내 주세요.")
    post = json.loads(row[3])
    bot.say("다시 만드는 중…")
    nid, out, fixed = make(c, post, avoid=row[:3])
    bot.say(reply_text(post, out, fixed), buttons(nid))


def log(*a):
    line = f"{datetime.now(KST):%m/%d %H:%M:%S} " + " ".join(map(str, a))
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run():
    bot, c, offset, waiting = Bot(), db(), None, None   # waiting: 본문 붙여 넣기를 기다리는 링크
    bot.call("deleteWebhook")
    log("댓글 봇 켜짐")
    while True:
        try:
            ups = bot.call("getUpdates", timeout=50, offset=offset, allowed_updates=["message", "callback_query"]).get("result", [])
        except requests.RequestException as e:
            log("연결 끊김, 10초 뒤 다시:", e)
            time.sleep(10)
            continue
        for u in ups:
            offset = u["update_id"] + 1
            try:
                if "callback_query" in u:
                    q = u["callback_query"]
                    if q["from"]["id"] != bot.owner:
                        continue
                    bot.call("answerCallbackQuery", callback_query_id=q["id"])
                    kind, did, *rest = q["data"].split(":")
                    if kind == "pick":
                        handle_pick(bot, c, int(did), rest[0])
                    elif kind == "redo":
                        handle_redo(bot, c, int(did))
                    continue
                m = u.get("message") or {}
                if (m.get("from") or {}).get("id") != bot.owner:
                    continue      # 대표 말고 다른 사람은 무시
                text = m.get("text") or m.get("caption") or ""
                url = find_link(text)
                if url:
                    waiting = url if handle_link(bot, c, url) == "need_text" else None
                    if waiting:
                        bot.say("본문을 읽지 못했어요. 글 본문을 복사해서 붙여 넣어 주세요.")
                elif waiting and text.strip():
                    handle_link(bot, c, waiting, pasted=text.strip())
                    waiting = None
                elif text.strip():
                    bot.say("글 링크를 보내주세요. (쓰레드 또는 인스타)")
            except Exception as e:     # 한 건이 실패해도 봇은 계속
                log("처리 실패:", repr(e))
                bot.say(f"만들다가 문제가 생겼어요: {type(e).__name__}. 잠시 뒤 다시 보내 주세요.")




def set_key():
    from get_token import set_env
    key = getpass.getpass("Anthropic API 키를 붙여 넣고 Enter (화면에 안 보여요): ").strip()
    if not key.startswith("sk-"):
        print("키 모양이 아니에요. 다시 실행해 주세요.")
        return 1
    set_env({"ANTHROPIC_API_KEY": key})
    print("✅ .env 에 저장했어요.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test")
    ap.add_argument("--set-key", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if a.set_key:
        return set_key()
    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY 가 없어요 — python comment_bot.py --set-key 로 먼저 넣어 주세요.")
        return 1
    if a.test:
        post = read(a.test)
        if not post:
            print("글을 읽지 못했어요.")
            return 1
        c = db()
        _, out, fixed = make(c, post)
        print(reply_text(post, out, fixed))
        return
    run()


if __name__ == "__main__":
    sys.exit(main())
