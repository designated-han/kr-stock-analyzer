"""에이전트 실행기.

Claude API 호출을 감싸는 하네스: 재시도, 타임아웃, 사용량 추적, 폴백, JSON 파싱.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path

import anthropic
import httpx
from pydantic import ValidationError

from core.config import settings
from core.models import AgentResult, AgentUsage, Conviction

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "agents" / "prompts"

JSON_RETRY_INSTRUCTION = (
    "이전 응답이 유효한 JSON이 아닙니다. "
    "마크다운 코드블록이나 설명을 넣지 말고 JSON 객체만 출력하세요."
)

# 백만 토큰당 USD (Anthropic 정가: 입력 / 출력 / 캐시 기록 / 캐시 읽기)
_PRICING_PER_MTOK = {
    "haiku": {"input": 0.80, "output": 4.00, "cache_write": 1.00, "cache_read": 0.08},
    "opus": {"input": 15.00, "output": 75.00, "cache_write": 18.75, "cache_read": 1.50},
    "sonnet": {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30},
}

DEPTH_INSTRUCTIONS = {
    "quick": "핵심 지표 2~3개만 빠르게 평가하세요. 상세 분석 불필요.",
    "standard": "주요 지표를 종합적으로 분석하세요.",
    "deep": (
        "모든 이용 가능한 데이터를 정밀 분석하세요. "
        "시나리오 분석, 민감도 분석 포함."
    ),
}

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_MAX_TOKENS = {"quick": 2048, "standard": 4096, "deep": 8192}


def load_prompt(agent_name: str) -> str:
    """에이전트 프롬프트 파일을 로드합니다."""
    prompt_path = PROMPTS_DIR / f"{agent_name}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"프롬프트 파일 없음: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def fallback_agent_result(agent_name: str, error: BaseException | str) -> AgentResult:
    """에이전트 완전 실패 시 합성 단계가 인지할 수 있는 중립 결과를 만듭니다."""
    return AgentResult(
        agent=agent_name,
        score=5.0,
        conviction=Conviction.NEUTRAL,
        summary=f"[{agent_name}] 분석 실패: {error}",
        evidence=[],
        risks=[],
        raw_analysis="",
    )


async def run_agent(
    agent_name: str,
    user_message: str,
    model: str | None = None,
    context: str = "",
    depth: str = "standard",
    client: anthropic.AsyncAnthropic | None = None,
) -> AgentResult:
    """단일 에이전트를 실행하고 구조화된 결과를 반환합니다.

    Args:
        agent_name: 에이전트 이름 (prompts/ 아래 파일명과 일치)
        user_message: 사용자 메시지 (분석 대상 기업 정보 등)
        model: 사용할 Claude 모델 (None이면 기본 모델)
        context: 이전 계층의 분석 결과 등 추가 컨텍스트
        depth: 분석 깊이 (quick / standard / deep)
        client: 공유 AsyncAnthropic 클라이언트 (없으면 새로 생성)

    Returns:
        AgentResult: 구조화된 분석 결과 (실패 시에도 폴백 결과)
    """
    if not settings.anthropic_api_key:
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        raise anthropic.AuthenticationError(
            "ANTHROPIC_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.",
            response=httpx.Response(401, request=request),
            body=None,
        )

    system_prompt = load_prompt(agent_name)
    model = model or settings.claude_model_default
    depth_instruction = DEPTH_INSTRUCTIONS.get(depth, DEPTH_INSTRUCTIONS["standard"])

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

    full_system = (
        system_prompt
        + f"\n\n## 분석 깊이\n현재 요청 깊이: {depth}\n{depth_instruction}"
        + schema_instruction
    )
    full_user = user_message
    if context:
        full_user += f"\n\n## 이전 분석 결과 (참고)\n{context}"

    if client is None:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    started = time.perf_counter()

    try:
        result = await asyncio.wait_for(
            _invoke_with_retries(
                client=client,
                agent_name=agent_name,
                model=model,
                system_prompt=full_system,
                user_message=full_user,
                depth=depth,
            ),
            timeout=settings.agent_timeout,
        )
    except anthropic.AuthenticationError:
        raise
    except TimeoutError as e:
        logger.error(f"[{agent_name}] 타임아웃 ({settings.agent_timeout}초)")
        result = fallback_agent_result(agent_name, e)
    except Exception as e:
        logger.exception(f"[{agent_name}] 예상치 못한 오류")
        result = fallback_agent_result(agent_name, e)

    elapsed = time.perf_counter() - started
    if result.usage is None:
        result.usage = AgentUsage(model=model)
    result.usage.elapsed_seconds = elapsed
    if not result.usage.model:
        result.usage.model = model
    return result


async def _invoke_with_retries(
    client: anthropic.AsyncAnthropic,
    agent_name: str,
    model: str,
    system_prompt: str,
    user_message: str,
    depth: str = "standard",
) -> AgentResult:
    """에러 타입별로 재시도하며 모델을 호출합니다."""
    messages: list[dict] = [{"role": "user", "content": user_message}]
    usage_acc = AgentUsage(model=model)
    last_error: BaseException | None = None
    max_attempts = settings.max_retries + 1
    max_tokens = _MAX_TOKENS.get(depth, 4096)

    for attempt in range(max_attempts):
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},  # 프롬프트 캐싱
                    }
                ],
                messages=messages,
            )
            usage_acc = usage_acc.merge(_usage_from_response(response, model))

            raw_text = response.content[0].text
            json_str = _extract_json(raw_text)
            data = json.loads(json_str)
            data.pop("usage", None)
            result = AgentResult.model_validate({**data, "agent": agent_name})
            result.usage = usage_acc

            logger.info(
                f"[{agent_name}] 완료 — 점수: {result.score}, "
                f"확신도: {result.conviction.value}, "
                f"토큰: {usage_acc.input_tokens}+{usage_acc.output_tokens}, "
                f"비용: ${usage_acc.estimated_cost_usd:.4f}"
            )
            return result

        except anthropic.AuthenticationError:
            raise

        except anthropic.RateLimitError as e:
            last_error = e
            logger.warning(f"[{agent_name}] Rate limit (시도 {attempt + 1}/{max_attempts}): {e}")
            if attempt < max_attempts - 1:
                await asyncio.sleep(2**attempt)
            continue

        except anthropic.APIStatusError as e:
            last_error = e
            retryable = e.status_code >= 500
            logger.error(
                f"[{agent_name}] API {e.status_code} (시도 {attempt + 1}/{max_attempts}): {e}"
            )
            if not retryable or attempt >= max_attempts - 1:
                break
            await asyncio.sleep(min(2**attempt, 8))
            continue

        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
            last_error = e
            logger.error(f"[{agent_name}] 연결 오류 (시도 {attempt + 1}/{max_attempts}): {e}")
            if attempt < max_attempts - 1:
                await asyncio.sleep(min(2**attempt, 8))
            continue

        except (json.JSONDecodeError, ValidationError) as e:
            last_error = e
            logger.warning(f"[{agent_name}] 파싱 실패 (시도 {attempt + 1}/{max_attempts}): {e}")
            if attempt >= max_attempts - 1:
                break
            # 모델에게 JSON만 다시 출력하도록 대화 턴을 추가
            assistant_text = ""
            try:
                assistant_text = response.content[0].text  # type: ignore[name-defined]
            except Exception:
                assistant_text = ""
            if assistant_text:
                messages.append({"role": "assistant", "content": assistant_text})
            messages.append({"role": "user", "content": JSON_RETRY_INSTRUCTION})
            continue

    error = last_error or RuntimeError("에이전트 호출 실패")
    logger.error(f"[{agent_name}] 재시도 소진 — 폴백 반환: {error}")
    result = fallback_agent_result(agent_name, error)
    result.usage = usage_acc
    return result


def _usage_from_response(response: object, model: str) -> AgentUsage:
    """Anthropic 응답에서 AgentUsage를 추출합니다."""
    raw = getattr(response, "usage", None)
    input_tokens = int(getattr(raw, "input_tokens", 0) or 0)
    output_tokens = int(getattr(raw, "output_tokens", 0) or 0)
    cache_read = int(getattr(raw, "cache_read_input_tokens", 0) or 0)
    cache_creation = int(getattr(raw, "cache_creation_input_tokens", 0) or 0)
    return AgentUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_creation,
        model=model,
        estimated_cost_usd=_estimate_cost_usd(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_creation,
        ),
    )


def _estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
) -> float:
    """모델명에 따른 대략적 USD 비용을 계산합니다."""
    name = model.lower()
    if "haiku" in name:
        prices = _PRICING_PER_MTOK["haiku"]
    elif "opus" in name:
        prices = _PRICING_PER_MTOK["opus"]
    else:
        prices = _PRICING_PER_MTOK["sonnet"]

    million = 1_000_000
    return (
        input_tokens * prices["input"]
        + output_tokens * prices["output"]
        + cache_creation_tokens * prices["cache_write"]
        + cache_read_tokens * prices["cache_read"]
    ) / million


def _extract_json(text: str) -> str:
    """응답 텍스트에서 JSON 객체만 추출합니다.

    앞뒤 설명, 마크다운 펜스, 문자열 안의 중첩 ```json 을 처리합니다.
    """
    candidates: list[str] = []
    for block in _FENCE_RE.findall(text):
        candidates.append(block.strip())
    # 마지막 펜스(최종 답)를 우선 시도
    candidates.reverse()
    candidates.append(text.strip())

    for candidate in candidates:
        sliced = _slice_json_object(candidate)
        if sliced is None:
            continue
        try:
            parsed = json.loads(sliced)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return sliced

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _slice_json_object(text: str) -> str | None:
    """텍스트에서 디코딩 가능한 첫 JSON 객체 슬라이스를 반환합니다."""
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, end = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return text[i : i + end]
    return None
