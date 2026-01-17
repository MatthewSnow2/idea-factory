"""Pipeline orchestrator for Agentic Idea Factory.

Coordinates stage execution, state transitions, and HIL gates.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from ..core.models import (
    BuildResult,
    EnrichmentResult,
    EvaluationResult,
    Idea,
    ProjectAnalysisResult,
    ProjectMode,
    ReviewDecision,
    ScaffoldingResult,
    Stage,
    Status,
)
from ..core.state_machine import state_machine
from ..db.repository import Repository
from ..integrations.s3_storage import get_s3_service
from ..notifications.service import NotificationContext, NotificationService, get_notification_service
from .building import build_project, BUILD_OUTPUT_DIR
from .enrichment import enrich_idea
from .evaluation import evaluate_idea
from .project_analysis import analyze_project
from .scaffolding import scaffold_idea

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
        self.notification_service = get_notification_service()

    async def _send_hil_notification(self, idea: Idea, gate: int) -> None:
        """Send notifications for a HIL gate.

        Args:
            idea: The idea at the HIL gate
            gate: The gate number (1 = post-evaluation, 2 = post-scaffolding)
        """
        try:
            # Gather context for notification
            enrichment = await self.repo.get_enrichment(idea.id)
            evaluation = await self.repo.get_evaluation(idea.id)
            scaffolding = await self.repo.get_scaffolding(idea.id) if gate == 2 else None

            # Build summaries
            enrichment_summary = None
            if enrichment:
                enrichment_summary = (
                    f"Title: {enrichment.enhanced_title}\n"
                    f"Problem: {enrichment.problem_statement}\n"
                    f"Description: {enrichment.enhanced_description[:200]}..."
                )

            evaluation_summary = None
            if evaluation:
                evaluation_summary = (
                    f"Score: {evaluation.overall_score}/100\n"
                    f"Recommendation: {evaluation.recommendation.value.upper()}\n"
                    f"Rationale: {evaluation.recommendation_rationale}"
                )

            scaffolding_summary = None
            if scaffolding:
                tech_stack = ", ".join(scaffolding.tech_stack[:5])
                scaffolding_summary = (
                    f"Tech Stack: {tech_stack}\n"
                    f"Estimated Hours: {scaffolding.estimated_hours or 'N/A'}\n"
                    f"Blueprint preview: {scaffolding.blueprint_content[:200]}..."
                )

            # Determine stage for notification
            stage = "evaluation" if gate == 1 else "scaffolding"

            context = NotificationContext(
                idea_id=idea.id,
                title=idea.title,
                stage=stage,
                enrichment_summary=enrichment_summary,
                evaluation_summary=evaluation_summary,
                scaffolding_summary=scaffolding_summary,
            )

            result = await self.notification_service.notify_hil_gate(context)
            logger.info(
                f"HIL Gate {gate} notification result: "
                f"email={result.email_sent}, slack={result.slack_sent}"
            )

        except Exception as e:
            # Don't fail the pipeline if notifications fail
            logger.error(f"Failed to send HIL gate {gate} notification: {e}")

    async def start_pipeline(self, idea_id: str) -> PipelineResult:
        """Start the pipeline for an idea.

        For NEW mode: Transitions from INPUT to ENRICHMENT.
        For EXISTING modes: Transitions from INPUT to PROJECT_ANALYSIS.
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

        # Determine target stage based on mode
        if idea.mode == ProjectMode.NEW:
            target_stage = Stage.ENRICHMENT
        else:
            # EXISTING_COMPLETE or EXISTING_ENHANCE
            target_stage = Stage.PROJECT_ANALYSIS

        # Transition to target stage
        result = self.state_machine.transition(
            idea.current_stage, idea.current_status, target_stage, Status.PROCESSING
        )

        if not result.success:
            return PipelineResult(success=False, idea=idea, message=result.error)

        # Update state
        idea = await self.repo.update_idea_state(
            idea_id, target_stage, Status.PROCESSING, triggered_by="pipeline"
        )

        # Run appropriate stage
        if target_stage == Stage.PROJECT_ANALYSIS:
            return await self._run_project_analysis(idea)
        else:
            return await self._run_enrichment(idea)

    async def _run_enrichment(
        self, idea: Idea, analysis: ProjectAnalysisResult | None = None
    ) -> PipelineResult:
        """Run the enrichment stage.

        Args:
            idea: The idea to enrich
            analysis: Optional project analysis result (for existing projects)
        """
        logger.info(f"Running enrichment for idea: {idea.id}")

        try:
            # Execute enrichment (with optional analysis context)
            output = await enrich_idea(idea, analysis)

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

    async def _start_enrichment_with_analysis(self, idea: Idea) -> PipelineResult:
        """Start enrichment stage after project analysis (for existing projects)."""
        # Get analysis result
        analysis = await self.repo.get_project_analysis(idea.id)
        if not analysis:
            return PipelineResult(
                success=False,
                idea=idea,
                message="Cannot enrich: no project analysis result found",
            )

        # Transition to enrichment processing
        result = self.state_machine.transition(
            idea.current_stage, idea.current_status, Stage.ENRICHMENT, Status.PROCESSING
        )

        if not result.success:
            return PipelineResult(success=False, idea=idea, message=result.error)

        idea = await self.repo.update_idea_state(
            idea.id, Stage.ENRICHMENT, Status.PROCESSING, triggered_by="pipeline"
        )

        # Run enrichment with analysis context
        return await self._run_enrichment(idea, analysis)

    async def _run_project_analysis(self, idea: Idea) -> PipelineResult:
        """Run the project analysis stage (for existing projects)."""
        logger.info(f"Running project analysis for idea: {idea.id}")

        try:
            # Execute project analysis
            output = await analyze_project(idea)

            # Save result
            await self.repo.save_project_analysis(idea.id, output)

            # Transition to completed
            idea = await self.repo.update_idea_state(
                idea.id, Stage.PROJECT_ANALYSIS, Status.COMPLETED, triggered_by="pipeline"
            )

            logger.info(f"Project analysis completed for idea: {idea.id}")
            return PipelineResult(
                success=True,
                idea=idea,
                stage=Stage.PROJECT_ANALYSIS,
                status=Status.COMPLETED,
                message=f"Project analysis completed. Found {output.total_files} files. Ready for enrichment.",
            )

        except Exception as e:
            logger.error(f"Project analysis failed for idea {idea.id}: {e}")

            # Transition to failed
            await self.repo.update_idea_state(
                idea.id, Stage.PROJECT_ANALYSIS, Status.FAILED, triggered_by="pipeline"
            )

            return PipelineResult(
                success=False,
                idea=idea,
                stage=Stage.PROJECT_ANALYSIS,
                status=Status.FAILED,
                message=f"Project analysis failed: {e}",
            )

    async def continue_pipeline(self, idea_id: str) -> PipelineResult:
        """Continue the pipeline to the next stage.

        Automatically advances through stages until a HIL gate is reached.
        """
        idea = await self.repo.get_idea(idea_id)
        if not idea:
            return PipelineResult(success=False, message=f"Idea not found: {idea_id}")

        # Check current state and advance
        if (
            idea.current_stage == Stage.PROJECT_ANALYSIS
            and idea.current_status == Status.COMPLETED
        ):
            # After project analysis, start enrichment with analysis context
            return await self._start_enrichment_with_analysis(idea)

        elif idea.current_stage == Stage.ENRICHMENT and idea.current_status == Status.COMPLETED:
            return await self._start_evaluation(idea)

        elif idea.current_stage == Stage.EVALUATION and idea.current_status == Status.COMPLETED:
            # HIL gate 1 - requires human review after evaluation
            idea = await self.repo.update_idea_state(
                idea.id, Stage.HUMAN_REVIEW, Status.AWAITING_REVIEW, triggered_by="pipeline"
            )

            # Send notifications for HIL gate 1
            await self._send_hil_notification(idea, gate=1)

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

        elif idea.current_stage == Stage.SCAFFOLDING and idea.current_status == Status.COMPLETED:
            # HIL gate 2 - requires human review before building
            idea = await self.repo.update_idea_state(
                idea.id, Stage.HUMAN_REVIEW, Status.AWAITING_REVIEW, triggered_by="pipeline"
            )

            # Send notifications for HIL gate 2
            await self._send_hil_notification(idea, gate=2)

            return PipelineResult(
                success=True,
                idea=idea,
                stage=Stage.HUMAN_REVIEW,
                status=Status.AWAITING_REVIEW,
                message="Scaffolding complete. Awaiting human review before building.",
                requires_review=True,
            )

        elif idea.current_stage == Stage.BUILDING and idea.current_status == Status.COMPLETED:
            # Transition to completed
            idea = await self.repo.update_idea_state(
                idea.id, Stage.COMPLETED, Status.COMPLETED, triggered_by="pipeline"
            )
            return PipelineResult(
                success=True,
                idea=idea,
                stage=Stage.COMPLETED,
                status=Status.COMPLETED,
                message="Pipeline completed successfully!",
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

        # For approval, determine which stage to advance to
        if decision == ReviewDecision.APPROVE:
            # Check if we have scaffolding result to determine which HIL gate
            scaffolding = await self.repo.get_scaffolding(idea_id)
            if scaffolding:
                # Second HIL gate (post-scaffolding) - advance to building
                return await self._start_building(idea)
            else:
                # First HIL gate (post-evaluation) - advance to scaffolding
                return await self._start_scaffolding(idea)

        # Update state for non-approval decisions
        idea = await self.repo.update_idea_state(
            idea_id, transition.new_stage, transition.new_status, triggered_by=reviewer
        )

        # Determine message for non-approval decisions
        if decision == ReviewDecision.REFINE:
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

    async def _start_scaffolding(self, idea: Idea) -> PipelineResult:
        """Start the scaffolding stage."""
        # Get enrichment and evaluation results
        enrichment = await self.repo.get_enrichment(idea.id)
        evaluation = await self.repo.get_evaluation(idea.id)

        if not enrichment or not evaluation:
            return PipelineResult(
                success=False,
                idea=idea,
                message="Cannot scaffold: missing enrichment or evaluation results",
            )

        # Get analysis for existing projects
        analysis = None
        if idea.mode != ProjectMode.NEW:
            analysis = await self.repo.get_project_analysis(idea.id)

        # Transition to scaffolding processing
        result = self.state_machine.transition(
            idea.current_stage, idea.current_status, Stage.SCAFFOLDING, Status.PROCESSING
        )

        if not result.success:
            return PipelineResult(success=False, idea=idea, message=result.error)

        idea = await self.repo.update_idea_state(
            idea.id, Stage.SCAFFOLDING, Status.PROCESSING, triggered_by="pipeline"
        )

        return await self._run_scaffolding(idea, enrichment, evaluation, analysis)

    async def _run_scaffolding(
        self,
        idea: Idea,
        enrichment: EnrichmentResult,
        evaluation: EvaluationResult,
        analysis: ProjectAnalysisResult | None = None,
    ) -> PipelineResult:
        """Run the scaffolding stage.

        Args:
            idea: The idea to scaffold
            enrichment: Enrichment result
            evaluation: Evaluation result
            analysis: Optional project analysis result (for existing projects)
        """
        logger.info(f"Running scaffolding for idea: {idea.id}")

        try:
            # Execute scaffolding (with optional analysis context)
            output = await scaffold_idea(idea, enrichment, evaluation, analysis)

            # Save result
            await self.repo.save_scaffolding(idea.id, output)

            # Transition to completed
            idea = await self.repo.update_idea_state(
                idea.id, Stage.SCAFFOLDING, Status.COMPLETED, triggered_by="pipeline"
            )

            logger.info(f"Scaffolding completed for idea: {idea.id}")
            return PipelineResult(
                success=True,
                idea=idea,
                stage=Stage.SCAFFOLDING,
                status=Status.COMPLETED,
                message="Scaffolding completed. Project blueprint generated.",
            )

        except Exception as e:
            logger.error(f"Scaffolding failed for idea {idea.id}: {e}")

            # Transition to failed
            await self.repo.update_idea_state(
                idea.id, Stage.SCAFFOLDING, Status.FAILED, triggered_by="pipeline"
            )

            return PipelineResult(
                success=False,
                idea=idea,
                stage=Stage.SCAFFOLDING,
                status=Status.FAILED,
                message=f"Scaffolding failed: {e}",
            )

    async def _start_building(self, idea: Idea) -> PipelineResult:
        """Start the building stage."""
        # Get enrichment and scaffolding results
        enrichment = await self.repo.get_enrichment(idea.id)
        scaffolding = await self.repo.get_scaffolding(idea.id)

        if not enrichment or not scaffolding:
            return PipelineResult(
                success=False,
                idea=idea,
                message="Cannot build: missing enrichment or scaffolding results",
            )

        # Transition to building processing
        result = self.state_machine.transition(
            idea.current_stage, idea.current_status, Stage.BUILDING, Status.PROCESSING
        )

        if not result.success:
            return PipelineResult(success=False, idea=idea, message=result.error)

        idea = await self.repo.update_idea_state(
            idea.id, Stage.BUILDING, Status.PROCESSING, triggered_by="pipeline"
        )

        return await self._run_building(idea, enrichment, scaffolding)

    async def _run_building(
        self,
        idea: Idea,
        enrichment: EnrichmentResult,
        scaffolding: ScaffoldingResult,
    ) -> PipelineResult:
        """Run the building stage."""
        logger.info(f"Running building for idea: {idea.id}")
        started_at = datetime.utcnow()

        try:
            # Execute building (pass idea for mode detection)
            output = await build_project(idea.id, enrichment, scaffolding, idea)

            # Save result
            await self.repo.save_build(idea.id, output, started_at)

            # Upload to S3 if build succeeded
            download_url = None
            if output.outcome in ("success", "partial"):
                download_url = await self._upload_to_s3(idea, enrichment)

            # Transition to completed
            idea = await self.repo.update_idea_state(
                idea.id, Stage.BUILDING, Status.COMPLETED, triggered_by="pipeline"
            )

            message = f"Build completed: {len(output.artifacts)} files generated ({output.outcome})"
            if download_url:
                message += f" - Download: {download_url}"

            logger.info(f"Building completed for idea: {idea.id}")
            return PipelineResult(
                success=True,
                idea=idea,
                stage=Stage.BUILDING,
                status=Status.COMPLETED,
                message=message,
            )

        except Exception as e:
            logger.error(f"Building failed for idea {idea.id}: {e}")

            # Transition to failed
            await self.repo.update_idea_state(
                idea.id, Stage.BUILDING, Status.FAILED, triggered_by="pipeline"
            )

            return PipelineResult(
                success=False,
                idea=idea,
                stage=Stage.BUILDING,
                status=Status.FAILED,
                message=f"Building failed: {e}",
            )

    async def _upload_to_s3(self, idea: Idea, enrichment: EnrichmentResult) -> str | None:
        """Upload build output to S3.

        Returns the presigned download URL or None if upload failed.
        """
        try:
            s3_service = get_s3_service()

            # Get project directory
            project_dir = BUILD_OUTPUT_DIR / idea.id
            if not project_dir.exists():
                logger.warning(f"Project directory not found for upload: {project_dir}")
                return None

            # Create zip name from title
            safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in enrichment.enhanced_title)
            safe_title = safe_title[:50]  # Limit length
            zip_name = f"{safe_title}-{idea.id[:8]}"

            # Upload as zip to S3
            result = s3_service.upload_directory_as_zip(project_dir, zip_name)
            download_url = result["download_url"]
            s3_key = result["key"]

            # Update build record with S3 info
            await self.repo.update_build_storage_info(idea.id, download_url, s3_key)

            logger.info(f"Uploaded build to S3: {s3_key}")
            return download_url

        except Exception as e:
            logger.error(f"S3 upload failed for idea {idea.id}: {e}")
            return None

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
