"""계정별 영상 제작 설정 한 곳. 새 계정은 ACCOUNTS 에 한 줄 더한다.

화면 디자인은 계정마다 다른 게 맞아서 각 제작기에 남기고, 겹치던 부품(음성·입 모양·렌더·인코딩)은 engine.py 하나를 쓴다.
실행: python reels/reel.py 목록 / python reels/reel.py 계정 "주제" [그 제작기의 옵션]
"""
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
SOLGAE = pathlib.Path.home() / "Desktop" / "솔개"
LAB = SOLGAE / "insta-research"   # 대화극·비교 제작기는 PC 개발 폴더에만 있다

# maker: 제작기 파일, cwd: 실행 폴더, args: 앞에 붙는 인자({topic} 자리에 주제), voice: 안내용
ACCOUNTS = {
    "핫코노미": {"maker": HERE / "make_reel.py", "cwd": HERE, "args": ["{topic}", "--board"], "voice": "Supertonic M3", "what": "뉴스 릴스 컷 보드 (영상은 보드에서 버튼으로)"},
    "핫코노미A": {"maker": SOLGAE / "hotconomy-reels" / "src" / "auto.py", "cwd": SOLGAE / "hotconomy-reels", "args": ["{topic}"], "voice": "GPT-SoVITS", "what": "핫코노미·궁금이 대화 영상"},
    "대화극": {"maker": LAB / "reels" / "duo_reel.py", "cwd": LAB / "reels", "args": ["{topic}"], "voice": "Supertonic M3·F2", "what": "너굴 팀장·햄찌 대화극"},
    "자산백배": {"maker": LAB / "reels" / "compare_reel.py", "cwd": LAB / "reels", "args": ["{topic}"], "voice": "Supertonic", "what": "3자 비교 릴스"},
    "오뉴월드": {"maker": LAB / "ohneworld" / "studio.py", "cwd": LAB / "ohneworld", "args": ["만들기", "{topic}"], "voice": "Supertonic M3", "what": "카드뉴스·릴스 (주제 자리에 글 이름, 캔바·캡컷은 studio.py 그대로)"},
}

# 사이트 요청은 암호가 없어서 하루 처리량을 막는다 (자동 보드는 따로)
DAILY = {"board": 15, "make": 12, "hot": 10, "asset": 10, "save": 150, "voice": 150, "format": 150, "photo": 200}


def maker_path(name):
    return ACCOUNTS[name]["maker"]
