"""Human review API routes."""

from fastapi import APIRouter, HTTPException

from ..core.models import HumanReview, HumanReviewInput, ReviewDecision, Stage
from ..db.repository import repository
from ..pipeline.orchestrator import PipelineOrchestrator

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.post("/{idea_id}", response_model=dict)
async def submit_review(idea_id: str, review_input: HumanReviewInput) -> dict:
    """Submit a human review decision for an idea.

    Decisions:
    - approve: Advance to next stage (scaffolding)
    - refine: Send back to enrichment for improvements
    - reject: Archive the idea
    - defer: Pause for later review
    """
    idea = await repository.get_idea(idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail=f"Idea not found: {idea_id}")

    if idea.current_stage != Stage.HUMAN_REVIEW:
        raise HTTPException(
            status_code=400,
            detail=f"Idea not awaiting review. Current stage: {idea.current_stage.value}",
        )

    orchestrator = PipelineOrchestrator(repository)
    result = await orchestrator.apply_review(
        idea_id=idea_id,
        decision=review_input.decision,
        rationale=review_input.decision_rationale,
        reviewer="human",
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    return {
        "message": result.message,
        "idea_id": idea_id,
        "new_stage": result.stage.value if result.stage else None,
        "new_status": result.status.value if result.status else None,
    }


@router.get("/{idea_id}", response_model=list[HumanReview])
async def get_reviews(idea_id: str) -> list[HumanReview]:
    """Get all reviews for an idea."""
    idea = await repository.get_idea(idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail=f"Idea not found: {idea_id}")

    return await repository.get_reviews(idea_id)


@router.get("/pending/count")
async def get_pending_reviews_count() -> dict:
    """Get count of ideas awaiting review."""
    ideas = await repository.list_ideas(
        stage=Stage.HUMAN_REVIEW,
        status=None,  # Any status in review stage
    )

    return {
        "total_pending": len(ideas),
        "ideas": [{"id": i.id, "title": i.title, "status": i.current_status.value} for i in ideas],
    }
