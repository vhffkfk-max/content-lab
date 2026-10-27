"""인스타 발행 (공식 Graph API, 페이스북 로그인 방식 페이지 토큰 — 수집과 같은 토큰).

    from publish.instagram import Instagram
    ig = Instagram(user_id, token)
    media_id, link = ig.publish_carousel(["https://.../1.jpg", ...], caption)
    media_id, link = ig.publish_reel("https://.../video.mp4", caption)
흐름: 항목별 컨테이너 → (캐러셀이면 묶음 컨테이너) → 처리 완료(FINISHED)까지 기다림 → media_publish.
이미지는 JPEG만, 인스타 서버가 직접 받아 가므로 공개 주소여야 한다.
호출 수를 아끼려고 상태 확인은 10~20초 간격으로만 한다 (지난번 메타 계정 확인 이슈 참고).
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://graph.facebook.com/v25.0"


class PublishError(Exception):
    """사람이 읽을 수 있는 이유(reason)를 담는다 — 텔레그램 알림에 그대로 씀."""

    def __init__(self, reason, detail=""):
        super().__init__(f"{reason} {detail}".strip())
        self.reason, self.detail = reason, detail


class Instagram:
    def __init__(self, user_id, token):
        self.user_id, self.token = user_id, token

    def _call(self, method, path, params):
        data = urllib.parse.urlencode({**params, "access_token": self.token})
        url = f"{BASE}/{path}" + (f"?{data}" if method == "GET" else "")
        req = urllib.request.Request(url, data=data.encode() if method == "POST" else None, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            err = json.loads(e.read() or b"{}").get("error", {})
            msg = err.get("error_user_msg") or err.get("message", str(e))
            raise PublishError(explain(err), f"[{err.get('code')}] {msg}")

    def limit(self):
        """24시간 발행 사용량 (used, total)."""
        d = (self._call("GET", f"{self.user_id}/content_publishing_limit", {"fields": "config,quota_usage"}).get("data") or [{}])[0]
        return d.get("quota_usage", 0), (d.get("config") or {}).get("quota_total", 50)

    def _wait(self, container_id, timeout=600):
        waited, step = 0, 10
        while waited < timeout:
            st = self._call("GET", container_id, {"fields": "status_code,status"})
            code = st.get("status_code")
            if code == "FINISHED":
                return
            if code in ("ERROR", "EXPIRED"):
                raise PublishError("인스타가 파일을 처리하지 못했어요 (형식·크기·비율 확인 필요).", st.get("status", ""))
            time.sleep(step)
            waited += step
            step = min(step + 5, 30)
        raise PublishError("인스타 처리 시간이 너무 오래 걸려요 (10분 초과).")

    def _publish(self, creation_id):
        media_id = self._call("POST", f"{self.user_id}/media_publish", {"creation_id": creation_id})["id"]
        link = self._call("GET", media_id, {"fields": "permalink"}).get("permalink", "")
        return media_id, link

    def publish_carousel(self, image_urls, caption, max_items=10):
        if not 2 <= len(image_urls) <= max_items:
            raise PublishError(f"캐러셀은 2~{max_items}장이어야 해요 (지금 {len(image_urls)}장).")
        used, total = self.limit()
        if used >= total:
            raise PublishError(f"오늘 인스타 발행 한도({total}개)를 다 썼어요. 내일 다시 올라가요.")
        children = []
        for url in image_urls:
            children.append(self._call("POST", f"{self.user_id}/media", {"image_url": url, "is_carousel_item": "true"})["id"])
        for c in children:
            self._wait(c)
        parent = self._call("POST", f"{self.user_id}/media", {"media_type": "CAROUSEL", "children": ",".join(children),
                                                               "caption": caption})["id"]
        self._wait(parent)
        return self._publish(parent)

    def publish_reel(self, video_url, caption, share_to_feed=True):
        used, total = self.limit()
        if used >= total:
            raise PublishError(f"오늘 인스타 발행 한도({total}개)를 다 썼어요. 내일 다시 올라가요.")
        cid = self._call("POST", f"{self.user_id}/media", {"media_type": "REELS", "video_url": video_url, "caption": caption,
                                                            "share_to_feed": "true" if share_to_feed else "false"})["id"]
        self._wait(cid, timeout=900)
        return self._publish(cid)

    def set_comments(self, media_id, enabled):
        """댓글 켜기/끄기 (유료 서비스 연결 계정만 끔 — 핫코노미는 켜 둠)."""
        return self._call("POST", media_id, {"comment_enabled": "true" if enabled else "false"})


def explain(err):
    """메타 오류를 쉬운 말로."""
    code, sub, msg = err.get("code"), err.get("error_subcode"), (err.get("message") or "").lower()
    if code in (190, 102):
        return "인스타 토큰이 만료됐거나 끊겼어요 — python -m publish.ig_token 으로 다시 연결해 주세요."
    if code == 10 or "permission" in msg:
        return "발행 권한(instagram_content_publish)이 없어요 — python -m publish.ig_token 으로 권한을 추가해 주세요."
    if code in (4, 17, 32, 613) or "limit" in msg:
        return "메타 호출 한도에 걸렸어요 — 잠시 뒤 자동으로 다시 시도해요."
    if sub == 2207026 or "aspect ratio" in msg:
        return "이미지·영상 비율이 인스타 기준(4:5~1.91:1, 릴스 9:16)에 맞지 않아요."
    if sub in (2207052, 2207004) or "image" in msg and "format" in msg:
        return "이미지 형식이 맞지 않아요 — JPEG로 내보내 주세요."
    if "url" in msg or sub == 2207003:
        return "인스타가 파일 주소를 열지 못했어요 (공개 주소가 아니거나 만료됨)."
    return "인스타 발행 중 오류가 났어요."
