"""@hotconomy 프로필 맨 위 고정 게시물 3장 (프로필 소개글과 같은 말, 카드뉴스와 같은 검정+빨강 톤).

    python -m publish.pinned [출력 폴더]      # → pinned-1.jpg ~ pinned-3.jpg (1080×1350)

프로필 격자는 3:4로 보여 좌우 34px씩 잘리니 글은 x 72~1008 안에 둔다(forms 공통 규칙).
세 장이 격자 첫 줄에 나란히 보이므로 위쪽 번호(01~03)와 제목 위치를 맞춘다.
"""
import sys

from common import ROOT
from publish import forms
from publish.render import render

CSS = forms.CSS + """
.pin-bg{position:absolute;inset:0;background:radial-gradient(circle at 85% 10%,#6a1216 0,#0b0b0d00 50%),radial-gradient(circle at 10% 95%,#4a1a08 0,#0b0b0d00 45%)}
.pin-no{position:absolute;left:72px;right:72px;top:150px;display:flex;align-items:center;gap:22px;font-size:40px;font-weight:800;color:var(--sub)}
.pin-no b{font-size:60px;color:var(--ac);font-weight:900}
.pin-t{position:absolute;left:72px;right:72px;top:290px;font-size:112px;font-weight:900;line-height:1.16;letter-spacing:-3px}
.pin-body{position:absolute;left:72px;right:72px;top:600px;bottom:240px;display:flex;flex-direction:column;justify-content:center;gap:34px}
.pin-row{display:flex;align-items:center;gap:30px;background:#ffffff0d;border:2px solid #ffffff1a;border-radius:30px;padding:30px 36px}
.pin-row .k{width:110px;height:110px;border-radius:50%;background:var(--ac);display:flex;align-items:center;justify-content:center;font-size:52px;font-weight:900;flex:none}
.pin-row .n{font-size:54px;font-weight:900;line-height:1.2}
.pin-row .d{font-size:36px;color:var(--sub);margin-top:6px;line-height:1.35}
.pin-logo{width:300px;height:300px;border-radius:50%;box-shadow:0 0 80px #e3262b88}
.pin-note{position:absolute;left:72px;right:72px;bottom:140px;text-align:center;font-size:34px;font-weight:700;color:var(--sub)}
"""


def _row(k, n, d):
    return f'<div class="pin-row"><div class="k">{k}</div><div><div class="n">{forms.md(n)}</div><div class="d">{forms.md(d)}</div></div></div>'


def _slide(no, label, title, body, note=""):
    note = f'<div class="pin-note">{forms.md(note)}</div>' if note else ""
    return (f'<div class="s"><div class="pin-bg"></div><div class="pin-no"><b>{no}</b>{label}</div>'
            f'<div class="pin-t" style="font-size:{forms.fit(title, 900, 112, 80, 1.0)}px">{forms.md(title)}</div><div class="pin-body">{body}</div>{note}{forms.foot(0, 0, page_no=False)}</div>')


def slides():
    logo = f'<div class="center"><img class="pin-logo" src="{forms.LOGO}"></div>' if forms.LOGO else ""
    one = _slide("01", "핫코노미는", "오늘 경제,\n**숫자 하나**로 끝",
                 logo + '<div class="b-l center" style="font-size:50px">어려운 경제 뉴스를<br><b class="hl">내 지갑</b> 얘기로 바꿔 드려요</div>',
                 "대출 이자, 월급, 장바구니, 환전, 내 계좌까지")
    two = _slide("02", "매일 보는 것", "코스피, 환율, 반도체\n**1분 요약**",
                 _row("📉", "코스피", "오늘 시장이 왜 움직였는지")
                 + _row("💱", "환율", "환전, 해외결제에 어떤 영향인지")
                 + _row("🔬", "반도체", "삼성전자, SK하이닉스 소식 정리"),
                 "⏰ 매일 저녁 업데이트")
    three = _slide("03", "자료 받는 법", "댓글 하나면\n**정리 자료**를 DM으로",
                   _row("1", "카드 마지막 장 확인", "글마다 댓글 키워드가 있어요")
                   + _row("2", "댓글에 키워드 남기기", "예: '환율', '금리'")
                   + _row("3", "DM으로 한 장 정리 받기", "그 주제를 한 장에 정리해 보내드려요"),
                   "📢 실시간 속보는 프로필 링크 텔레그램에서")
    return [one, two, three]


def main(out=None):
    out = out or ROOT / "output" / "cardnews" / "pinned"
    return render(slides(), out, "pinned", CSS)


if __name__ == "__main__":
    print("\n".join(map(str, main(sys.argv[1] if len(sys.argv) > 1 else None))))
