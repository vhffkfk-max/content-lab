"""정제 + 준비된(ready) 계정 생성을 한 번에. local_ai.py 가 하루 3번(07·12·18시) 부른다.

    python -m acclab.run
"""
import sys

import llm as anthropic
from acclab import generate, refine
from acclab.common import accounts


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if not anthropic.ready():
        print("Claude(Max)를 부를 수 없는 곳이라 건너뜀")
        return 0
    sys.argv = [sys.argv[0]]
    refine.main()
    made = 0
    for a in accounts():
        if a.get("ready"):
            made += generate.run(a["slug"], a["daily_max"]) or 0
    print(f"계정 글 {made}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
