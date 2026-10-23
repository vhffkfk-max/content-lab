"""내가 운영하는 텔레그램 그룹의 회원별 참여도 순위를 엑셀로 뽑는다 (상품 지급용, 내 PC에만 저장).

    python tg_participation.py --chat -1004375748687 --start 2026-10-01 --end 2026-10-23
    python tg_participation.py --chat -1004375748687 --start 2026-10-01 --end 2026-10-31

점수 = 메시지(10자 이상) 1점 + 참여한 날 3점 + 받은 반응 1점 + 받은 답글 2점
  - 10자 미만 메시지(ㅋㅋ, 스티커 등)는 '짧은 메시지'로 따로 세고 점수에는 넣지 않는다.
  - 받은 답글은 다른 회원이 단 답글만 센다 (자기 글에 단 답글 제외).
  - 관리자·봇은 순위에서 뺀다 (엑셀 '제외' 시트에 따로 표시).
결과: output/participation/참여도_<방>_<시작>_<끝>.xlsx  (회원 이름이 들어가서 저장소에 올리지 않음)
"""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from common import OUTPUT_DIR
from tg_login import client

KST = timezone(timedelta(hours=9))
MIN_CHARS = 10
W_MSG, W_DAY, W_REACT, W_REPLY = 1, 3, 1, 2


def name_of(u):
    if u is None:
        return "(알 수 없음)"
    full = " ".join(x for x in (getattr(u, "first_name", None), getattr(u, "last_name", None)) if x)
    return full or getattr(u, "title", None) or str(u.id)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat", required=True, help="방 id (telegram_chats.csv 의 id)")
    ap.add_argument("--start", required=True, help="시작일 YYYY-MM-DD (한국시간, 포함)")
    ap.add_argument("--end", required=True, help="끝일 YYYY-MM-DD (한국시간, 포함)")
    args = ap.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=KST)
    end = datetime.fromisoformat(args.end).replace(tzinfo=KST) + timedelta(days=1)

    stat = defaultdict(lambda: {"msgs": 0, "short": 0, "days": set(), "reactions": 0, "replies": 0})
    users, owner_of = {}, {}
    replies_to = []
    with client() as c:
        chat = c.get_entity(int(args.chat))
        title = getattr(chat, "title", args.chat)
        from telethon.tl.types import ChannelParticipantsAdmins
        admins = {u.id for u in c.get_participants(chat, filter=ChannelParticipantsAdmins)}
        total = 0
        for m in c.iter_messages(chat, offset_date=end):
            if m.date < start:
                break
            if m.action or not m.sender_id:   # 입장·퇴장 같은 안내 메시지, 익명 관리자 글
                continue
            uid = m.sender_id
            if uid not in users:
                users[uid] = m.sender
            owner_of[m.id] = uid
            s = stat[uid]
            text = m.message or ""
            if len(text.strip()) >= MIN_CHARS:
                s["msgs"] += 1
            else:
                s["short"] += 1
            s["days"].add(m.date.astimezone(KST).date())
            if m.reactions:
                s["reactions"] += sum(r.count for r in m.reactions.results)
            if m.reply_to and m.reply_to.reply_to_msg_id:
                replies_to.append((m.reply_to.reply_to_msg_id, uid))
            total += 1
    for target, uid in replies_to:
        owner = owner_of.get(target)
        if owner and owner != uid:
            stat[owner]["replies"] += 1

    rows, excluded = [], []
    for uid, s in stat.items():
        u = users.get(uid)
        row = {"이름": name_of(u), "아이디": f"@{u.username}" if getattr(u, "username", None) else "",
               "회원번호": uid, "메시지(10자 이상)": s["msgs"], "짧은 메시지": s["short"], "참여한 날": len(s["days"]),
               "받은 반응": s["reactions"], "받은 답글": s["replies"]}
        row["점수"] = (W_MSG * s["msgs"] + W_DAY * len(s["days"]) + W_REACT * s["reactions"] + W_REPLY * s["replies"])
        if uid in admins or getattr(u, "bot", False):
            row["제외 이유"] = "봇" if getattr(u, "bot", False) else "관리자"
            excluded.append(row)
        else:
            rows.append(row)
    rows.sort(key=lambda r: (-r["점수"], -r["참여한 날"], -r["메시지(10자 이상)"]))
    for i, r in enumerate(rows, 1):
        r["순위"] = i

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "순위"
    cols = ["순위", "이름", "아이디", "점수", "참여한 날", "메시지(10자 이상)", "받은 반응", "받은 답글", "짧은 메시지", "회원번호"]
    ws.append(cols)
    for r in rows:
        ws.append([r[k] for k in cols])
    ws2 = wb.create_sheet("제외")
    ws2.append(["제외 이유"] + cols[1:])
    for r in excluded:
        ws2.append([r["제외 이유"]] + [r[k] for k in cols[1:]])
    ws3 = wb.create_sheet("기준")
    for line in [("방", title), ("기간", f"{args.start} ~ {args.end} (한국시간)"),
                 ("뽑은 시각", datetime.now(KST).strftime("%Y-%m-%d %H:%M")), ("읽은 메시지", total),
                 ("점수", f"메시지(10자 이상) {W_MSG}점 + 참여한 날 {W_DAY}점 + 받은 반응 {W_REACT}점 + 받은 답글 {W_REPLY}점"),
                 ("짧은 메시지", f"{MIN_CHARS}자 미만(ㅋㅋ, 스티커, 사진만 등)은 따로 세고 점수에서 제외"),
                 ("받은 답글", "다른 회원이 단 답글만 (자기 글 답글 제외)"), ("제외", "관리자·봇은 순위에서 제외")]:
        ws3.append(list(line))
    for sheet in (ws, ws2, ws3):
        for cell in sheet[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="F3D6E2")
        for col in sheet.columns:
            sheet.column_dimensions[col[0].column_letter].width = max(10, min(40, max(len(str(c.value or "")) for c in col) * 1.6))
    out_dir = OUTPUT_DIR / "participation"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"참여도_{title}_{args.start}_{args.end}.xlsx".replace("/", "_")
    wb.save(out)
    print(f"✅ {title}: 메시지 {total}개, 순위 {len(rows)}명 (제외 {len(excluded)}명) → {out}")
    for r in rows[:10]:
        print(f"  {r['순위']:>2}. {r['이름']} {r['아이디']} — {r['점수']}점 (날 {r['참여한 날']}, 메시지 {r['메시지(10자 이상)']}, 반응 {r['받은 반응']}, 답글 {r['받은 답글']})")


if __name__ == "__main__":
    main()
