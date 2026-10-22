"""output/site/*.json 과 site/ 화면 파일로 독립 웹사이트(public/index.html)를 만든다.

    python build_site.py   →  public/index.html  (GitHub Pages 가 이 폴더를 배포)
"""
import json
import re

from common import OUTPUT_DIR, ROOT

DATASETS = ["summary", "recs", "rec_reasons", "rec_examples", "insights", "topics",
            "patterns", "accounts", "top_posts", "drafts", "calendar", "this_week", "this_week_accounts"]


def main():
    site = OUTPUT_DIR / "site"
    data = {}
    for name in DATASETS:
        path = site / f"{name}.json"
        data[name] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    body = (ROOT / "site" / "body.html").read_text(encoding="utf-8")
    m = re.search(r"<script>.*</script>", body, re.S)
    script, markup = m.group(0), body[:m.start()] + body[m.end():]
    # </script> 가 데이터 안에 있어도 페이지가 깨지지 않게
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    shell = (ROOT / "site" / "shell.html").read_text(encoding="utf-8")
    html = (shell.replace("<!--BODY-->", markup)
                 .replace("/*DATA*/{}", payload)
                 .replace("<!--SCRIPT-->", script))
    out = ROOT / "public"
    out.mkdir(exist_ok=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"✅ 사이트 생성: {out / 'index.html'} ({len(html.encode()) // 1024}KB)")


if __name__ == "__main__":
    main()
