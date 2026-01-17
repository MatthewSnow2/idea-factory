"""Ideas API routes."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from ..auth.middleware import get_optional_user, require_terms_accepted
from ..auth.rate_limit import get_rate_limit_status, record_idea_submission, require_rate_limit
from ..core.models import (
    Idea,
    IdeaInput,
    IdeaListResponse,
    IdeaResponse,
    PipelineStatusResponse,
    ProjectAnalysisResult,
    ProjectMode,
    Stage,
    Status,
    User,
)
from ..db.repository import repository
from ..pipeline.orchestrator import PipelineOrchestrator

router = APIRouter(prefix="/api/ideas", tags=["ideas"])


@router.post("", response_model=Idea, status_code=201)
async def create_idea(
    input_data: IdeaInput,
    user: Annotated[User, Depends(require_terms_accepted)] = None,
) -> Idea:
    """Create a new idea.

    The idea starts in INPUT stage with PENDING status.
    Use POST /ideas/{id}/start to begin the pipeline.

    Requires authentication and terms acceptance.
    Rate limited to 10 ideas per day per user.

    Modes:
        - NEW: Generate a brand new project (default)
        - EXISTING_COMPLETE: Analyze and complete an existing project
        - EXISTING_ENHANCE: Analyze and add features to an existing project

    For EXISTING modes, project_source is required with:
        - source_type: "local_path" or "git_url"
        - location: Path or URL to the project
        - branch: Optional git branch (for git_url)
        - subdirectory: Optional subdirectory within the project
    """
    # Check rate limit
    if user:
        await require_rate_limit(user)

    # Create idea with user attribution
    submitted_by = user.id if user else None
    idea = await repository.create_idea(input_data, submitted_by=submitted_by)

    # Record for rate limiting
    if user:
        record_idea_submission(user.id)

    return idea


@router.get("/rate-limit", response_model=dict)
async def get_my_rate_limit(
    user: Annotated[User, Depends(require_terms_accepted)],
) -> dict:
    """Get current rate limit status for authenticated user."""
    return get_rate_limit_status(user.id)


@router.get("", response_model=IdeaListResponse)
async def list_ideas(
    stage: Stage | None = None,
    status: Status | None = None,
    limit: int = 100,
    offset: int = 0,
) -> IdeaListResponse:
    """List ideas with optional filtering."""
    ideas = await repository.list_ideas(stage=stage, status=status, limit=limit, offset=offset)
    return IdeaListResponse(ideas=ideas, total=len(ideas))


@router.get("/{idea_id}", response_model=IdeaResponse)
async def get_idea(idea_id: str) -> IdeaResponse:
    """Get idea with all related data."""
    idea = await repository.get_idea(idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail=f"Idea not found: {idea_id}")

    enrichment = await repository.get_enrichment(idea_id)
    evaluation = await repository.get_evaluation(idea_id)
    reviews = await repository.get_reviews(idea_id)

    return IdeaResponse(
        idea=idea,
        enrichment=enrichment,
        evaluation=evaluation,
        reviews=reviews,
    )


@router.get("/{idea_id}/analysis", response_model=ProjectAnalysisResult | None)
async def get_project_analysis(idea_id: str) -> ProjectAnalysisResult | None:
    """Get project analysis results for an existing project idea.

    Only available for ideas with mode EXISTING_COMPLETE or EXISTING_ENHANCE.
    Returns None if analysis hasn't been run yet.
    """
    idea = await repository.get_idea(idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail=f"Idea not found: {idea_id}")

    if idea.mode == ProjectMode.NEW:
        raise HTTPException(
            status_code=400,
            detail="Project analysis not available for NEW mode ideas",
        )

    analysis = await repository.get_project_analysis(idea_id)
    return analysis


@router.get("/{idea_id}/status", response_model=PipelineStatusResponse)
async def get_pipeline_status(idea_id: str) -> PipelineStatusResponse:
    """Get pipeline status for an idea."""
    idea = await repository.get_idea(idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail=f"Idea not found: {idea_id}")

    history = await repository.get_transitions(idea_id)

    # Determine if we can advance
    can_advance = idea.current_status == Status.COMPLETED or (
        idea.current_stage == Stage.INPUT and idea.current_status == Status.PENDING
    )

    # Determine next action
    next_action = None
    if idea.current_stage == Stage.INPUT and idea.current_status == Status.PENDING:
        next_action = "POST /api/ideas/{id}/start"
    elif idea.current_status == Status.COMPLETED:
        next_action = "POST /api/ideas/{id}/continue"
    elif idea.current_status == Status.AWAITING_REVIEW:
        next_action = "POST /api/reviews/{id}"
    elif idea.current_status == Status.FAILED:
        next_action = "POST /api/ideas/{id}/retry"

    return PipelineStatusResponse(
        idea_id=idea_id,
        current_stage=idea.current_stage,
        current_status=idea.current_status,
        can_advance=can_advance,
        next_action=next_action,
        history=history,
    )


@router.post("/{idea_id}/start")
async def start_pipeline(idea_id: str, background_tasks: BackgroundTasks) -> dict:
    """Start the pipeline for an idea.

    Runs enrichment and evaluation in the background,
    stopping at the first HIL gate.
    """
    idea = await repository.get_idea(idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail=f"Idea not found: {idea_id}")

    if idea.current_stage != Stage.INPUT:
        raise HTTPException(
            status_code=400,
            detail=f"Pipeline already started. Current stage: {idea.current_stage.value}",
        )

    # Run pipeline in background
    orchestrator = PipelineOrchestrator(repository)
    background_tasks.add_task(orchestrator.run_full_pipeline, idea_id)

    return {
        "message": "Pipeline started",
        "idea_id": idea_id,
        "status_url": f"/api/ideas/{idea_id}/status",
    }


@router.post("/{idea_id}/continue")
async def continue_pipeline(idea_id: str, background_tasks: BackgroundTasks) -> dict:
    """Continue the pipeline from current stage.

    Use after a stage completes to advance to the next stage.
    """
    idea = await repository.get_idea(idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail=f"Idea not found: {idea_id}")

    if idea.current_status not in [Status.COMPLETED, Status.PENDING]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot continue pipeline. Current status: {idea.current_status.value}",
        )

    # Run continuation in background
    orchestrator = PipelineOrchestrator(repository)
    background_tasks.add_task(orchestrator.continue_pipeline, idea_id)

    return {
        "message": "Pipeline continuing",
        "idea_id": idea_id,
        "status_url": f"/api/ideas/{idea_id}/status",
    }


@router.post("/{idea_id}/analyze")
async def run_full_analysis(idea_id: str, background_tasks: BackgroundTasks) -> dict:
    """Run full pipeline (start + continue until HIL gate).

    Convenience endpoint that runs the complete analysis pipeline.
    """
    idea = await repository.get_idea(idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail=f"Idea not found: {idea_id}")

    # Run full pipeline in background
    orchestrator = PipelineOrchestrator(repository)
    background_tasks.add_task(orchestrator.run_full_pipeline, idea_id)

    return {
        "message": "Full analysis started",
        "idea_id": idea_id,
        "status_url": f"/api/ideas/{idea_id}/status",
    }
