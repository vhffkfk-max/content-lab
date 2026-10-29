"""카드뉴스 한 장(HTML) → 1080×1350 JPG. 크롬(헤드리스)으로 그려서 글자·여백이 정확하다.

    from publish.render import render
    render(["<div class=slide>...</div>", ...], out_dir, "name")   # → [name-1.jpg, ...]
캔바로 가져가 내보내면 글자가 가끔 깨져서(2026-10-28 확인) 발행용 이미지는 여기서 만든다.
캔바 수정용 사본은 publish/canva_copy.py (같은 HTML → 배경 그림 + 글상자 PPTX).
글꼴: 내 PC는 윈도 Noto Sans/Serif KR 가변 글꼴, 깃허브(우분투)는 fonts-noto-cjk 의 Noto Sans/Serif CJK KR (CSS 대체 글꼴).
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

from PIL import Image

from common import ROOT

W, H = 1080, 1350
BROWSERS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", "google-chrome", "chromium", "chromium-browser"]
FONT_FILES = {"HSans": ["C:/Windows/Fonts/NotoSansKR-VF.ttf"], "HSerif": ["C:/Windows/Fonts/NotoSerifKR-VF.ttf"]}
ASSETS = ROOT / "assets"


def browser():
    for b in BROWSERS:
        if os.path.exists(b) or shutil.which(b):
            return b
    raise RuntimeError("크롬이 없어요 — 카드뉴스를 그릴 수 없어요.")


def font_css():
    out = []
    for fam, files in FONT_FILES.items():
        srcs = [f"url('{pathlib.Path(f).as_uri()}')" for f in files if os.path.exists(f)]
        if not srcs:
            continue   # 우분투: local() 은 굵기 하나만 잡혀서 굵은 글씨가 사라짐 → 시스템 Noto CJK 로 넘긴다 (forms CSS 의 대체 글꼴)
        out.append(f"@font-face{{font-family:{fam};src:{','.join(srcs)};font-weight:100 900}}")
    return "\n".join(out)


def page(body, css):
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>
{font_css()}
html,body{{margin:0;padding:0;width:{W}px;height:{H}px;overflow:hidden}}
*{{box-sizing:border-box}}
{css}
</style></head><body>{body}</body></html>"""


def chrome(html_text, tmp, *args):
    """HTML 을 크롬(헤드리스)으로 열어 args(--screenshot=… / --dump-dom)대로 → 표준출력."""
    html = pathlib.Path(tmp) / f"p{abs(hash(html_text))}.html"
    html.write_text(html_text, encoding="utf-8")
    linux = ["--no-sandbox"] if sys.platform.startswith("linux") else []
    r = subprocess.run([browser(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1", *linux,
                        "--allow-file-access-from-files", "--virtual-time-budget=3000", f"--window-size={W},{H}",
                        *args, html.as_uri()], check=True, capture_output=True, timeout=90)
    return r.stdout.decode("utf-8", "ignore")


def render(slides, out_dir, name, css=""):
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, body in enumerate(slides, 1):
            png = pathlib.Path(tmp) / f"s{i}.png"
            chrome(page(body, css), tmp, f"--screenshot={png}")
            jpg = out_dir / f"{name}-{i}.jpg"
            Image.open(png).convert("RGB").crop((0, 0, W, H)).save(jpg, "JPEG", quality=93)
            files.append(jpg)
    return files


def asset_uri(rel):
    p = ASSETS / rel
    return p.as_uri() if p.exists() else ""
