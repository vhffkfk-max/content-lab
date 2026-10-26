"""바꾼 모델(Haiku 5.5·Sonnet 5.5)이 구조화 출력·생각량 설정으로 잘 되는지 아주 작게 시험 (1회용)."""
from typing import List

import anthropic
from pydantic import BaseModel


class Out(BaseModel):
    summary_ko: str
    tags: List[str]


client = anthropic.Anthropic()
for model, stream in (("claude-haiku-5-5", True), ("claude-haiku-5-5", False), ("claude-sonnet-5-5", True)):
    kw = dict(model=model, max_tokens=2000, output_config={"effort": "low"}, output_format=Out,
              messages=[{"role": "user", "content": "Summarize in Korean in one sentence: 'Fed holds rates steady, signals two cuts next year.' tags: 2 words"}])
    try:
        if stream:
            with client.messages.stream(**kw) as s:
                r = s.get_final_message()
        else:
            r = client.messages.parse(**kw)
        print(model, "stream" if stream else "parse", r.stop_reason, r.parsed_output, r.usage.input_tokens, r.usage.output_tokens)
    except Exception as e:
        print(model, "실패", type(e).__name__, str(e)[:300])
