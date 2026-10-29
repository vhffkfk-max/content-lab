"""output/site/*.json 과 site/ 화면 파일로 독립 웹사이트(public/index.html)를 만든다.

    python build_site.py   →  public/index.html  (GitHub Pages 가 이 폴더를 배포)
"""
import json
import re

from common import OUTPUT_DIR, ROOT

DATASETS = ["summary", "recs", "rec_reasons", "rec_examples", "insights", "topics",
            "patterns", "accounts", "top_posts", "drafts", "calendar", "this_week", "this_week_accounts",
            "google_meta", "google_topics", "google_headlines", "google_trends", "google_opportunities",
            "press_headlines", "press_popular", "threads_meta", "threads_topics", "threads_posts",
            "acc_details", "acc_patterns", "acc_tops", "own_meta", "own_posts", "own_formats",
            "fo_hot", "fo_topics", "imports", "threads_saved", "threads_saved_stats", "threads_ai",
            "thx_meta", "thx_hot", "thx_top", "thx_rising", "thx_topics", "thx_formats", "thx_accounts", "thx_rank", "thx_foreign", "thx_viral", "thx_viral_meta", "thx_live", "thx_live_meta", "igx_live", "igx_live_meta", "ig_health",
            "ig_slides", "thm_meta", "thm_posts", "thm_feed", "thm_ai",
            "x_meta", "x_trump", "x_rank", "x_groups", "x_accounts", "x_ai",
            "tg_meta", "tg_chats", "tg_hot", "tg_mine", "tg_hours", "tg_lengths", "tg_media", "tg_ai",
            "tg_growth", "tg_streak", "tg_slots", "tg_shared", "tg_rank", "tg_rewrites", "trd_rooms", "trd_posts", "live_meta"]


def main():
    site = OUTPUT_DIR / "site"
    data = {}
    for name in DATASETS:
        path = site / f"{name}.json"
        data[name] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    fb_path = ROOT / "data" / "feedback.json"   # 사이트에서 남긴 후기·콘텐츠 기록
    data["feedback"] = [json.loads(fb_path.read_text(encoding="utf-8"))] if fb_path.exists() else []
    cfg_path = ROOT / "site" / "site_config.json"
    data["site_config"] = [json.loads(cfg_path.read_text(encoding="utf-8"))] if cfg_path.exists() else []
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
    # 개인정보처리방침·데이터 삭제 안내·쓰레드 콜백 페이지 (메타 앱 심사에 필요한 공개 주소)
    cfg_path = ROOT / "site" / "site_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    contact = cfg.get("contact_email") or "운영팀 문의 메일 (등록 예정)"
    for page in (ROOT / "site" / "pages").glob("*.html"):
        (out / page.name).write_text(page.read_text(encoding="utf-8").replace("CONTACT_EMAIL", contact), encoding="utf-8")
    print(f"✅ 사이트 생성: {out / 'index.html'} ({len(html.encode()) // 1024}KB)")


if __name__ == "__main__":
    main()
