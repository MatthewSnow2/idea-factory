"""Pydantic models for Agentic Idea Factory.

These models define the contracts between pipeline stages.
"""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================


class Stage(str, Enum):
    """Pipeline stages."""

    INPUT = "input"
    ENRICHMENT = "enrichment"
    EVALUATION = "evaluation"
    HUMAN_REVIEW = "human_review"
    SCAFFOLDING = "scaffolding"
    BUILDING = "building"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class Status(str, Enum):
    """Stage statuses."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    AWAITING_REVIEW = "awaiting_review"
    PAUSED = "paused"


class CapabilitiesFit(str, Enum):
    """Capabilities fit assessment."""

    STRONG = "strong"
    DEVELOPING = "developing"
    MISSING = "missing"


class Recommendation(str, Enum):
    """Evaluation recommendation."""

    DEVELOP = "develop"
    REFINE = "refine"
    REJECT = "reject"
    DEFER = "defer"


class ReviewDecision(str, Enum):
    """Human review decision."""

    APPROVE = "approve"
    REFINE = "refine"
    REJECT = "reject"
    DEFER = "defer"


# =============================================================================
# Input Models
# =============================================================================


class IdeaInput(BaseModel):
    """Input for creating a new idea."""

    title: str = Field(..., min_length=3, max_length=200)
    raw_content: str = Field(..., min_length=10)
    tags: list[str] = Field(default_factory=list)


class HumanReviewInput(BaseModel):
    """Input for human review decision."""

    decision: ReviewDecision
    decision_rationale: str | None = None


# =============================================================================
# Stage Output Models
# =============================================================================


class EnrichmentOutput(BaseModel):
    """Output from enrichment stage (Gemini)."""

    enhanced_title: str
    enhanced_description: str
    problem_statement: str
    potential_solutions: list[str]
    market_context: str


class EvaluationScores(BaseModel):
    """Scores from Christensen evaluation."""

    disruption_score: float = Field(..., ge=0.0, le=1.0)
    overall_score: float = Field(..., ge=0.0, le=100.0)


class EvaluationOutput(BaseModel):
    """Output from evaluation stage (Christensen MCP)."""

    jtbd_analysis: str
    disruption_potential: str
    scores: EvaluationScores
    capabilities_fit: CapabilitiesFit
    recommendation: Recommendation
    recommendation_rationale: str
    key_risks: list[str]
    case_study_matches: list[str]


class ScaffoldingOutput(BaseModel):
    """Output from scaffolding stage (Claude)."""

    blueprint_content: str
    project_structure: dict[str, list[str]]  # directory -> files
    tech_stack: list[str]
    estimated_hours: float | None = None


class BuildOutput(BaseModel):
    """Output from build stage."""

    github_repo: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    outcome: Literal["success", "partial", "failed"]


# =============================================================================
# Database Record Models
# =============================================================================


class Idea(BaseModel):
    """Full idea record from database."""

    id: str
    title: str
    raw_content: str
    tags: list[str]
    current_stage: Stage
    current_status: Status
    submitted_at: datetime
    updated_at: datetime


class EnrichmentResult(BaseModel):
    """Enrichment result record."""

    idea_id: str
    enhanced_title: str
    enhanced_description: str
    problem_statement: str
    potential_solutions: list[str]
    market_context: str
    enriched_at: datetime
    enriched_by: str


class EvaluationResult(BaseModel):
    """Evaluation result record."""

    idea_id: str
    jtbd_analysis: str
    disruption_potential: str
    disruption_score: float
    capabilities_fit: CapabilitiesFit
    recommendation: Recommendation
    recommendation_rationale: str
    key_risks: list[str]
    case_study_matches: list[str]
    overall_score: float
    evaluated_at: datetime
    evaluated_by: str


class HumanReview(BaseModel):
    """Human review record."""

    id: str
    idea_id: str
    stage: Stage
    decision: ReviewDecision
    decision_rationale: str | None
    reviewer: str
    reviewed_at: datetime


class StateTransition(BaseModel):
    """State transition audit record."""

    id: str
    idea_id: str
    from_stage: Stage
    from_status: Status
    to_stage: Stage
    to_status: Status
    triggered_by: str
    metadata: dict | None
    created_at: datetime


# =============================================================================
# API Response Models
# =============================================================================


class IdeaResponse(BaseModel):
    """API response for a single idea with all related data."""

    idea: Idea
    enrichment: EnrichmentResult | None = None
    evaluation: EvaluationResult | None = None
    reviews: list[HumanReview] = Field(default_factory=list)


class IdeaListResponse(BaseModel):
    """API response for listing ideas."""

    ideas: list[Idea]
    total: int


class PipelineStatusResponse(BaseModel):
    """API response for pipeline status."""

    idea_id: str
    current_stage: Stage
    current_status: Status
    can_advance: bool
    next_action: str | None = None
    history: list[StateTransition] = Field(default_factory=list)
