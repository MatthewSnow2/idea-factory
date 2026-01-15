"""Pydantic models for Agentic Idea Factory.

These models define the contracts between pipeline stages.
"""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


# =============================================================================
# Enums
# =============================================================================


class Stage(str, Enum):
    """Pipeline stages."""

    INPUT = "input"
    PROJECT_ANALYSIS = "project_analysis"  # NEW: For existing projects
    ENRICHMENT = "enrichment"
    EVALUATION = "evaluation"
    HUMAN_REVIEW = "human_review"
    SCAFFOLDING = "scaffolding"
    BUILDING = "building"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ProjectMode(str, Enum):
    """Project processing mode."""

    NEW = "new"  # Create new project from scratch
    EXISTING_COMPLETE = "existing_complete"  # Analyze and complete existing project
    EXISTING_ENHANCE = "existing_enhance"  # Analyze and add features to existing project


class SourceType(str, Enum):
    """Source type for existing projects."""

    LOCAL_PATH = "local_path"  # Local filesystem path
    GIT_URL = "git_url"  # Remote git repository URL


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


class ProjectSource(BaseModel):
    """Source configuration for existing projects."""

    source_type: SourceType
    location: str  # Path or URL
    branch: str | None = None  # For git URLs
    subdirectory: str | None = None  # If project is in a subdirectory


class IdeaInput(BaseModel):
    """Input for creating a new idea."""

    title: str = Field(..., min_length=3, max_length=200)
    raw_content: str = Field(..., min_length=10)
    tags: list[str] = Field(default_factory=list)
    mode: ProjectMode = ProjectMode.NEW
    project_source: ProjectSource | None = None
    preferred_tech_stack: list[str] | None = Field(
        default=None,
        description="Optional user-specified tech stack. If provided, skips AI tech stack decision.",
    )

    @model_validator(mode="after")
    def validate_source_for_existing(self) -> "IdeaInput":
        """Require project_source for EXISTING modes."""
        if self.mode != ProjectMode.NEW and not self.project_source:
            raise ValueError(f"project_source required for mode {self.mode}")
        return self


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


class FileModification(BaseModel):
    """A modification to an existing file (for existing projects)."""

    file_path: str
    modification_type: Literal["patch", "replace", "append", "insert"]
    content: str  # Patch diff or new content
    line_start: int | None = None  # For insert/append
    rationale: str


class NewFileSpec(BaseModel):
    """Specification for a new file to create (for existing projects)."""

    file_path: str
    purpose: str
    integrates_with: list[str] = Field(default_factory=list)  # Existing files


class ScaffoldingOutput(BaseModel):
    """Output from scaffolding stage (Claude)."""

    blueprint_content: str
    project_structure: dict[str, list[str]]  # directory -> files
    tech_stack: list[str]
    estimated_hours: float | None = None
    # For existing projects
    file_modifications: list[FileModification] = Field(default_factory=list)
    new_files: list[NewFileSpec] = Field(default_factory=list)
    preserved_files: list[str] = Field(default_factory=list)


class BuildOutput(BaseModel):
    """Output from build stage."""

    github_repo: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    outcome: Literal["success", "partial", "failed"]


# =============================================================================
# Project Analysis Models (for existing projects)
# =============================================================================


class FileAnalysis(BaseModel):
    """Analysis of a single file."""

    path: str
    language: str
    purpose: str  # Brief description of what this file does
    dependencies: list[str] = Field(default_factory=list)  # What it imports/requires
    exports: list[str] = Field(default_factory=list)  # What it exports/provides
    issues: list[str] = Field(default_factory=list)  # Problems detected
    todos: list[str] = Field(default_factory=list)  # TODO comments found


class ArchitecturePattern(BaseModel):
    """Detected architecture pattern."""

    pattern_name: str  # e.g., "MVC", "Clean Architecture", "Microservices"
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)  # Files/patterns that support this


class CompletionGap(BaseModel):
    """A gap identified for COMPLETE mode."""

    gap_type: Literal[
        "missing_feature", "incomplete_implementation", "broken_test", "todo"
    ]
    description: str
    location: str  # File path or general area
    priority: Literal["high", "medium", "low"]
    estimated_effort: Literal["small", "medium", "large"]


class EnhancementOpportunity(BaseModel):
    """An enhancement opportunity for ENHANCE mode."""

    opportunity_type: Literal["new_feature", "refactoring", "performance", "testing"]
    description: str
    affected_areas: list[str] = Field(default_factory=list)
    integration_points: list[str] = Field(default_factory=list)
    estimated_effort: Literal["small", "medium", "large"]


class ProjectAnalysisOutput(BaseModel):
    """Output from project analysis stage."""

    # Basic project info
    project_name: str
    detected_tech_stack: list[str]
    detected_patterns: list[ArchitecturePattern] = Field(default_factory=list)

    # File structure analysis
    total_files: int
    key_files: list[FileAnalysis] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)

    # For COMPLETE mode
    completion_gaps: list[CompletionGap] = Field(default_factory=list)
    completeness_score: float | None = None  # 0.0 to 1.0

    # For ENHANCE mode
    enhancement_opportunities: list[EnhancementOpportunity] = Field(default_factory=list)
    architecture_quality_score: float | None = None  # 0.0 to 1.0

    # Common
    readme_summary: str | None = None
    existing_blueprint: str | None = None  # If BLUEPRINT.md exists
    constraints: list[str] = Field(default_factory=list)  # e.g., "n8n-constrained"


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
    mode: ProjectMode = ProjectMode.NEW
    project_source: ProjectSource | None = None
    preferred_tech_stack: list[str] | None = None


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


class ProjectAnalysisResult(BaseModel):
    """Project analysis result record (for existing projects)."""

    idea_id: str
    project_name: str
    detected_tech_stack: list[str]
    detected_patterns: list[ArchitecturePattern]
    total_files: int
    key_files: list[FileAnalysis]
    entry_points: list[str]
    completion_gaps: list[CompletionGap] = Field(default_factory=list)
    completeness_score: float | None = None
    enhancement_opportunities: list[EnhancementOpportunity] = Field(default_factory=list)
    architecture_quality_score: float | None = None
    readme_summary: str | None = None
    existing_blueprint: str | None = None
    constraints: list[str] = Field(default_factory=list)
    analyzed_at: datetime
    analyzed_by: str


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


class ScaffoldingResult(BaseModel):
    """Scaffolding result record."""

    idea_id: str
    blueprint_content: str
    project_structure: dict[str, list[str]]
    tech_stack: list[str]
    estimated_hours: float | None
    scaffolded_at: datetime
    scaffolded_by: str
    # For existing projects
    file_modifications: list[FileModification] = Field(default_factory=list)
    new_files: list[NewFileSpec] = Field(default_factory=list)
    preserved_files: list[str] = Field(default_factory=list)


class BuildResult(BaseModel):
    """Build result record."""

    idea_id: str
    github_repo: str | None
    artifacts: list[str]
    outcome: Literal["success", "partial", "failed"]
    started_at: datetime
    completed_at: datetime | None


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
