"""State machine for pipeline stage transitions.

Defines valid transitions and enforces pipeline rules.
"""

from dataclasses import dataclass

from .models import ProjectMode, ReviewDecision, Stage, Status


@dataclass(frozen=True)
class StateKey:
    """Hashable state key for transition lookup."""

    stage: Stage
    status: Status


@dataclass
class TransitionResult:
    """Result of a state transition attempt."""

    success: bool
    new_stage: Stage | None = None
    new_status: Status | None = None
    error: str | None = None


# Valid transitions: (from_stage, from_status) -> (to_stage, to_status)
VALID_TRANSITIONS: dict[StateKey, list[StateKey]] = {
    # INPUT stage - can go to ENRICHMENT (new) or PROJECT_ANALYSIS (existing)
    StateKey(Stage.INPUT, Status.PENDING): [
        StateKey(Stage.ENRICHMENT, Status.PROCESSING),  # NEW mode
        StateKey(Stage.PROJECT_ANALYSIS, Status.PROCESSING),  # EXISTING modes
    ],
    # PROJECT_ANALYSIS stage (for existing projects)
    StateKey(Stage.PROJECT_ANALYSIS, Status.PROCESSING): [
        StateKey(Stage.PROJECT_ANALYSIS, Status.COMPLETED),
        StateKey(Stage.PROJECT_ANALYSIS, Status.FAILED),
    ],
    StateKey(Stage.PROJECT_ANALYSIS, Status.COMPLETED): [
        StateKey(Stage.ENRICHMENT, Status.PROCESSING),
    ],
    StateKey(Stage.PROJECT_ANALYSIS, Status.FAILED): [
        StateKey(Stage.PROJECT_ANALYSIS, Status.PROCESSING),  # Retry
        StateKey(Stage.ARCHIVED, Status.COMPLETED),
    ],
    # ENRICHMENT stage
    StateKey(Stage.ENRICHMENT, Status.PROCESSING): [
        StateKey(Stage.ENRICHMENT, Status.COMPLETED),
        StateKey(Stage.ENRICHMENT, Status.FAILED),
    ],
    StateKey(Stage.ENRICHMENT, Status.COMPLETED): [
        StateKey(Stage.EVALUATION, Status.PROCESSING),
    ],
    StateKey(Stage.ENRICHMENT, Status.FAILED): [
        StateKey(Stage.ENRICHMENT, Status.PROCESSING),  # Retry
        StateKey(Stage.ARCHIVED, Status.COMPLETED),
    ],
    # EVALUATION stage
    StateKey(Stage.EVALUATION, Status.PROCESSING): [
        StateKey(Stage.EVALUATION, Status.COMPLETED),
        StateKey(Stage.EVALUATION, Status.FAILED),
    ],
    StateKey(Stage.EVALUATION, Status.COMPLETED): [
        StateKey(Stage.HUMAN_REVIEW, Status.AWAITING_REVIEW),
    ],
    StateKey(Stage.EVALUATION, Status.FAILED): [
        StateKey(Stage.EVALUATION, Status.PROCESSING),  # Retry
        StateKey(Stage.ARCHIVED, Status.COMPLETED),
    ],
    # HUMAN_REVIEW stage (post-evaluation or post-scaffolding)
    StateKey(Stage.HUMAN_REVIEW, Status.AWAITING_REVIEW): [
        StateKey(Stage.SCAFFOLDING, Status.PROCESSING),  # approve (first HIL gate)
        StateKey(Stage.BUILDING, Status.PROCESSING),  # approve (second HIL gate)
        StateKey(Stage.ENRICHMENT, Status.PROCESSING),  # refine
        StateKey(Stage.ARCHIVED, Status.COMPLETED),  # reject
        StateKey(Stage.HUMAN_REVIEW, Status.PAUSED),  # defer
    ],
    StateKey(Stage.HUMAN_REVIEW, Status.PAUSED): [
        StateKey(Stage.HUMAN_REVIEW, Status.AWAITING_REVIEW),  # Resume
    ],
    # SCAFFOLDING stage
    StateKey(Stage.SCAFFOLDING, Status.PROCESSING): [
        StateKey(Stage.SCAFFOLDING, Status.COMPLETED),
        StateKey(Stage.SCAFFOLDING, Status.FAILED),
    ],
    StateKey(Stage.SCAFFOLDING, Status.COMPLETED): [
        StateKey(Stage.HUMAN_REVIEW, Status.AWAITING_REVIEW),  # Second HIL gate
    ],
    StateKey(Stage.SCAFFOLDING, Status.FAILED): [
        StateKey(Stage.SCAFFOLDING, Status.PROCESSING),  # Retry
        StateKey(Stage.ARCHIVED, Status.COMPLETED),
    ],
    # BUILDING stage
    StateKey(Stage.BUILDING, Status.PROCESSING): [
        StateKey(Stage.BUILDING, Status.COMPLETED),
        StateKey(Stage.BUILDING, Status.FAILED),
    ],
    StateKey(Stage.BUILDING, Status.COMPLETED): [
        StateKey(Stage.COMPLETED, Status.COMPLETED),
    ],
    StateKey(Stage.BUILDING, Status.FAILED): [
        StateKey(Stage.BUILDING, Status.PROCESSING),  # Retry
        StateKey(Stage.ARCHIVED, Status.COMPLETED),
    ],
}

# Stages that require human review before advancing
HIL_GATE_STAGES = {Stage.EVALUATION, Stage.SCAFFOLDING}


class StateMachine:
    """Pipeline state machine for managing idea progression."""

    def __init__(self) -> None:
        self.transitions = VALID_TRANSITIONS

    def can_transition(
        self, from_stage: Stage, from_status: Status, to_stage: Stage, to_status: Status
    ) -> bool:
        """Check if a transition is valid."""
        from_key = StateKey(from_stage, from_status)
        to_key = StateKey(to_stage, to_status)

        valid_targets = self.transitions.get(from_key, [])
        return to_key in valid_targets

    def get_valid_transitions(self, stage: Stage, status: Status) -> list[StateKey]:
        """Get all valid transitions from current state."""
        from_key = StateKey(stage, status)
        return self.transitions.get(from_key, [])

    def transition(
        self, from_stage: Stage, from_status: Status, to_stage: Stage, to_status: Status
    ) -> TransitionResult:
        """Attempt a state transition."""
        if not self.can_transition(from_stage, from_status, to_stage, to_status):
            valid = self.get_valid_transitions(from_stage, from_status)
            valid_str = ", ".join(f"({s.stage.value}, {s.status.value})" for s in valid)
            return TransitionResult(
                success=False,
                error=f"Invalid transition from ({from_stage.value}, {from_status.value}) "
                f"to ({to_stage.value}, {to_status.value}). "
                f"Valid transitions: [{valid_str}]",
            )

        return TransitionResult(success=True, new_stage=to_stage, new_status=to_status)

    def apply_review_decision(
        self, current_stage: Stage, decision: ReviewDecision
    ) -> TransitionResult:
        """Apply a human review decision and return the resulting transition."""
        if current_stage != Stage.HUMAN_REVIEW:
            return TransitionResult(
                success=False, error=f"Cannot apply review decision in stage {current_stage.value}"
            )

        # Map decisions to target states
        decision_map: dict[ReviewDecision, StateKey] = {
            ReviewDecision.APPROVE: StateKey(
                Stage.SCAFFOLDING
                if current_stage == Stage.HUMAN_REVIEW
                else Stage.BUILDING,  # Context-dependent
                Status.PROCESSING,
            ),
            ReviewDecision.REFINE: StateKey(Stage.ENRICHMENT, Status.PROCESSING),
            ReviewDecision.REJECT: StateKey(Stage.ARCHIVED, Status.COMPLETED),
            ReviewDecision.DEFER: StateKey(Stage.HUMAN_REVIEW, Status.PAUSED),
        }

        target = decision_map[decision]
        return self.transition(
            Stage.HUMAN_REVIEW, Status.AWAITING_REVIEW, target.stage, target.status
        )

    def requires_hil_gate(self, stage: Stage) -> bool:
        """Check if stage requires human review before advancing."""
        return stage in HIL_GATE_STAGES

    def get_next_stage(
        self, current_stage: Stage, mode: ProjectMode = ProjectMode.NEW
    ) -> Stage | None:
        """Get the next stage in the pipeline (for auto-progression).

        Args:
            current_stage: Current pipeline stage
            mode: Project mode (NEW or EXISTING_*)

        Returns:
            Next stage or None if at end of pipeline
        """
        if mode == ProjectMode.NEW:
            stage_order = [
                Stage.INPUT,
                Stage.ENRICHMENT,
                Stage.EVALUATION,
                Stage.HUMAN_REVIEW,
                Stage.SCAFFOLDING,
                Stage.HUMAN_REVIEW,  # Second HIL gate
                Stage.BUILDING,
                Stage.COMPLETED,
            ]
        else:
            # EXISTING_COMPLETE or EXISTING_ENHANCE
            stage_order = [
                Stage.INPUT,
                Stage.PROJECT_ANALYSIS,
                Stage.ENRICHMENT,
                Stage.EVALUATION,
                Stage.HUMAN_REVIEW,
                Stage.SCAFFOLDING,
                Stage.HUMAN_REVIEW,  # Second HIL gate
                Stage.BUILDING,
                Stage.COMPLETED,
            ]

        try:
            idx = stage_order.index(current_stage)
            if idx + 1 < len(stage_order):
                return stage_order[idx + 1]
        except ValueError:
            pass

        return None


# Singleton instance
state_machine = StateMachine()
