"""API 연결 전에 프로그램이 잘 도는지 확인하기 위한 가짜 데이터 생성기.

data/demo.db 에만 쓰고 실제 데이터(data/insta.db)는 건드리지 않습니다.
    python demo_data.py
    python analyze.py --db data/demo.db
"""
import random
from datetime import datetime, timedelta, timezone

from common import DATA_DIR, connect

random.seed(7)
DB = DATA_DIR / "demo.db"

ACCOUNTS = [  # (아이디, 지역, 카테고리, 팔로워)
    ("demo_kr_usstock", "KR", "미국주식", 182000), ("demo_kr_money1min", "KR", "경제일반", 96000),
    ("demo_kr_kospi", "KR", "국내주식", 54000), ("demo_kr_coinlab", "KR", "코인", 71000),
    ("demo_kr_dividend", "KR", "미국주식", 33000), ("demo_kr_econnews", "KR", "경제일반", 240000),
    ("demo_kr_btcdaily", "KR", "코인", 28000), ("demo_kr_valueup", "KR", "국내주식", 19000),
    ("demo_us_stockguy", "US", "미국주식", 820000), ("demo_us_macro", "US", "경제일반", 410000),
    ("demo_us_cryptoqueen", "US", "코인", 365000), ("demo_us_etfdad", "US", "미국주식", 150000),
    ("demo_us_earnings", "US", "미국주식", 98000), ("demo_us_btcmag", "US", "코인", 380000),
]

KR_CAPTIONS = {
    "AI·반도체": ["엔비디아 실적 앞두고 꼭 알아야 할 3가지", "HBM 수혜주 총정리", "반도체 지금 사도 될까?"],
    "금리·연준": ["FOMC 금리 결정, 내 계좌에 미치는 영향 정리", "파월 발언 1분 요약", "금리인하 오면 뭘 사야 할까?"],
    "비트코인": ["비트코인 지금 들어가도 될까?", "비트코인 반감기 이후 흐름 정리", "속보: 비트코인 신고가"],
    "배당": ["월배당 ETF 5개 비교", "배당주로 월 100만원 만들기", "SCHD 지금 사도 될까?"],
    "국내 대형주": ["삼성전자 지금 바닥일까?", "코스피 밸류업 수혜주 정리", "오늘 코스피 왜 빠졌나"],
    "초보·투자마인드": ["주식 초보가 절대 하면 안 되는 실수 5가지", "복리의 힘, 20대에 알았다면", "부자들의 투자 습관"],
    "환율·달러": ["환율 1400원, 달러 지금 사야 할까?", "원달러 환율 정리"],
    "알트코인": ["이더리움 ETF 승인 영향 정리", "솔라나 지금 괜찮을까?"],
    "실적발표": ["이번주 실적 발표 일정"],
}
US_CAPTIONS = {
    "AI·반도체": ["NVIDIA earnings: 3 things to watch", "Why I'm buying more NVDA", "Top 5 AI chip stocks"],
    "실적발표": ["Earnings season: 5 stocks I'm watching", "Big tech earnings explained", "This guidance changed everything"],
    "금리·연준": ["The Fed just cut rates. Here's what it means", "Rate cuts explained in 60 seconds"],
    "비트코인": ["Bitcoin to 200k? My honest take", "Breaking: Bitcoin ETF inflows record", "Why I keep stacking BTC"],
    "ETF·지수투자": ["VOO vs QQQ: which is better?", "The only 3 ETFs you need", "Index fund investing guide"],
    "초보·투자마인드": ["5 money mistakes beginners make", "How compound interest made me a millionaire"],
    "알트코인": ["Top 3 altcoins for this cycle", "Solana explained"],
    "연금·절세": ["Roth IRA explained for beginners", "Stop overpaying taxes on your investments"],
    "급락·변동성": ["Market crash? Don't panic, do this", "VIX is spiking: what I'm doing"],
}
# 주제별 반응 배수: 해외에서 실적발표·AI가 강하고, 한국은 배당·비트코인이 잘 되는 상황을 가정
BOOST = {("US", "실적발표"): 2.3, ("US", "AI·반도체"): 1.9, ("US", "연금·절세"): 1.5,
         ("KR", "배당"): 1.6, ("KR", "비트코인"): 1.5, ("KR", "AI·반도체"): 1.4, ("KR", "초보·투자마인드"): 1.3,
         ("KR", "국내 대형주"): 0.8}
FORMAT_BOOST = {"REELS": 1.5, "CAROUSEL_ALBUM": 1.25, "IMAGE": 0.8}


def main():
    if DB.exists():
        DB.unlink()
    conn = connect(DB)
    now = datetime.now(timezone.utc)
    pid = 0
    for username, region, category, followers in ACCOUNTS:
        caps = KR_CAPTIONS if region == "KR" else US_CAPTIONS
        base_er = random.uniform(0.008, 0.03)
        for d in (14, 7, 0):  # 팔로워 성장 추이를 보여주기 위한 스냅샷 3회
            conn.execute("INSERT INTO account_snapshots VALUES (?,?,?,?)",
                         (username, (now - timedelta(days=d)).date().isoformat(),
                          int(followers * (1 - d * random.uniform(0.0005, 0.003))), 500))
        conn.execute("INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?)",
                     (username, region, category, username, "데모 계정", followers, 500, now.isoformat()))
        for _ in range(random.randint(20, 40)):
            topic = random.choice(list(caps))
            caption = random.choice(caps[topic]) + "\n\n#주식 #경제"
            mtype, ptype = random.choice([("VIDEO", "REELS"), ("CAROUSEL_ALBUM", "FEED"), ("IMAGE", "FEED")])
            # 한국 계정은 저녁(한국시간 18~21시 = UTC 9~12시) 게시물이 잘 되는 상황
            ts = now - timedelta(days=random.uniform(0, 55))
            ts = ts.replace(hour=random.choice([0, 3, 5, 9, 10, 11, 13, 14]), minute=random.randint(0, 59), second=0)
            evening = region == "KR" and 9 <= ts.hour < 12
            mult = BOOST.get((region, topic), 1.0) * FORMAT_BOOST[ptype if ptype == "REELS" else mtype]
            mult *= 1.3 if evening else 1.0
            mult *= 1.25 if any(ch.isdigit() for ch in caption.split("\n")[0]) else 1.0
            likes = int(followers * base_er * mult * random.lognormvariate(0, 0.45))
            comments = int(likes * random.uniform(0.01, 0.05))
            pid += 1
            conn.execute("INSERT INTO posts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (f"demo{pid}", username, caption, mtype, ptype,
                          ts.strftime("%Y-%m-%dT%H:%M:%S+0000"), f"https://www.instagram.com/p/demo{pid}/",
                          likes, comments, None, now.isoformat()))
    for tag, region in [("미국주식", "KR"), ("코인", "KR"), ("stocks", "US"), ("bitcoin", "US")]:
        for i in range(25):
            topic = random.choice(list(KR_CAPTIONS if region == "KR" else US_CAPTIONS))
            cap = random.choice((KR_CAPTIONS if region == "KR" else US_CAPTIONS)[topic])
            ts = now - timedelta(days=random.uniform(0, 20))
            conn.execute("INSERT INTO hashtag_posts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (f"h{tag}{i}", tag, region, "", cap, "IMAGE", ts.strftime("%Y-%m-%dT%H:%M:%S+0000"),
                          None, random.randint(500, 20000), random.randint(5, 400), now.isoformat()))
    conn.commit()
    print(f"✅ 데모 데이터 생성: 계정 {len(ACCOUNTS)}개, 게시물 {pid}개 → {DB}")
    print("   다음: python analyze.py --db data/demo.db")


if __name__ == "__main__":
    main()
