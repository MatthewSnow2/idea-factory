"""Pipeline orchestrator for Agentic Idea Factory.

Coordinates stage execution, state transitions, and HIL gates.
"""

import logging
from dataclasses import dataclass
from typing import Callable

from ..core.models import (
    EnrichmentResult,
    EvaluationResult,
    Idea,
    ReviewDecision,
    Stage,
    Status,
)
from ..core.state_machine import state_machine
from ..db.repository import Repository
from .enrichment import enrich_idea
from .evaluation import evaluate_idea

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result of a pipeline operation."""

    success: bool
    idea: Idea | None = None
    stage: Stage | None = None
    status: Status | None = None
    message: str | None = None
    requires_review: bool = False


class PipelineOrchestrator:
    """Orchestrates the idea pipeline stages."""

    def __init__(self, repository: Repository) -> None:
        self.repo = repository
        self.state_machine = state_machine

    async def start_pipeline(self, idea_id: str) -> PipelineResult:
        """Start the pipeline for an idea.

        Transitions from INPUT to ENRICHMENT and begins processing.
        """
        idea = await self.repo.get_idea(idea_id)
        if not idea:
            return PipelineResult(success=False, message=f"Idea not found: {idea_id}")

        if idea.current_stage != Stage.INPUT:
            return PipelineResult(
                success=False,
                idea=idea,
                message=f"Idea not in INPUT stage: {idea.current_stage.value}",
            )

        # Transition to enrichment
        result = self.state_machine.transition(
            idea.current_stage, idea.current_status, Stage.ENRICHMENT, Status.PROCESSING
        )

        if not result.success:
            return PipelineResult(success=False, idea=idea, message=result.error)

        # Update state
        idea = await self.repo.update_idea_state(
            idea_id, Stage.ENRICHMENT, Status.PROCESSING, triggered_by="pipeline"
        )

        # Run enrichment
        return await self._run_enrichment(idea)

    async def _run_enrichment(self, idea: Idea) -> PipelineResult:
        """Run the enrichment stage."""
        logger.info(f"Running enrichment for idea: {idea.id}")

        try:
            # Execute enrichment
            output = await enrich_idea(idea)

            # Save result
            await self.repo.save_enrichment(idea.id, output)

            # Transition to completed
            idea = await self.repo.update_idea_state(
                idea.id, Stage.ENRICHMENT, Status.COMPLETED, triggered_by="pipeline"
            )

            logger.info(f"Enrichment completed for idea: {idea.id}")
            return PipelineResult(
                success=True,
                idea=idea,
                stage=Stage.ENRICHMENT,
                status=Status.COMPLETED,
                message="Enrichment completed. Ready for evaluation.",
            )

        except Exception as e:
            logger.error(f"Enrichment failed for idea {idea.id}: {e}")

            # Transition to failed
            await self.repo.update_idea_state(
                idea.id, Stage.ENRICHMENT, Status.FAILED, triggered_by="pipeline"
            )

            return PipelineResult(
                success=False,
                idea=idea,
                stage=Stage.ENRICHMENT,
                status=Status.FAILED,
                message=f"Enrichment failed: {e}",
            )

    async def continue_pipeline(self, idea_id: str) -> PipelineResult:
        """Continue the pipeline to the next stage.

        Automatically advances through stages until a HIL gate is reached.
        """
        idea = await self.repo.get_idea(idea_id)
        if not idea:
            return PipelineResult(success=False, message=f"Idea not found: {idea_id}")

        # Check current state and advance
        if idea.current_stage == Stage.ENRICHMENT and idea.current_status == Status.COMPLETED:
            return await self._start_evaluation(idea)

        elif idea.current_stage == Stage.EVALUATION and idea.current_status == Status.COMPLETED:
            # HIL gate - requires human review
            idea = await self.repo.update_idea_state(
                idea.id, Stage.HUMAN_REVIEW, Status.AWAITING_REVIEW, triggered_by="pipeline"
            )
            return PipelineResult(
                success=True,
                idea=idea,
                stage=Stage.HUMAN_REVIEW,
                status=Status.AWAITING_REVIEW,
                message="Evaluation complete. Awaiting human review.",
                requires_review=True,
            )

        elif (
            idea.current_stage == Stage.HUMAN_REVIEW
            and idea.current_status == Status.AWAITING_REVIEW
        ):
            return PipelineResult(
                success=True,
                idea=idea,
                stage=Stage.HUMAN_REVIEW,
                status=Status.AWAITING_REVIEW,
                message="Awaiting human review decision.",
                requires_review=True,
            )

        else:
            return PipelineResult(
                success=False,
                idea=idea,
                message=f"Cannot continue from state: ({idea.current_stage.value}, {idea.current_status.value})",
            )

    async def _start_evaluation(self, idea: Idea) -> PipelineResult:
        """Start the evaluation stage."""
        # Get enrichment result
        enrichment = await self.repo.get_enrichment(idea.id)
        if not enrichment:
            return PipelineResult(
                success=False,
                idea=idea,
                message="Cannot evaluate: no enrichment result found",
            )

        # Transition to evaluation processing
        result = self.state_machine.transition(
            idea.current_stage, idea.current_status, Stage.EVALUATION, Status.PROCESSING
        )

        if not result.success:
            return PipelineResult(success=False, idea=idea, message=result.error)

        idea = await self.repo.update_idea_state(
            idea.id, Stage.EVALUATION, Status.PROCESSING, triggered_by="pipeline"
        )

        return await self._run_evaluation(idea, enrichment)

    async def _run_evaluation(
        self, idea: Idea, enrichment: EnrichmentResult
    ) -> PipelineResult:
        """Run the evaluation stage."""
        logger.info(f"Running evaluation for idea: {idea.id}")

        try:
            # Execute evaluation
            output = await evaluate_idea(idea, enrichment)

            # Save result
            await self.repo.save_evaluation(idea.id, output)

            # Transition to completed
            idea = await self.repo.update_idea_state(
                idea.id, Stage.EVALUATION, Status.COMPLETED, triggered_by="pipeline"
            )

            logger.info(f"Evaluation completed for idea: {idea.id}")
            return PipelineResult(
                success=True,
                idea=idea,
                stage=Stage.EVALUATION,
                status=Status.COMPLETED,
                message="Evaluation completed. Advancing to human review.",
            )

        except Exception as e:
            logger.error(f"Evaluation failed for idea {idea.id}: {e}")

            # Transition to failed
            await self.repo.update_idea_state(
                idea.id, Stage.EVALUATION, Status.FAILED, triggered_by="pipeline"
            )

            return PipelineResult(
                success=False,
                idea=idea,
                stage=Stage.EVALUATION,
                status=Status.FAILED,
                message=f"Evaluation failed: {e}",
            )

    async def apply_review(
        self,
        idea_id: str,
        decision: ReviewDecision,
        rationale: str | None = None,
        reviewer: str = "human",
    ) -> PipelineResult:
        """Apply a human review decision.

        Args:
            idea_id: The idea being reviewed
            decision: The review decision
            rationale: Optional explanation
            reviewer: Who made the decision

        Returns:
            PipelineResult with next state
        """
        idea = await self.repo.get_idea(idea_id)
        if not idea:
            return PipelineResult(success=False, message=f"Idea not found: {idea_id}")

        if idea.current_stage != Stage.HUMAN_REVIEW:
            return PipelineResult(
                success=False,
                idea=idea,
                message=f"Idea not in HUMAN_REVIEW stage: {idea.current_stage.value}",
            )

        # Save the review
        await self.repo.save_review(
            idea_id, idea.current_stage, decision, rationale, reviewer
        )

        # Apply the decision through state machine
        transition = self.state_machine.apply_review_decision(
            idea.current_stage, decision
        )

        if not transition.success:
            return PipelineResult(success=False, idea=idea, message=transition.error)

        # Update state
        idea = await self.repo.update_idea_state(
            idea_id, transition.new_stage, transition.new_status, triggered_by=reviewer
        )

        # Determine next action
        if decision == ReviewDecision.APPROVE:
            message = "Approved! Advancing to scaffolding stage."
        elif decision == ReviewDecision.REFINE:
            message = "Sent back for refinement. Restarting enrichment."
        elif decision == ReviewDecision.REJECT:
            message = "Rejected and archived."
        else:  # DEFER
            message = "Deferred. Idea paused for later review."

        return PipelineResult(
            success=True,
            idea=idea,
            stage=transition.new_stage,
            status=transition.new_status,
            message=message,
        )

    async def run_full_pipeline(self, idea_id: str) -> PipelineResult:
        """Run the full pipeline until a HIL gate is reached.

        Automatically chains stages: INPUT → ENRICHMENT → EVALUATION → HUMAN_REVIEW
        """
        # Start pipeline
        result = await self.start_pipeline(idea_id)
        if not result.success:
            return result

        # Continue until we hit a gate or failure
        while result.success and not result.requires_review:
            result = await self.continue_pipeline(idea_id)

        return result
