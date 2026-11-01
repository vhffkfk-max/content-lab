"""카드뉴스 학습 — (1) 대표가 캔바에서 고친 것 (2) 발행 뒤 48시간 성적. 다음 초안(draft_card)에 바로 반영된다.

    python -m publish.card_learn            # 둘 다 (PC local_ai.py 가 08~23시 1시간마다)
    python -m publish.card_learn --edits    # 캔바 수정만
    python -m publish.card_learn --perf     # 성적만
    python -m publish.card_learn --show     # 지금까지 배운 것

(1) 캔바 '발행 대기'의 초안 사본이 만든 뒤 고쳐졌고 30분 넘게 그대로면 PPTX 로 내보내 처음 사본과 글상자별로 비교한다
    → 바뀐 글, 지운 장, 글자 크기, 색, 위치 → Sonnet(Max)이 '대표 수정 습관' 규칙(최대 12개)과 폼별 메모로 정리 → data/card_style.json
    규칙은 다음 초안 프롬프트에 들어가고, 같은 폼에서 같은 색 바꾸기가 2번 나오면 그 폼의 색을 아예 바꾼다(forms.make → restyle).
(2) @hotconomy 게시물(Graph API)을 큐 캡션과 맞춰 찾고, 올린 지 48시간이 지나면 도달·저장·공유·댓글을 큐 perf 에 적는다
    → 폼별 점수 data/form_stats.json → 초안 프롬프트에 [폼 성적], 3번 넘게 써 본 폼 중 점수가 1등의 절반도 안 되는 폼은 후보에서 뺀다.
점수 = (저장 + 공유×2 + 댓글) ÷ 도달 × 100. 경제 카드뉴스는 저장이 가장 중요한 숫자라서.
"""
import argparse
import difflib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from common import ROOT, load_env

KST = timezone(timedelta(hours=9))
QUEUE = ROOT / "data" / "publish_queue.json"
STYLE = ROOT / "data" / "card_style.json"
STATS = ROOT / "data" / "form_stats.json"
DRAFTS = ROOT / "output" / "cardnews" / "drafts"
MODEL = "claude-sonnet-5-5"
SETTLE = 30 * 60          # 마지막으로 고친 뒤 이만큼 그대로면 다 고친 걸로 본다
LOOKBACK = 21             # 며칠 지난 초안까지 캔바를 들여다볼지
FINAL_HOURS = 48          # 성적은 올린 지 48시간 숫자로 비교
MIN_TRIES = 3             # 이만큼 써 본 폼만 성적으로 거른다
SWAP_TIMES = 2            # 같은 색 바꾸기가 이만큼 나오면 폼 색을 바꾼다
W = 1080


def now():
    return datetime.now(KST)


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def norm(s):
    return re.sub(r"\s+", "", s or "")


def short(s, n=40):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[:n - 1] + "…"


# ── 초안에서 쓰는 것 (draft_card · forms) ──
def style():
    return load(STYLE, {"rules": [], "forms": {}, "history": []})


def restyle(form, css, slides):
    """같은 폼에서 2번 넘게 나온 색 바꾸기를 CSS·슬라이드 HTML 에 그대로 적용."""
    swaps = {k: v for k, v in (style()["forms"].get(form, {}).get("swaps") or {}).items() if v >= SWAP_TIMES}
    for key in swaps:
        old, new = key.split(">")
        pat = re.compile(re.escape(old), re.I)
        css = pat.sub(new, css)
        slides = [pat.sub(new, s) for s in slides]
    return css, slides


def prompt_notes(allowed):
    """초안 프롬프트에 붙일 [대표 수정 습관]·[폼 성적]."""
    st, out = style(), []
    lines = [f"- {r}" for r in st.get("rules", [])]
    lines += [f"- ({k}) {n}" for k in allowed for n in (st["forms"].get(k, {}).get("notes") or [])]
    if lines:
        out.append("[대표 수정 습관] (대표가 캔바에서 직접 고친 걸 정리한 것, 꼭 따를 것)\n" + "\n".join(lines))
    fs = load(STATS, {}).get("forms", {})
    if fs:
        rows = sorted(fs.items(), key=lambda kv: -kv[1]["score"])
        out.append("[폼 성적] (올린 지 48시간, 점수=(저장+공유×2+댓글)/도달×100. 3번 미만은 아직 시험 중)\n" + "\n".join(
            f"- {k}: {v['n']}번, 점수 {v['score']}, 평균 도달 {v['reach']:,}, 저장률 {v['save_rate']}%" for k, v in rows)
            + "\n소재에 맞는 폼이 여럿이면 점수가 높은 폼, 또는 아직 3번이 안 된 폼을 먼저 고르세요.")
    return "\n\n".join(out)


def prune(allowed):
    """3번 넘게 써 본 폼 중 점수가 1등의 절반도 안 되는 폼은 뺀다 (다 빠지면 그대로)."""
    fs = load(STATS, {}).get("forms", {})
    tried = {k: v["score"] for k, v in fs.items() if v["n"] >= MIN_TRIES}
    if len(tried) < 2:
        return allowed
    best = max(tried.values())
    kept = [k for k in allowed if k not in tried or tried[k] >= best / 2]
    return kept or allowed


# ── (1) 캔바 수정 ──
def boxes(path):
    """PPTX → 장마다 글상자 [{text, x, y, size, colors}] 와 그림 수. 위치는 1080 기준 px."""
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    prs = Presentation(str(path))
    k = W / prs.slide_width
    pages = []
    for slide in prs.slides:
        page = {"boxes": [], "pics": 0}

        def walk(shapes):
            for sh in shapes:
                if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
                    walk(sh.shapes)
                    continue
                if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    page["pics"] += 1
                if not getattr(sh, "has_text_frame", False) or not sh.text_frame.text.strip():
                    continue
                runs = [r for p in sh.text_frame.paragraphs for r in p.runs if r.text.strip()]
                sizes = [r.font.size.pt for r in runs if r.font.size]
                colors = set()
                for r in runs:
                    try:
                        colors.add("#" + str(r.font.color.rgb).upper())
                    except (AttributeError, TypeError):
                        pass
                page["boxes"].append({"text": " ".join(sh.text_frame.text.split()), "x": round((sh.left or 0) * k),
                                      "y": round((sh.top or 0) * k), "size": max(sizes) if sizes else None, "colors": sorted(colors)})

        walk(slide.shapes)
        page["boxes"].sort(key=lambda b: (b["y"], b["x"]))
        pages.append(page)
    return pages


def _sim(a, b):
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def _pair(olds, news, score, cut):
    """두 목록을 점수 높은 순으로 짝짓기 → [(i, j)], 짝 없는 쪽은 빠짐."""
    cand = sorted(((score(o, n), i, j) for i, o in enumerate(olds) for j, n in enumerate(news)), reverse=True)
    used_i, used_j, out = set(), set(), []
    for s, i, j in cand:
        if s >= cut and i not in used_i and j not in used_j:
            used_i.add(i)
            used_j.add(j)
            out.append((i, j))
    return sorted(out)


def diff(orig, edit):
    """처음 사본과 고친 사본 비교 → (사람이 읽는 변경 목록, 색 바꾸기 [(old, new)])."""
    text = lambda p: " ".join(b["text"] for b in p["boxes"])
    pages = _pair(orig, edit, lambda a, b: _sim(text(a), text(b)), 0.25)
    if len(orig) == len(edit):                      # 장 수가 같으면 순서대로 (글을 다 갈아엎어도 같은 장)
        pages = [(i, i) for i in range(len(orig))]
    changes, swaps = [], []
    for i in sorted(set(range(len(orig))) - {i for i, _ in pages}):
        changes.append(f"{i + 1}장 통째로 지움 ('{short(text(orig[i]))}')")
    for j in sorted(set(range(len(edit))) - {j for _, j in pages}):
        changes.append(f"새 장 추가 (고친 뒤 {j + 1}장째, '{short(text(edit[j]))}')")
    for i, j in pages:
        o, e = orig[i]["boxes"], edit[j]["boxes"]
        tag = f"{i + 1}장"
        added = edit[j]["pics"] - max(orig[i]["pics"] - 1, 0)   # 처음 사본의 배경 그림은 캔바가 '배경'으로 내보내서 그림 수에 안 잡힘
        if added > 0:
            changes.append(f"{tag} 그림 {added}개 추가")
        near = lambda a, b: max(_sim(a["text"], b["text"]), 0.5 if abs(a["x"] - b["x"]) + abs(a["y"] - b["y"]) < 40 else 0)
        pairs = _pair(o, e, near, 0.35)
        for a in sorted(set(range(len(o))) - {a for a, _ in pairs}):
            changes.append(f"{tag} 글 지움: '{short(o[a]['text'])}'")
        for b in sorted(set(range(len(e))) - {b for _, b in pairs}):
            changes.append(f"{tag} 글 추가: '{short(e[b]['text'], 80)}'")
        for a, b in pairs:
            x, y = o[a], e[b]
            if norm(x["text"]) != norm(y["text"]):
                changes.append(f"{tag} 글 고침: '{short(x['text'], 80)}' → '{short(y['text'], 80)}'")
            if x["size"] and y["size"] and abs(y["size"] / x["size"] - 1) > 0.08:
                changes.append(f"{tag} 글자 크기 {x['size']:.0f}→{y['size']:.0f}pt ({(y['size'] / x['size'] - 1) * 100:+.0f}%): '{short(y['text'], 24)}'")
            gone, came = set(x["colors"]) - set(y["colors"]), set(y["colors"]) - set(x["colors"])
            if gone and came:
                changes.append(f"{tag} 색 {', '.join(sorted(gone))} → {', '.join(sorted(came))}: '{short(y['text'], 24)}'")
                if len(gone) == 1 and len(came) == 1:
                    swaps.append((gone.pop(), came.pop()))
            dx, dy = y["x"] - x["x"], y["y"] - x["y"]
            if abs(dx) > 40 or abs(dy) > 40:
                way = "아래" if dy > 40 else "위" if dy < -40 else ""
                side = "오른쪽" if dx > 40 else "왼쪽" if dx < -40 else ""
                changes.append(f"{tag} 위치 {' '.join(w for w in (way, side) if w)}로 이동({dx:+}, {dy:+}px): '{short(y['text'], 24)}'")
    return changes, swaps


def summarize(item, changes, st):
    """변경 목록 → 갱신된 규칙(최대 12개)·이 폼 메모·한 줄 요약 (Sonnet, Max 구독)."""
    from pydantic import BaseModel

    import llm as anthropic

    class Out(BaseModel):
        rules: list[str]
        form_notes: list[str]
        summary: str

    system = ("당신은 경제 인스타 @hotconomy 카드뉴스 초안을 쓰는 AI의 편집장입니다. 대표가 AI 초안을 캔바에서 직접 고친 내역을 보고, "
              "다음 초안부터 처음부터 그렇게 쓰도록 '대표 수정 습관' 규칙을 다듬습니다.\n"
              "- rules: 모든 폼에 해당하는 글쓰기 규칙. 기존 규칙을 유지·합치·고쳐서 최대 12개. 한 줄씩, 구체적으로(예: '표지 제목은 12자 안쪽', "
              "'숫자는 소수점 첫째 자리까지', '“~라는 보도” 대신 매체 이름'). 이번 한 번만의 사실 수정(오타, 숫자 정정)은 규칙으로 만들지 않습니다.\n"
              "- form_notes: 이 폼에만 해당하는 디자인·구성 메모(기존 메모 포함 최대 5개). 글자 크기·색·위치·장 수처럼 화면에 관한 것.\n"
              "- summary: 이번에 무엇을 배웠는지 한 줄(대표에게 텔레그램으로 보냄).\n"
              "가운뎃점(·) 대신 쉼표를 씁니다.")
    form = item["form"]
    prompt = (f"폼: {form}\n주제: {item.get('topic')}\n제목: {item.get('title')}\n\n[기존 규칙]\n"
              + ("\n".join(f"- {r}" for r in st["rules"]) or "- (없음)")
              + "\n\n[이 폼 기존 메모]\n" + ("\n".join(f"- {n}" for n in st["forms"].get(form, {}).get("notes", [])) or "- (없음)")
              + "\n\n[이번에 대표가 고친 것]\n" + "\n".join(f"- {c}" for c in changes[:80]))
    r = anthropic.Anthropic().messages.parse(model=MODEL, max_tokens=4000, system=system, output_config={"effort": "low"},
                                             messages=[{"role": "user", "content": prompt}], output_format=Out)
    o = r.parsed_output
    return [s.strip() for s in o.rules if s.strip()][:12], [s.strip() for s in o.form_notes if s.strip()][:5], o.summary.strip()


def learn_edits(queue, send=True):
    from publish import notify
    since = now() - timedelta(days=LOOKBACK)
    todo = [i for i in queue["items"] if (i.get("canva") or {}).get("id")
            and datetime.fromisoformat(i["created_at"]) >= since]
    if not todo:
        print("캔바 사본이 있는 최근 초안이 없어요.")
        return False
    from publish.canva import Canva, CanvaError
    cv, st, changed = Canva(), style(), False
    for item in todo:
        c = item["canva"]
        try:
            d = cv._call("GET", f"designs/{c['id']}")["design"]
        except CanvaError as e:
            print("⚠️", item["id"], e)
            continue
        upd = d.get("updated_at") or 0
        if upd - (d.get("created_at") or upd) < 120 or upd <= c.get("learned_at", 0) or time.time() - upd < SETTLE:
            continue                                   # 안 고쳤거나, 이미 배웠거나, 아직 고치는 중
        orig = DRAFTS / item["id"] / f"{item['id']}.pptx"
        if not orig.exists():
            print("⚠️ 처음 사본 PPTX 가 없어 비교 못 함:", orig)
            c["learned_at"] = upd
            changed = True
            continue
        edited = DRAFTS / item["id"] / f"{item['id']}-canva-{upd}.pptx"
        try:
            job = cv._call("POST", "exports", {"design_id": c["id"], "format": {"type": "pptx"}})["job"]
            url = cv._job(f"exports/{job['id']}")["urls"][0]
            edited.write_bytes(urllib.request.urlopen(url, timeout=180).read())
        except (CanvaError, OSError) as e:
            print("⚠️ 캔바 내보내기 실패:", item["id"], e)
            continue
        changes, swaps = diff(boxes(orig), boxes(edited))
        c["learned_at"] = upd
        changed = True
        if not changes:
            print(f"· {item['id']}: 고친 시각은 바뀌었지만 글·색·위치 변화 없음")
            continue
        print(f"✏️ {item['id']} 고친 것 {len(changes)}가지:\n  " + "\n  ".join(changes[:30]))
        f = st["forms"].setdefault(item["form"], {})
        for old, new in swaps:
            key = f"{old}>{new}"
            f.setdefault("swaps", {})[key] = f.get("swaps", {}).get(key, 0) + 1
        try:
            st["rules"], f["notes"], summary = summarize(item, changes, st)
        except Exception as e:                        # Claude 가 안 되면 변경 목록만 쌓아 두고 다음에 다시 정리
            print("⚠️ 규칙 정리 실패 (변경 목록은 저장):", e)
            summary = ""
        st["history"] = (st.get("history", []) + [{"id": item["id"], "form": item["form"], "at": now().isoformat(timespec="seconds"),
                                                    "changes": changes[:40], "summary": summary}])[-30:]
        save(STYLE, st)
        applied = [k for k, v in f.get("swaps", {}).items() if v >= SWAP_TIMES]
        if send:
            msg = f"🧠 캔바 수정 배웠어요: {item.get('title', item['topic'])}\n{summary or f'고친 것 {len(changes)}가지 저장'}"
            msg += f"\n지금 규칙 {len(st['rules'])}개 → 다음 초안부터 적용"
            if applied:
                msg += f"\n🎨 {item['form']} 폼 색 바꿈: " + ", ".join(k.replace('>', '→') for k in applied)
            notify.send(msg)
    return changed


# ── (2) 성적 ──
METRIC_SETS = ["reach,saved,shares,views,total_interactions", "reach,saved,shares,total_interactions", "reach,saved"]


def graph(path, params):
    base = f"https://graph.facebook.com/{os.environ.get('GRAPH_API_VERSION', 'v25.0')}"
    url = f"{base}/{path}?" + urllib.parse.urlencode({**params, "access_token": os.environ["IG_ACCESS_TOKEN"]})
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": json.loads(e.read() or b"{}").get("error", {})}
    except (TimeoutError, urllib.error.URLError) as e:
        return {"error": {"message": str(e)}}


def match(media, items):
    """게시물 ↔ 초안: 발행 기록의 media_id, 아니면 캡션 앞부분이 비슷하고 초안보다 나중에 올린 것."""
    out, taken = {}, set()
    for it in items:
        mid = ((it.get("published") or {}).get("instagram") or {}).get("media_id") or (it.get("perf") or {}).get("media_id")
        if mid:
            out[it["id"]] = mid
            taken.add(mid)
    cand = []
    for it in items:
        if it["id"] in out:
            continue
        made = datetime.fromisoformat(it["created_at"]) - timedelta(hours=1)
        for m in media:
            if m["id"] in taken or datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00")) < made:
                continue
            s = _sim((m.get("caption") or "")[:200], it.get("caption", "")[:200])
            if s >= 0.45:
                cand.append((s, it["id"], m["id"]))
    for s, iid, mid in sorted(cand, reverse=True):
        if iid not in out and mid not in taken:
            out[iid] = mid
            taken.add(mid)
    return out


def learn_perf(queue, send=True):
    from publish import notify
    if not os.environ.get("IG_ACCESS_TOKEN") or not os.environ.get("IG_USER_ID"):
        print("IG_ACCESS_TOKEN/IG_USER_ID 가 없어 성적을 못 봐요.")
        return False
    res = graph(f"{os.environ['IG_USER_ID']}/media", {"fields": "id,caption,timestamp,permalink,media_type,like_count,comments_count", "limit": 50})
    if "error" in res:
        print("⚠️ 내 게시물 목록 실패:", res["error"].get("message"))
        return False
    media = {m["id"]: m for m in res.get("data", [])}
    items = [i for i in queue["items"] if not (i.get("perf") or {}).get("final")]
    found, changed = match(list(media.values()), items), False
    for it in items:
        mid = found.get(it["id"])
        if not mid or mid not in media:
            continue
        m = media[mid]
        posted = datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00"))
        hours = round((datetime.now(timezone.utc) - posted).total_seconds() / 3600, 1)
        vals = {}
        for metrics in METRIC_SETS:
            r = graph(f"{mid}/insights", {"metric": metrics})
            if "error" not in r:
                vals = {d["name"]: (d.get("values") or [{}])[0].get("value", (d.get("total_value") or {}).get("value")) for d in r.get("data", [])}
                break
        final = hours >= FINAL_HOURS
        it["perf"] = {"media_id": mid, "permalink": m.get("permalink"), "posted_at": posted.astimezone(KST).isoformat(timespec="minutes"),
                      "hours": hours, "reach": vals.get("reach"), "saved": vals.get("saved"), "shares": vals.get("shares"),
                      "views": vals.get("views"), "likes": m.get("like_count"), "comments": m.get("comments_count"),
                      "checked_at": now().isoformat(timespec="minutes"), "final": final}
        changed = True
        print(f"📊 {it['id']} ({it['form']}) {hours}시간: 도달 {vals.get('reach')} 저장 {vals.get('saved')} 공유 {vals.get('shares')}")
        if final:
            stats = write_stats(queue)
            f = stats["forms"].get(it["form"], {})
            if send:
                notify.send(f"📊 48시간 성적: {it.get('title', it['topic'])}\n폼 {it['form']} · 도달 {vals.get('reach')} · 저장 {vals.get('saved')} · "
                            f"공유 {vals.get('shares')} · 댓글 {m.get('comments_count')}\n점수 {score(it['perf'])} (이 폼 평균 {f.get('score')}, {f.get('n')}번)\n{m.get('permalink', '')}")
    write_stats(queue)
    return changed


def score(p):
    reach = p.get("reach") or 0
    return round(((p.get("saved") or 0) + 2 * (p.get("shares") or 0) + (p.get("comments") or 0)) / reach * 100, 2) if reach else 0.0


def write_stats(queue):
    done = [i for i in queue["items"] if (i.get("perf") or {}).get("final") and i.get("form")]
    forms = {}
    for i in done:
        forms.setdefault(i["form"], []).append(i["perf"])
    avg = lambda xs: round(sum(xs) / len(xs), 2) if xs else 0
    stats = {"updated_at": now().isoformat(timespec="minutes"),
             "forms": {k: {"n": len(ps), "score": avg([score(p) for p in ps]), "reach": round(avg([p.get("reach") or 0 for p in ps])),
                           "save_rate": avg([(p.get("saved") or 0) / p["reach"] * 100 for p in ps if p.get("reach")])} for k, ps in forms.items()},
             "posts": [{"id": i["id"], "form": i["form"], "topic": i.get("topic"), "score": score(i["perf"]), **{k: i["perf"].get(k) for k in
                        ("reach", "saved", "shares", "comments", "permalink")}} for i in done][-60:]}
    save(STATS, stats)
    return stats


def show():
    st, fs = style(), load(STATS, {})
    print("[대표 수정 습관]\n" + ("\n".join(f"- {r}" for r in st["rules"]) or "- (아직 없음)"))
    for k, f in st["forms"].items():
        print(f"[{k}] 메모 {f.get('notes', [])} 색 바꾸기 {f.get('swaps', {})}")
    print("[폼 성적]")
    for k, v in sorted(fs.get("forms", {}).items(), key=lambda kv: -kv[1]["score"]):
        print(f"- {k}: {v}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--edits", action="store_true")
    ap.add_argument("--perf", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--no-send", action="store_true")
    a = ap.parse_args()
    load_env()
    if a.show:
        return show()
    both = not (a.edits or a.perf)
    queue = load(QUEUE, {"items": []})
    changed = False
    if a.edits or both:
        changed |= learn_edits(queue, not a.no_send)
    if a.perf or both:
        changed |= learn_perf(queue, not a.no_send)
    if changed:
        save(QUEUE, queue)


if __name__ == "__main__":
    sys.exit(main())
