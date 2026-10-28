"""캔바 Connect API (폴더·디자인 가져오기·내보내기·이동).

    from publish.canva import Canva
    cv = Canva()                                  # 저장된 refresh token 으로 로그인 (새 refresh token 은 자동 저장)
    folder = cv.ensure_folder("핫코노미 · 발행 대기")
    design = cv.import_file("card.pptx", "카드뉴스 시안", folder)
    urls = cv.export(design["id"], "jpg")         # 24시간 유효한 다운로드 주소들
호출 한도는 대부분 분당 20회라 상태 확인은 3~10초 간격으로만 한다.
"""
import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request

from publish.canva_auth import refresh_access

API = "https://api.canva.com/rest/v1"
MIME = {".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pdf": "application/pdf"}
FOLDERS = {"queue": "핫코노미 · 발행 대기", "done": "핫코노미 · 발행 완료", "failed": "핫코노미 · 발행 실패"}


class CanvaError(Exception):
    pass


class Canva:
    def __init__(self, token=None):
        self.token = token or refresh_access()

    def _call(self, method, path, body=None, headers=None, raw=None):
        h = {"Authorization": f"Bearer {self.token}", **(headers or {})}
        data = raw
        if body is not None:
            data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
        req = urllib.request.Request(f"{API}/{path}", data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                txt = r.read()
                return json.loads(txt) if txt else {}
        except urllib.error.HTTPError as e:
            raise CanvaError(f"캔바 {method} {path.split('?')[0]} 실패({e.code}): {e.read()[:300].decode('utf-8', 'ignore')}")

    def items(self, folder_id, types=None):
        out, cont = [], None
        while True:
            q = "?limit=100" + (f"&item_types={types}" if types else "") + (f"&continuation={cont}" if cont else "")
            r = self._call("GET", f"folders/{folder_id}/items{q}")
            out += r.get("items", [])
            cont = r.get("continuation")
            if not cont:
                return out

    def ensure_folder(self, name, parent="root"):
        for it in self.items(parent, "folder"):
            if (it.get("folder") or {}).get("name") == name:
                return it["folder"]["id"]
        return self._call("POST", "folders", {"name": name, "parent_folder_id": parent})["folder"]["id"]

    def ensure_folders(self):
        return {k: self.ensure_folder(v) for k, v in FOLDERS.items()}

    def _job(self, path, key="job", timeout=300):
        waited, step = 0, 3
        while waited < timeout:
            job = self._call("GET", path)[key]
            if job["status"] == "success":
                return job
            if job["status"] == "failed":
                raise CanvaError(f"캔바 작업 실패: {job.get('error')}")
            time.sleep(step)
            waited += step
            step = min(step + 2, 10)
        raise CanvaError("캔바 작업이 5분 넘게 끝나지 않아요.")

    def import_file(self, path, title, folder_id=None):
        """PPTX·PDF 등을 편집 가능한 캔바 디자인으로 가져온다 → 디자인 정보."""
        meta = {"title_base64": base64.b64encode(title[:50].encode()).decode(),
                "mime_type": MIME.get(os.path.splitext(path)[1].lower()) or mimetypes.guess_type(path)[0]}
        with open(path, "rb") as f:
            job = self._call("POST", "imports", headers={"Content-Type": "application/octet-stream",
                                                         "Import-Metadata": json.dumps(meta)}, raw=f.read())["job"]
        design = self._job(f"imports/{job['id']}")["result"]["designs"][0]
        if folder_id:
            self.move(design["id"], folder_id)
        return design

    def page_count(self, design_id):
        return self._call("GET", f"designs/{design_id}")["design"].get("page_count") or 1

    def export(self, design_id, kind="jpg"):
        """JPG 는 한 장씩 따로 내보낸다 — 여러 장을 한 번에 내보내면 앞 장 글자가 겹쳐 깨지는 경우가 있었음(2026-10-28 확인)."""
        if kind != "jpg":
            job = self._call("POST", "exports", {"design_id": design_id, "format": {"type": "mp4", "quality": "vertical_1080p"}})["job"]
            return self._job(f"exports/{job['id']}", timeout=600)["urls"]
        return [self._stable_page(design_id, p) for p in range(1, self.page_count(design_id) + 1)]

    def _export_page(self, design_id, page):
        job = self._call("POST", "exports", {"design_id": design_id, "format": {"type": "jpg", "quality": 92, "pages": [page]}})["job"]
        url = self._job(f"exports/{job['id']}")["urls"][0]
        with urllib.request.urlopen(url, timeout=120) as r:
            return url, r.read()

    def _stable_page(self, design_id, page, tries=6):
        """깨진 장(글꼴 늦게 불러와 글자 겹침)은 매번 다르게 깨지므로, 같은 장을 다시 내보내 두 번 똑같이 나온 것만 쓴다."""
        seen = []
        for _ in range(tries):
            url, data = self._export_page(design_id, page)
            if any(_same(data, d) for _, d in seen):
                return url
            seen.append((url, data))
        raise CanvaError(f"{page}장째가 계속 다르게 나와요(글자 깨짐 의심) — 캔바에서 디자인을 한 번 열어 확인해 주세요.")


def _same(a, b, limit=1.5):
    """두 JPG 가 사실상 같은 그림인지 (평균 밝기 차이)."""
    import io

    from PIL import Image, ImageChops, ImageStat
    x, y = (Image.open(io.BytesIO(v)).convert("L").resize((270, 338)) for v in (a, b))
    return ImageStat.Stat(ImageChops.difference(x, y)).mean[0] < limit

    def move(self, item_id, folder_id):
        self._call("POST", "folders/move", {"item_id": item_id, "to_folder_id": folder_id})
