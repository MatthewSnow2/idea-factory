"""Database repository for Agentic Idea Factory.

Provides async data access layer using aiosqlite.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiosqlite

from ..core.models import (
    EnrichmentOutput,
    EnrichmentResult,
    EvaluationOutput,
    EvaluationResult,
    HumanReview,
    Idea,
    IdeaInput,
    ReviewDecision,
    Stage,
    StateTransition,
    Status,
)

DB_PATH = Path(__file__).parent.parent.parent / "data" / "idea-factory.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Repository:
    """Async database repository."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Connect to database and initialize schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row

        # Initialize schema
        schema_sql = SCHEMA_PATH.read_text()
        await self._db.executescript(schema_sql)
        await self._db.commit()

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        """Get database connection."""
        if not self._db:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._db

    # =========================================================================
    # Ideas
    # =========================================================================

    async def create_idea(self, input_data: IdeaInput) -> Idea:
        """Create a new idea."""
        idea_id = str(uuid4())
        now = datetime.utcnow().isoformat()

        await self.db.execute(
            """
            INSERT INTO ideas (id, title, raw_content, tags, current_stage, current_status, submitted_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                idea_id,
                input_data.title,
                input_data.raw_content,
                json.dumps(input_data.tags),
                Stage.INPUT.value,
                Status.PENDING.value,
                now,
                now,
            ),
        )
        await self.db.commit()

        return Idea(
            id=idea_id,
            title=input_data.title,
            raw_content=input_data.raw_content,
            tags=input_data.tags,
            current_stage=Stage.INPUT,
            current_status=Status.PENDING,
            submitted_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
        )

    async def get_idea(self, idea_id: str) -> Idea | None:
        """Get idea by ID."""
        async with self.db.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return self._row_to_idea(row)

    async def list_ideas(
        self,
        stage: Stage | None = None,
        status: Status | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Idea]:
        """List ideas with optional filtering."""
        query = "SELECT * FROM ideas WHERE 1=1"
        params: list[Any] = []

        if stage:
            query += " AND current_stage = ?"
            params.append(stage.value)
        if status:
            query += " AND current_status = ?"
            params.append(status.value)

        query += " ORDER BY submitted_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_idea(row) for row in rows]

    async def update_idea_state(
        self, idea_id: str, stage: Stage, status: Status, triggered_by: str = "system"
    ) -> Idea | None:
        """Update idea's stage and status with audit trail."""
        idea = await self.get_idea(idea_id)
        if not idea:
            return None

        now = datetime.utcnow().isoformat()

        # Update idea
        await self.db.execute(
            """
            UPDATE ideas SET current_stage = ?, current_status = ?, updated_at = ?
            WHERE id = ?
            """,
            (stage.value, status.value, now, idea_id),
        )

        # Record transition
        await self.db.execute(
            """
            INSERT INTO state_transitions (id, idea_id, from_stage, from_status, to_stage, to_status, triggered_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                idea_id,
                idea.current_stage.value,
                idea.current_status.value,
                stage.value,
                status.value,
                triggered_by,
                now,
            ),
        )
        await self.db.commit()

        return await self.get_idea(idea_id)

    def _row_to_idea(self, row: aiosqlite.Row) -> Idea:
        """Convert database row to Idea model."""
        return Idea(
            id=row["id"],
            title=row["title"],
            raw_content=row["raw_content"],
            tags=json.loads(row["tags"]),
            current_stage=Stage(row["current_stage"]),
            current_status=Status(row["current_status"]),
            submitted_at=datetime.fromisoformat(row["submitted_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    # =========================================================================
    # Enrichment Results
    # =========================================================================

    async def save_enrichment(self, idea_id: str, output: EnrichmentOutput) -> EnrichmentResult:
        """Save enrichment result."""
        now = datetime.utcnow().isoformat()

        await self.db.execute(
            """
            INSERT OR REPLACE INTO enrichment_results
            (idea_id, enhanced_title, enhanced_description, problem_statement, potential_solutions, market_context, enriched_at, enriched_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                idea_id,
                output.enhanced_title,
                output.enhanced_description,
                output.problem_statement,
                json.dumps(output.potential_solutions),
                output.market_context,
                now,
                "gemini-1.5-flash",
            ),
        )
        await self.db.commit()

        return EnrichmentResult(
            idea_id=idea_id,
            enhanced_title=output.enhanced_title,
            enhanced_description=output.enhanced_description,
            problem_statement=output.problem_statement,
            potential_solutions=output.potential_solutions,
            market_context=output.market_context,
            enriched_at=datetime.fromisoformat(now),
            enriched_by="gemini-1.5-flash",
        )

    async def get_enrichment(self, idea_id: str) -> EnrichmentResult | None:
        """Get enrichment result for an idea."""
        async with self.db.execute(
            "SELECT * FROM enrichment_results WHERE idea_id = ?", (idea_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return EnrichmentResult(
                idea_id=row["idea_id"],
                enhanced_title=row["enhanced_title"],
                enhanced_description=row["enhanced_description"],
                problem_statement=row["problem_statement"],
                potential_solutions=json.loads(row["potential_solutions"]),
                market_context=row["market_context"],
                enriched_at=datetime.fromisoformat(row["enriched_at"]),
                enriched_by=row["enriched_by"],
            )

    # =========================================================================
    # Evaluation Results
    # =========================================================================

    async def save_evaluation(self, idea_id: str, output: EvaluationOutput) -> EvaluationResult:
        """Save evaluation result."""
        now = datetime.utcnow().isoformat()

        await self.db.execute(
            """
            INSERT OR REPLACE INTO evaluation_results
            (idea_id, jtbd_analysis, disruption_potential, disruption_score, capabilities_fit,
             recommendation, recommendation_rationale, key_risks, case_study_matches, overall_score,
             evaluated_at, evaluated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                idea_id,
                output.jtbd_analysis,
                output.disruption_potential,
                output.scores.disruption_score,
                output.capabilities_fit.value,
                output.recommendation.value,
                output.recommendation_rationale,
                json.dumps(output.key_risks),
                json.dumps(output.case_study_matches),
                output.scores.overall_score,
                now,
                "christensen-mcp",
            ),
        )
        await self.db.commit()

        return EvaluationResult(
            idea_id=idea_id,
            jtbd_analysis=output.jtbd_analysis,
            disruption_potential=output.disruption_potential,
            disruption_score=output.scores.disruption_score,
            capabilities_fit=output.capabilities_fit,
            recommendation=output.recommendation,
            recommendation_rationale=output.recommendation_rationale,
            key_risks=output.key_risks,
            case_study_matches=output.case_study_matches,
            overall_score=output.scores.overall_score,
            evaluated_at=datetime.fromisoformat(now),
            evaluated_by="christensen-mcp",
        )

    async def get_evaluation(self, idea_id: str) -> EvaluationResult | None:
        """Get evaluation result for an idea."""
        async with self.db.execute(
            "SELECT * FROM evaluation_results WHERE idea_id = ?", (idea_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return EvaluationResult(
                idea_id=row["idea_id"],
                jtbd_analysis=row["jtbd_analysis"],
                disruption_potential=row["disruption_potential"],
                disruption_score=row["disruption_score"],
                capabilities_fit=row["capabilities_fit"],
                recommendation=row["recommendation"],
                recommendation_rationale=row["recommendation_rationale"],
                key_risks=json.loads(row["key_risks"]),
                case_study_matches=json.loads(row["case_study_matches"]),
                overall_score=row["overall_score"],
                evaluated_at=datetime.fromisoformat(row["evaluated_at"]),
                evaluated_by=row["evaluated_by"],
            )

    # =========================================================================
    # Human Reviews
    # =========================================================================

    async def save_review(
        self,
        idea_id: str,
        stage: Stage,
        decision: ReviewDecision,
        rationale: str | None = None,
        reviewer: str = "human",
    ) -> HumanReview:
        """Save human review decision."""
        review_id = str(uuid4())
        now = datetime.utcnow().isoformat()

        await self.db.execute(
            """
            INSERT INTO human_reviews (id, idea_id, stage, decision, decision_rationale, reviewer, reviewed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (review_id, idea_id, stage.value, decision.value, rationale, reviewer, now),
        )
        await self.db.commit()

        return HumanReview(
            id=review_id,
            idea_id=idea_id,
            stage=stage,
            decision=decision,
            decision_rationale=rationale,
            reviewer=reviewer,
            reviewed_at=datetime.fromisoformat(now),
        )

    async def get_reviews(self, idea_id: str) -> list[HumanReview]:
        """Get all reviews for an idea."""
        async with self.db.execute(
            "SELECT * FROM human_reviews WHERE idea_id = ? ORDER BY reviewed_at", (idea_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                HumanReview(
                    id=row["id"],
                    idea_id=row["idea_id"],
                    stage=Stage(row["stage"]),
                    decision=ReviewDecision(row["decision"]),
                    decision_rationale=row["decision_rationale"],
                    reviewer=row["reviewer"],
                    reviewed_at=datetime.fromisoformat(row["reviewed_at"]),
                )
                for row in rows
            ]

    # =========================================================================
    # State Transitions
    # =========================================================================

    async def get_transitions(self, idea_id: str) -> list[StateTransition]:
        """Get state transition history for an idea."""
        async with self.db.execute(
            "SELECT * FROM state_transitions WHERE idea_id = ? ORDER BY created_at", (idea_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                StateTransition(
                    id=row["id"],
                    idea_id=row["idea_id"],
                    from_stage=Stage(row["from_stage"]),
                    from_status=Status(row["from_status"]),
                    to_stage=Stage(row["to_stage"]),
                    to_status=Status(row["to_status"]),
                    triggered_by=row["triggered_by"],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else None,
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                for row in rows
            ]

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_stage_counts(self) -> dict[str, int]:
        """Get count of ideas by stage."""
        async with self.db.execute(
            "SELECT current_stage, COUNT(*) as count FROM ideas GROUP BY current_stage"
        ) as cursor:
            rows = await cursor.fetchall()
            return {row["current_stage"]: row["count"] for row in rows}


# Singleton instance
repository = Repository()
