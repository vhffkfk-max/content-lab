"""카드뉴스 한 장(HTML) → 1080×1350 JPG. 크롬(헤드리스)으로 그려서 글자·여백이 정확하다.

    from publish.render import render
    render(["<div class=slide>...</div>", ...], out_dir, "name")   # → [name-1.jpg, ...]
캔바로 가져가 내보내면 글자가 가끔 깨져서(2026-10-28 확인) 발행용 이미지는 여기서 만든다.
글꼴: 내 PC는 윈도 Noto Sans/Serif KR, 깃허브(우분투)는 fonts-noto-cjk 의 Noto Sans/Serif CJK KR.
"""
import os
import pathlib
import shutil
import subprocess
import tempfile

from PIL import Image

from common import ROOT

W, H = 1080, 1350
BROWSERS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", "google-chrome", "chromium", "chromium-browser"]
FONT_FILES = {"HSans": ["C:/Windows/Fonts/NotoSansKR-VF.ttf"], "HSerif": ["C:/Windows/Fonts/NotoSerifKR-VF.ttf"]}
FONT_LOCAL = {"HSans": ["Noto Sans KR", "Noto Sans CJK KR"], "HSerif": ["Noto Serif KR", "Noto Serif CJK KR"]}
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
        srcs += [f"local('{n}')" for n in FONT_LOCAL[fam]]
        out.append(f"@font-face{{font-family:{fam};src:{','.join(srcs)};font-weight:100 900}}")
    return "\n".join(out)


def page(body, css):
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>
{font_css()}
html,body{{margin:0;padding:0;width:{W}px;height:{H}px;overflow:hidden}}
*{{box-sizing:border-box}}
{css}
</style></head><body>{body}</body></html>"""


def render(slides, out_dir, name, css=""):
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    exe, files = browser(), []
    with tempfile.TemporaryDirectory() as tmp:
        for i, body in enumerate(slides, 1):
            html = pathlib.Path(tmp) / f"s{i}.html"
            html.write_text(page(body, css), encoding="utf-8")
            png = pathlib.Path(tmp) / f"s{i}.png"
            subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                            "--allow-file-access-from-files", "--virtual-time-budget=3000", f"--window-size={W},{H}",
                            f"--screenshot={png}", html.as_uri()], check=True, capture_output=True, timeout=90)
            jpg = out_dir / f"{name}-{i}.jpg"
            Image.open(png).convert("RGB").crop((0, 0, W, H)).save(jpg, "JPEG", quality=93)
            files.append(jpg)
    return files


def asset_uri(rel):
    p = ASSETS / rel
    return p.as_uri() if p.exists() else ""
