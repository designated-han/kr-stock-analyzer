"""에이전트 입출력 공통 모델.

모든 에이전트는 이 공통 스키마를 따르는 구조화된 출력을 반환합니다.
"""

from enum import Enum

from pydantic import BaseModel, Field


class Conviction(str, Enum):
    """확신도."""

    STRONG_POSITIVE = "strong_positive"
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    STRONG_NEGATIVE = "strong_negative"


class Evidence(BaseModel):
    """분석 근거."""

    claim: str = Field(description="주장")
    data: str = Field(description="뒷받침 데이터 또는 수치")
    source: str = Field(default="", description="출처")


class Risk(BaseModel):
    """식별된 리스크."""

    title: str = Field(description="리스크 제목")
    description: str = Field(description="리스크 설명")
    severity: int = Field(ge=1, le=5, description="심각도 (1~5)")
    probability: int = Field(ge=1, le=5, description="발생 확률 (1~5)")


class AgentResult(BaseModel):
    """모든 에이전트의 공통 출력 스키마.

    오케스트레이터와 합성 에이전트는 이 형식만 이해합니다.
    """

    agent: str = Field(description="에이전트 이름 (예: financial, buffett)")
    score: float = Field(ge=1, le=10, description="종합 점수 (1~10)")
    conviction: Conviction = Field(description="확신도")
    summary: str = Field(description="핵심 결론 (2~3문장)")
    evidence: list[Evidence] = Field(default_factory=list, description="근거 목록")
    risks: list[Risk] = Field(default_factory=list, description="식별된 리스크")
    raw_analysis: str = Field(default="", description="상세 분석 텍스트")


class CompanyInfo(BaseModel):
    """분석 대상 기업 기본 정보."""

    name: str = Field(description="기업명")
    corp_code: str = Field(default="", description="DART 기업코드")
    stock_code: str = Field(default="", description="종목코드 (6자리)")
    industry: str = Field(default="", description="업종")
    ceo: str = Field(default="", description="대표이사")
    established: str = Field(default="", description="설립일")
    market: str = Field(default="KOSPI", description="시장 (KOSPI/KOSDAQ)")


class AnalysisRequest(BaseModel):
    """분석 요청."""

    company: CompanyInfo = Field(description="분석 대상 기업")
    depth: str = Field(default="standard", description="분석 깊이 (quick/standard/deep)")


class ConsensusOpinion(str, Enum):
    """최종 컨센서스 의견."""

    STRONG_BUY = "적극 매수"
    BUY = "매수"
    HOLD = "관망"
    SELL = "매도"
    STRONG_SELL = "적극 매도"


class SynthesisResult(BaseModel):
    """리포트 합성 최종 결과."""

    company: CompanyInfo
    overall_score: float = Field(ge=1, le=10, description="종합 점수")
    consensus: ConsensusOpinion = Field(description="컨센서스 의견")
    key_points: list[str] = Field(description="핵심 투자 포인트 (3~5개)")
    analyst_results: list[AgentResult] = Field(description="실무 분석 결과")
    philosophy_results: list[AgentResult] = Field(description="철학 평가 결과")
    agreements: list[str] = Field(default_factory=list, description="의견 일치 사항")
    conflicts: list[str] = Field(default_factory=list, description="의견 충돌 사항")
    executive_summary: str = Field(description="Executive Summary")
