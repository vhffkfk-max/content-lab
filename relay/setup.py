"""사이트 버튼 중간 서버 설정: 깃허브 토큰과 암호 두 개를 창에 넣으면 Vercel 에 저장하고 다시 배포한다.
값은 화면·파일·로그에 남기지 않는다. 토큰이 만료됐거나 암호를 바꿀 때 다시 실행: python relay/setup.py"""
import re
import subprocess
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox

import requests

HERE = Path(__file__).parent
REPO = "vhffkfk-max/content-lab"
NEW_TOKEN = ("https://github.com/settings/personal-access-tokens/new?name=content-lab-relay"
             "&description=site-relay&target_name=vhffkfk-max&expires_in=366&contents=write&actions=write")


def vercel(*args, stdin=None):
    return subprocess.run(["npx.cmd", "--yes", "vercel@65.0.0", *args], cwd=HERE, input=stdin,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def problem(token, key, owner):
    ok = re.compile(r"[\x21-\x7e]{10,}")
    if not ok.fullmatch(key) or not ok.fullmatch(owner):
        return "암호는 띄어쓰기 없이 영문·숫자·기호 10자 이상으로 해 주세요."
    if key == owner:
        return "공용 암호와 발행 암호는 서로 달라야 해요."
    r = requests.get(f"https://api.github.com/repos/{REPO}", headers={"Authorization": f"Bearer {token}"}, timeout=20)
    if r.status_code != 200:
        return f"깃허브 토큰이 안 맞아요({r.status_code}). 코드를 끝까지 복사했는지 확인해 주세요."
    return ""


def apply(token, key, owner):
    for name, value in (("LAB_GH_TOKEN", token), ("LAB_KEY", key), ("LAB_OWNER_KEY", owner)):
        if not vercel("env", "add", name, "production", "--force", stdin=value.encode()):
            return f"{name} 저장에 실패했어요."
    return "" if vercel("deploy", "--prod", "--yes") else "저장은 됐지만 배포에 실패했어요."


def main():
    win = tk.Tk()
    win.title("컨텐츠 연구소 중간 서버 설정")
    win.attributes("-topmost", True)
    frame = tk.Frame(win, padx=20, pady=16)
    frame.pack()
    entries = []
    for i, (label, hint) in enumerate((
            ("깃허브 토큰", "위 버튼 → Only select repositories → content-lab → Generate token → 복사"),
            ("공용 암호", "같이 쓰는 분들에게 알려 줄 암호 (10자 이상)"),
            ("인스타 발행 암호", "대표님만 아는 암호 (공용 암호와 다르게, 10자 이상)"))):
        tk.Label(frame, text=label, font=("맑은 고딕", 10, "bold")).grid(row=1 + i * 2, column=0, sticky="w", pady=(10, 0))
        tk.Label(frame, text=hint, fg="#666", font=("맑은 고딕", 9)).grid(row=1 + i * 2, column=1, sticky="w", pady=(10, 0))
        e = tk.Entry(frame, width=64, show="" if i else "*")
        e.grid(row=2 + i * 2, column=0, columnspan=2, sticky="we")
        entries.append(e)
    tk.Button(frame, text="깃허브에서 토큰 만들기", command=lambda: webbrowser.open(NEW_TOKEN)).grid(row=0, column=0, columnspan=2, sticky="w")
    status = tk.Label(frame, text="", fg="#a00", font=("맑은 고딕", 9))
    status.grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def save():
        token, key, owner = (e.get().strip() for e in entries)
        msg = problem(token, key, owner)
        if not msg:
            status.config(text="저장하고 배포하는 중이에요… 1분쯤 걸려요.", fg="#333")
            win.update()
            msg = apply(token, key, owner)
        if msg:
            status.config(text=msg, fg="#a00")
            return
        messagebox.showinfo("완료", "저장했어요. 이 창을 닫으면 끝이에요.")
        print("OK: 저장 후 배포 완료")
        win.destroy()

    tk.Button(frame, text="저장하고 배포", command=save).grid(row=8, column=0, columnspan=2, sticky="e", pady=(12, 0))
    win.mainloop()


if __name__ == "__main__":
    main()
