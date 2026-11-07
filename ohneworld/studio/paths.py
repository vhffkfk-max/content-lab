"""폴더 위치와 PC별 설정. 설정은 config.json 에서 고칩니다."""
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKUP_NAVER = ROOT / "백업" / "네이버"
BACKUP_IG = ROOT / "백업" / "인스타"
DATA = ROOT / "데이터"
ANALYSIS = ROOT / "분석"
METRICS = ROOT / "성과" / "수치.csv"
MATERIAL = ROOT / "재료"
RESULT = ROOT / "결과"
STYLE = ROOT / "style" / "말희아빠_스타일.md"
FORMATS = ROOT / "studio" / "formats.json"

CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

# vendor/llm.py 를 `import llm` 으로 쓸 수 있게
sys.path.insert(0, str(ROOT / "studio" / "vendor"))

FONT_FILES = {"HSans": ["C:/Windows/Fonts/NotoSansKR-VF.ttf"], "HSerif": ["C:/Windows/Fonts/NotoSerifKR-VF.ttf"],
              "Hand": [str(ROOT / "fonts" / "Gaegu-Bold.ttf")]}   # 손글씨: Gaegu Bold (OFL, 구글 폰트)


def font_css():
    out = []
    for fam, files in FONT_FILES.items():
        srcs = [f"url('{pathlib.Path(f).as_uri()}')" for f in files if os.path.exists(f)]
        if srcs:
            out.append(f"@font-face{{font-family:{fam};src:{','.join(srcs)};font-weight:100 900}}")
    return "\n".join(out)


def save_json(path, obj):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def load_json(path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
