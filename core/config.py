"""애플리케이션 설정."""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """환경변수 기반 설정."""

    # Claude API
    anthropic_api_key: str = Field(..., description="Anthropic API 키")
    claude_model_default: str = Field("claude-sonnet-4-20250514", description="기본 모델")
    claude_model_cheap: str = Field("claude-haiku-4-20250414", description="데이터 수집용 저비용 모델")
    claude_model_quality: str = Field("claude-sonnet-4-20250514", description="분석/합성용 고품질 모델")

    # DART API
    dart_api_key: str = Field("", description="DART Open API 키")

    # Naver Search API
    naver_client_id: str = Field("", description="Naver 클라이언트 ID")
    naver_client_secret: str = Field("", description="Naver 클라이언트 시크릿")

    # 실행 설정
    max_concurrent_agents: int = Field(5, description="최대 동시 에이전트 수")
    max_retries: int = Field(2, description="에이전트 실패 시 재시도 횟수")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
