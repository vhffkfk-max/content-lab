"""말희아빠 블로그·오뉴월드 인스타 새 글 팝업 — '확인했어요'를 누르기 전까지 맨 위에 떠서 1분마다 소리 내고 다시 올라온다.

    malhee_watch.py 가 새 글을 찾으면 띄움 (이미 떠 있으면 새 창을 안 만듦). 확인 안 한 글이 남아 있으면 PC를 다시 켜도 다시 뜸.
    python malhee_popup.py <폴더>     # 시험: 다른 폴더의 목록으로 띄움

- 읽기: ~/.content-lab-ai/malhee_pending.json (malhee_watch.py 만 씀)
- 쓰기: ~/.content-lab-ai/malhee_confirmed.json (이 창만 씀) — 두 프로그램이 같은 파일을 고치다 부딪히지 않게 나눔
- 닫기(X)로는 안 꺼짐. 회의 중이면 '10분 뒤 다시'. 밤 12시~아침 7시는 소리만 끔
"""
import ctypes
import json
import os
import socket
import sys
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path

try:
    import winsound
except ImportError:
    winsound = None

HOME = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / ".content-lab-ai"
PENDING, CONFIRMED = HOME / "malhee_pending.json", HOME / "malhee_confirmed.json"
PORT = 47831                # 창을 하나만 띄우는 표시
NAG_S, SNOOZE_S = 60, 10 * 60
WRITING, WRITING_MAX_S = "쓰는 중", 20 * 60   # 글을 쓰는 동안은 확인을 막되, 멈춘 듯하면 풀어 줌
FONT = "Malgun Gothic"
ACCENT, INK, MUTED, BG, BOX = "#b8336a", "#1f1f24", "#6b6b76", "#ffffff", "#f4f2f4"


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


class App:
    def __init__(self):
        self.key = None
        self.root = tk.Tk()
        r = self.root
        r.title("새 글이 올라왔어요")
        r.configure(bg=BG)
        r.geometry(f"560x640+{max(0, r.winfo_screenwidth() - 600)}+40")
        r.attributes("-topmost", True)
        r.protocol("WM_DELETE_WINDOW", self.nag)   # X 로는 안 꺼짐
        self.count = tk.Label(r, bg=ACCENT, fg="white", font=(FONT, 11, "bold"), anchor="w", padx=16, pady=10)
        self.count.pack(fill="x")
        self.title = tk.Label(r, bg=BG, fg=INK, font=(FONT, 14, "bold"), anchor="w", justify="left", wraplength=520, padx=16, pady=8)
        self.title.pack(fill="x")
        self.meta = tk.Label(r, bg=BG, fg=MUTED, font=(FONT, 10), anchor="w", justify="left", wraplength=520, padx=16)
        self.meta.pack(fill="x")
        foot = tk.Frame(r, bg=BG, padx=16, pady=12)
        foot.pack(side="bottom", fill="x")
        self.done = self.button(foot, "확인했어요", self.confirm, primary=True)
        self.done.pack(side="bottom", fill="x", pady=(8, 0))
        row = tk.Frame(foot, bg=BG)
        row.pack(fill="x")
        self.copy_text = self.button(row, "바레이션 복사", self.copy)
        self.copy_link = self.button(row, "링크 안내 복사", self.copy_lead)
        self.open_url = self.button(row, "원문 열기", self.open)
        self.later = self.button(row, "10분 뒤 다시", self.snooze)
        for b in (self.copy_text, self.copy_link, self.open_url, self.later):
            b.pack(side="left", expand=True, fill="x", padx=2)
        self.box = tk.Text(r, wrap="word", bg=BOX, fg=INK, font=(FONT, 11), relief="flat", padx=12, pady=10, height=10)
        self.box.pack(fill="both", expand=True, padx=16, pady=(10, 0))
        self.box.configure(state="disabled")
        self.snoozed_until = 0
        self.last_nag = time.time()
        if self.refresh():
            self.beep()
            self.root.after(5000, self.tick)

    def button(self, parent, text, cmd, primary=False):
        return tk.Button(parent, text=text, command=cmd, font=(FONT, 12 if primary else 10, "bold" if primary else "normal"), relief="flat", cursor="hand2",
                         bg=ACCENT if primary else BOX, fg="white" if primary else INK, activebackground=ACCENT if primary else "#e6e2e6", pady=9 if primary else 6)

    def items(self):
        done = set(load(CONFIRMED))
        return [p for p in load(PENDING) if p["key"] not in done]

    def current(self):
        return next((p for p in self.items() if p["key"] == self.key), None)

    def refresh(self):
        items = self.items()
        if not items:
            self.root.destroy()
            return False
        p = next((x for x in items if x["key"] == self.key), items[0])
        self.key = p["key"]
        writing = p.get("status") == WRITING and time.time() - p.get("found", 0) < WRITING_MAX_S
        self.count.configure(text=f"{p['source']}에 새 글 · 확인 안 한 글 {len(items)}개")
        self.title.configure(text=p.get("title") or f"{p['source']} 새 글")
        lines = [f"올라온 시각 {p.get('time', '')}"]
        if p.get("check"):
            lines += ["올리기 전 확인: " + " / ".join(p["check"])]
        self.meta.configure(text="\n".join(lines))
        body = {"건너뜀": f"바레이션을 쓰지 않았어요.\n이유: {p.get('reason', '')}\n\n원문을 열어 직접 판단해 주세요.",
                "실패": "바레이션을 쓰지 못했어요.\n원문을 열어 직접 만들어 주세요."}.get(p.get("status"), p.get("text") or "바레이션을 쓰는 중이에요. 보통 1분 안에 여기에 떠요.")
        if self.box.get("1.0", "end-1c") != body:
            self.box.configure(state="normal")
            self.box.delete("1.0", "end")
            self.box.insert("1.0", body)
            self.box.configure(state="disabled")
        self.copy_text.configure(state="normal" if p.get("text") else "disabled")
        self.copy_link.configure(state="normal" if p.get("link_lead") else "disabled")
        self.done.configure(state="disabled" if writing else "normal", text="바레이션 쓰는 중…" if writing else "확인했어요", disabledforeground="#f3d5e1")
        return True

    def confirm(self):
        CONFIRMED.write_text(json.dumps((load(CONFIRMED) + [self.key])[-300:], ensure_ascii=False), encoding="utf-8")
        self.key = None
        if self.refresh():
            self.beep()

    def clip(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()

    def copy(self):
        p = self.current()
        if p and p.get("text"):
            self.clip(p["text"])

    def copy_lead(self):
        p = self.current()
        if p and p.get("link_lead"):
            self.clip(f"{p['link_lead']}\n\n{p['url']}")

    def open(self):
        p = self.current()
        if p:
            webbrowser.open(p["url"])

    def snooze(self):
        self.snoozed_until = time.time() + SNOOZE_S
        self.root.withdraw()

    def beep(self):
        if winsound and datetime.now().hour >= 7:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)

    def nag(self):
        """다시 맨 위로 + 소리. 글을 치는 중일 수 있어서 입력 칸을 뺏지는 않음."""
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.beep()
        self.last_nag = time.time()

    def tick(self):
        if not self.refresh():
            return
        now = time.time()
        if now >= self.snoozed_until and now - self.last_nag >= NAG_S:
            self.nag()
        self.root.after(5000, self.tick)


def main():
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", PORT))   # 이미 떠 있으면 조용히 끝
    except OSError:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    app = App()
    try:
        app.root.mainloop()
    except tk.TclError:   # 다 확인해서 창이 닫힌 뒤
        pass


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parent)
    main()
