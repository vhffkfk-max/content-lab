""".env 의 인스타 토큰을 GitHub 저장소 비밀값(Secrets)으로 등록한다. 값은 화면에 출력하지 않는다.

먼저 gh auth login 으로 GitHub 에 로그인한 뒤:
    python push_secrets.py
Claude API 키는 따로: gh secret set ANTHROPIC_API_KEY  (붙여넣기 프롬프트가 뜸)
"""
import os
import subprocess
import sys

from common import ROOT, load_env


def main():
    load_env()
    for name in ("IG_ACCESS_TOKEN", "IG_USER_ID"):
        value = os.environ.get(name)
        if not value:
            sys.exit(f"❌ .env 에 {name} 이 없어요.")
        subprocess.run(["gh", "secret", "set", name], input=value, text=True, check=True, cwd=ROOT,
                       stdout=subprocess.DEVNULL)
        print(f"✅ {name} 등록")


if __name__ == "__main__":
    main()
