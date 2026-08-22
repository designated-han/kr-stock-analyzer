"""에이전트 실행기.

Claude API를 호출하여 에이전트를 실행하고, 구조화된 출력을 파싱합니다.
"""

import json
import logging
from pathlib import Path

import anthropic
from pydantic import ValidationError

from core.config import settings
from core.models import AgentResult

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "agents" / "prompts"


def load_prompt(agent_name: str) -> str:
    """에이전트 프롬프트 파일을 로드합니다."""
    prompt_path = PROMPTS_DIR / f"{agent_name}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"프롬프트 파일 없음: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


async def run_agent(
    agent_name: str,
    user_message: str,
    model: str | None = None,
    context: str = "",
) -> AgentResult:
    """단일 에이전트를 실행하고 구조화된 결과를 반환합니다.

    Args:
        agent_name: 에이전트 이름 (prompts/ 아래 파일명과 일치)
        user_message: 사용자 메시지 (분석 대상 기업 정보 등)
        model: 사용할 Claude 모델 (None이면 기본 모델)
        context: 이전 계층의 분석 결과 등 추가 컨텍스트

    Returns:
        AgentResult: 구조화된 분석 결과
    """
    system_prompt = load_prompt(agent_name)
    model = model or settings.claude_model_default

    # 출력 스키마를 시스템 프롬프트에 주입
    schema_instruction = f"""

## 출력 형식
반드시 아래 JSON 스키마에 맞춰 응답하세요. JSON만 출력하고, 다른 텍스트는 포함하지 마세요.

```json
{{
  "agent": "{agent_name}",
  "score": <1~10 사이 숫자>,
  "conviction": "<strong_positive|positive|neutral|negative|strong_negative>",
  "summary": "<핵심 결론 2~3문장>",
  "evidence": [
    {{"claim": "<주장>", "data": "<수치/데이터>", "source": "<출처>"}}
  ],
  "risks": [
    {{"title": "<리스크>", "description": "<설명>", "severity": <1~5>, "probability": <1~5>}}
  ],
  "raw_analysis": "<상세 분석 텍스트>"
}}
```"""

    full_system = system_prompt + schema_instruction
    full_user = user_message
    if context:
        full_user += f"\n\n## 이전 분석 결과 (참고)\n{context}"

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    for attempt in range(settings.max_retries + 1):
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=4096,
                system=[
                    {
                        "type": "text",
                        "text": full_system,
                        "cache_control": {"type": "ephemeral"},  # 프롬프트 캐싱
                    }
                ],
                messages=[{"role": "user", "content": full_user}],
            )

            # 응답에서 JSON 추출
            raw_text = response.content[0].text
            json_str = _extract_json(raw_text)
            data = json.loads(json_str)
            result = AgentResult(**data)

            logger.info(
                f"[{agent_name}] 완료 — 점수: {result.score}, "
                f"확신도: {result.conviction.value}, "
                f"토큰: {response.usage.input_tokens}+{response.usage.output_tokens}"
            )
            return result

        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning(f"[{agent_name}] 파싱 실패 (시도 {attempt + 1}): {e}")
            if attempt == settings.max_retries:
                raise
        except anthropic.APIError as e:
            logger.error(f"[{agent_name}] API 오류 (시도 {attempt + 1}): {e}")
            if attempt == settings.max_retries:
                raise


def _extract_json(text: str) -> str:
    """응답 텍스트에서 JSON 부분만 추출합니다."""
    # ```json ... ``` 블록이 있으면 그 안의 내용 추출
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        return text[start:end].strip()
    if "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        return text[start:end].strip()
    # JSON 객체 직접 찾기
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        return text[start:end]
    return text
