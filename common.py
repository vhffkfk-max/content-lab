"""공통 설정: .env 읽기, 경로, SQLite 스키마."""
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
ENV_PATH = ROOT / ".env"
DEFAULT_DB = DATA_DIR / "insta.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    username TEXT PRIMARY KEY,
    region TEXT,
    category TEXT,
    name TEXT,
    biography TEXT,
    followers INTEGER,
    media_count INTEGER,
    last_collected TEXT
);
CREATE TABLE IF NOT EXISTS account_snapshots (
    username TEXT,
    date TEXT,
    followers INTEGER,
    media_count INTEGER,
    PRIMARY KEY (username, date)
);
CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    username TEXT,
    caption TEXT,
    media_type TEXT,
    product_type TEXT,
    timestamp TEXT,
    permalink TEXT,
    likes INTEGER,
    comments INTEGER,
    views INTEGER,
    collected_at TEXT
);
CREATE TABLE IF NOT EXISTS hashtag_posts (
    id TEXT,
    tag TEXT,
    region TEXT,
    category TEXT,
    caption TEXT,
    media_type TEXT,
    timestamp TEXT,
    permalink TEXT,
    likes INTEGER,
    comments INTEGER,
    collected_at TEXT,
    PRIMARY KEY (id, tag)
);
"""


def load_env(path=ENV_PATH):
    """.env 파일의 KEY=VALUE 를 환경변수로 읽어온다 (외부 패키지 없이)."""
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def connect(db_path=DEFAULT_DB):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
