"""릴스 묶음 → 캡컷 프로젝트(타임라인에 장면·음성·배경음·자막이 놓인 상태).

캡컷 공식 기능이 아니다. CapCut 9.5.0.4050 의 프로젝트 파일 구조를 보고 맞춘 것이라 업데이트하면 안 될 수 있다.
안 되면 캡컷용 폴더의 파일을 직접 가져오면 된다 (안내.txt).

- 새 폴더만 만들고 기존 프로젝트는 건드리지 않는다. 목록 파일은 고치기 전에 복사본을 남긴다.
- 캡컷이 켜져 있으면 목록 파일을 덮어쓸 수 있어 멈춘다.
- 영상은 원본 경로를 가리킨다. 결과 폴더를 지우거나 옮기면 캡컷에서 파일을 다시 연결해야 한다.
"""
import copy
import json
import os
import pathlib
import re
import shutil
import subprocess
import time
import uuid

TEMPLATE = pathlib.Path(__file__).parent / "capcut_template"
ROOT = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
US = 1_000_000


def new_id():
    return str(uuid.uuid4()).upper()


def probe_us(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout
    return int(round(float(out) * US))


def parse_srt(text):
    rows = []
    for m in re.finditer(r"(\d\d):(\d\d):(\d\d),(\d{3}) --> (\d\d):(\d\d):(\d\d),(\d{3})\n(.+?)(?:\n\n|\n?$)", text.lstrip("﻿"), re.S):
        g = m.groups()
        t = lambda h, mi, s, ms: (int(h) * 3600 + int(mi) * 60 + int(s)) * US + int(ms) * 1000
        rows.append({"start": t(*g[:4]), "end": t(*g[4:8]), "text": g[8].strip()})
    return rows


def _refs(mats, tpl, kinds):
    """구간에 딸린 부속 재료(속도 등)를 새 번호로 복제한다."""
    out = []
    for k in kinds:
        x = copy.deepcopy(tpl["materials"][k][0])
        x["id"] = new_id()
        mats[k].append(x)
        out.append(x["id"])
    return out


def _segment(tpl_seg, material_id, start, dur, refs, render_index=0):
    s = copy.deepcopy(tpl_seg)
    s.update(id=new_id(), material_id=material_id, extra_material_refs=refs, render_index=render_index, track_render_index=0,
             source_timerange={"start": 0, "duration": dur}, target_timerange={"start": start, "duration": dur})
    return s


def _text_material(text, dark=True):
    rgb, hexc = ([1.0, 1.0, 1.0], "#FFFFFF") if dark else ([0.07, 0.07, 0.07], "#111111")
    style = {"fill": {"alpha": 1.0, "content": {"render_type": "solid", "solid": {"alpha": 1.0, "color": rgb}}}, "range": [0, len(text)], "size": 9.0, "bold": True,
             "italic": False, "underline": False, "strokes": [], "font": {"id": "", "path": ""}}
    return {"id": new_id(), "type": "subtitle", "content": json.dumps({"text": text, "styles": [style]}, ensure_ascii=False), "alignment": 1, "font_size": 9.0, "text_color": hexc,
            "text_alpha": 1.0, "typesetting": 0, "letter_spacing": 0.0, "line_spacing": 0.02, "line_max_width": 0.82, "fixed_width": -1.0, "fixed_height": -1.0, "global_alpha": 1.0,
            "background_alpha": 0.85, "background_color": "#111111", "background_style": 1, "background_round_radius": 0.2, "background_height": 0.14, "background_width": 0.14,
            "background_horizontal_offset": 0.0, "background_vertical_offset": 0.0, "use_effect_default_color": False, "shape_clip_x": False, "shape_clip_y": False,
            "layer_weight": 1, "check_flag": 15, "words": {"start_time": [], "end_time": [], "text": []}, "recognize_type": 0, "font_name": "", "font_path": "", "font_id": ""}


def _audio_material(path, dur):
    return {"id": new_id(), "type": "extract_music", "name": path.name, "path": path.as_posix(), "duration": dur, "category_name": "local", "category_id": "", "check_flag": 1,
            "local_material_id": "", "music_id": new_id(), "source_platform": 0, "team_id": "", "text_id": "", "tone_type": "", "video_id": "", "wave_points": [], "effect_id": "",
            "formula_id": "", "intensifies_path": "", "resource_id": "", "source_from": "", "third_resource_id": "", "tone_category_id": "", "tone_category_name": "", "tone_effect_id": "",
            "tone_effect_name": "", "tone_platform": "", "tone_second_category_id": "", "tone_second_category_name": "", "tone_speaker": "", "tone_style": ""}


def build_content(tpl, clips, voice, music, captions, dark_scenes=(), caption_y=-0.33):
    """clips=[(경로, 길이us)], voice·music=(경로, 길이us), captions=parse_srt 결과 → draft_content
    dark_scenes: 배경이 검은 장면 번호(0부터). 그 장면 자막은 흰 글씨, 나머지(모눈종이)는 검은 글씨
    (캡컷이 자막 바탕 칸을 적용하지 않아 흰 글씨가 밝은 배경에서 안 보였음, 2026-11-06 확인)"""
    d = copy.deepcopy(tpl)
    vt = d["tracks"][0]
    tpl_seg, tpl_vid = vt["segments"][0], d["materials"]["videos"][0]
    mats = d["materials"]
    for k in mats:
        mats[k] = []
    d["id"] = new_id()
    d["canvas_config"].update(ratio="original", width=1080, height=1920)

    # 영상 줄: 장면마다 구간 하나
    segs, t, bounds = [], 0, []
    for p, dur in clips:
        bounds.append((t, t + dur))
        v = copy.deepcopy(tpl_vid)
        v.update(id=new_id(), path=pathlib.Path(p).as_posix(), material_name=pathlib.Path(p).name, duration=dur, width=1080, height=1920, has_audio=False)
        mats["videos"].append(v)
        segs.append(_segment(tpl_seg, v["id"], t, dur, _refs(mats, tpl, ["speeds", "placeholder_infos", "canvases", "sound_channel_mappings", "material_colors", "vocal_separations"])))
        t += dur
    total = t
    tracks = [{**{k: v for k, v in vt.items() if k != "segments"}, "id": new_id(), "segments": segs}]

    # 소리 줄: 음성, 배경음
    audio_seg = {**copy.deepcopy(tpl_seg), "clip": None, "uniform_scale": None, "hdr_settings": None, "enable_lut": False, "enable_adjust": False, "enable_color_curves": False,
                 "enable_hsl_curves": False, "enable_color_wheels": False, "enable_video_mask": False}
    for n, (p, dur) in enumerate((voice, music)):
        m = _audio_material(pathlib.Path(p), dur)
        mats["audios"].append(m)
        seg = _segment(audio_seg, m["id"], 0, min(dur, total), _refs(mats, tpl, ["speeds", "placeholder_infos", "sound_channel_mappings", "vocal_separations"]))
        tracks.append({"id": new_id(), "type": "audio", "flag": 0, "attribute": 0, "name": "", "is_default_name": True, "segments": [seg]})

    # 자막 줄: 고칠 수 있는 글자
    text_segs = []
    for c in captions:
        mid = (c["start"] + c["end"]) // 2
        scene = next((i for i, (a, b) in enumerate(bounds) if a <= mid < b), len(bounds) - 1)
        m = _text_material(c["text"], dark=scene in dark_scenes)
        mats["texts"].append(m)
        s = _segment(tpl_seg, m["id"], c["start"], max(1, c["end"] - c["start"]), [], render_index=14000)
        s["clip"]["transform"] = {"x": 0.0, "y": caption_y}
        s.update(enable_lut=False, enable_adjust=False, enable_color_curves=False, enable_hsl_curves=False, enable_color_wheels=False, enable_video_mask=False, hdr_settings=None)
        text_segs.append(s)
    tracks.append({"id": new_id(), "type": "text", "flag": 0, "attribute": 0, "name": "", "is_default_name": True, "segments": text_segs})
    d["tracks"], d["duration"] = tracks, total
    return d


CTL = pathlib.Path(__file__).with_name("capcut_ctl.ps1")


def ctl(*args):
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(CTL), *args], capture_output=True, text=True, encoding="cp949", errors="replace", timeout=120)   # 윈도 파워셸 출력은 cp949
    return r.returncode == 0, (r.stdout or r.stderr).strip()


def is_running():
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CapCut.exe", "/NH"], capture_output=True, text=True, errors="replace")
    return "capcut.exe" in r.stdout.lower()


def _unique_folder(root, name):
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)[:60]
    f, n = root / name, 2
    while f.exists():
        f, n = root / f"{name}_{n}", n + 1
    return f


def install(pack, name, root=None, cover=None, check_running=True, dark_scenes=(), caption_y=-0.33):
    """캡컷용 폴더 → 새 프로젝트. 만든 폴더 경로를 돌려준다."""
    root = pathlib.Path(root or ROOT)
    pack = pathlib.Path(pack).resolve()
    if check_running and is_running():
        raise SystemExit("캡컷이 켜져 있어요. 캡컷을 닫은 뒤 다시 실행해 주세요 (켜 둔 채 목록을 고치면 덮어써질 수 있어요).")
    if not (root / "root_meta_info.json").exists():
        raise SystemExit(f"캡컷 프로젝트 폴더를 찾지 못했어요: {root}")
    tpl = json.loads((TEMPLATE / "draft_content.json").read_text(encoding="utf-8"))
    meta = json.loads((TEMPLATE / "draft_meta_info.json").read_text(encoding="utf-8"))
    clips = [(p, probe_us(p)) for p in sorted((pack / "장면영상").glob("*.mp4"))]
    voice, music = pack / "음성만.m4a", pack / "배경음.m4a"
    captions = parse_srt((pack / "자막.srt").read_text(encoding="utf-8-sig"))
    d = build_content(tpl, clips, (voice, probe_us(voice)), (music, probe_us(music)), captions, dark_scenes, caption_y)
    folder = _unique_folder(root, name)
    folder.mkdir()
    for f in TEMPLATE.iterdir():
        if f.name not in ("draft_content.json", "draft_meta_info.json"):
            shutil.copy2(f, folder / f.name)
    now_s, now_us = int(time.time()), int(time.time() * US)
    text = json.dumps(d, ensure_ascii=False)
    (folder / "draft_content.json").write_text(text, encoding="utf-8")
    (folder / "timeline_layout.json").write_text(json.dumps({"dockItems": [{"dockIndex": 0, "ratio": 1, "timelineIds": [d["id"]], "timelineNames": ["타임라인 01"]}], "layoutOrientation": 1}, ensure_ascii=False), encoding="utf-8")
    (folder / "draft_settings").write_text(f"[General]\ndraft_create_time={now_s}\ndraft_last_edit_time={now_s}\nreal_edit_seconds=0\nreal_edit_keys=0\n", encoding="utf-8")
    (folder / "key_value.json").write_text("{}", encoding="utf-8")
    if cover and pathlib.Path(cover).exists():
        shutil.copy2(cover, folder / "draft_cover.jpg")

    # 미디어 칸에 보일 재료 목록
    items, vs = [], []
    def add(p, kind, dur, w=0, h=0):
        i = str(uuid.uuid4())
        items.append({"ai_group_type": "", "create_time": now_s, "duration": dur, "enter_from": 0, "extra_info": pathlib.Path(p).name, "file_Path": pathlib.Path(p).as_posix(), "height": h, "id": i, "import_time": now_s,
                      "import_time_ms": now_us, "item_source": 1, "material_color_tag": "", "md5": "", "metetype": kind, "roughcut_time_range": {"duration": dur, "start": 0}, "sub_time_range": {"duration": -1, "start": -1}, "type": 0, "width": w})
        vs.append({"child_id": i, "parent_id": ""})
    for p, dur in clips:
        add(p, "video", dur, 1080, 1920)
    add(voice, "music", probe_us(voice))
    add(music, "music", probe_us(music))
    for p in sorted((pack / "차트").glob("*")):
        add(p, "photo", 5 * US)
    did = new_id()
    meta.update(draft_id=did, draft_name=folder.name, draft_fold_path=folder.as_posix(), draft_root_path=str(root), draft_cover="draft_cover.jpg", tm_duration=d["duration"], tm_draft_create=now_us, tm_draft_modified=now_us, draft_is_from_deeplink="false")
    for g in meta["draft_materials"]:
        g["value"] = items if g["type"] == 0 else []
    (folder / "draft_meta_info.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    store = json.loads((TEMPLATE / "draft_virtual_store.json").read_text(encoding="utf-8"))
    for g in store["draft_virtual_store"]:
        if g["type"] == 1:
            g["value"] = vs
    (folder / "draft_virtual_store.json").write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")

    # 프로젝트 목록에 추가 (고치기 전에 복사본)
    rp = root / "root_meta_info.json"
    shutil.copy2(rp, root / f"root_meta_info.백업_{now_s}.json")
    r = json.loads(rp.read_text(encoding="utf-8"))
    base = copy.deepcopy(r["all_draft_store"][0]) if r.get("all_draft_store") else {}
    base.update(draft_id=did, draft_name=folder.name, draft_fold_path=folder.as_posix(), draft_root_path=str(root), draft_cover=(folder / "draft_cover.jpg").as_posix(), draft_json_file=(folder / "draft_content.json").as_posix(),
                tm_draft_create=now_us, tm_draft_modified=now_us, tm_duration=d["duration"], tm_draft_removed=0, draft_timeline_materials_size=sum(os.path.getsize(p) for p, _ in clips))
    r["all_draft_store"].insert(0, base)
    if isinstance(r.get("draft_ids"), int):
        r["draft_ids"] += 1
    rp.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    return folder, {"scenes": len(clips), "captions": len(captions), "seconds": round(d["duration"] / US, 1)}
