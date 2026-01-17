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
    ArchitecturePattern,
    BuildOutput,
    BuildResult,
    CompletionGap,
    EnhancementOpportunity,
    EnrichmentOutput,
    EnrichmentResult,
    EvaluationOutput,
    EvaluationResult,
    FileAnalysis,
    FileModification,
    HumanReview,
    Idea,
    IdeaInput,
    NewFileSpec,
    ProjectAnalysisOutput,
    ProjectAnalysisResult,
    ProjectMode,
    ProjectSource,
    ReviewDecision,
    ScaffoldingOutput,
    ScaffoldingResult,
    SourceType,
    Stage,
    StateTransition,
    Status,
    User,
    UserRole,
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
    # Users
    # =========================================================================

    async def create_user(
        self,
        user_id: str,
        email: str,
        name: str | None = None,
        role: str = "collaborator",
    ) -> User:
        """Create a new user."""
        now = datetime.utcnow().isoformat()

        await self.db.execute(
            """
            INSERT INTO users (id, email, name, role, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, email, name, role, now, now),
        )
        await self.db.commit()

        return User(
            id=user_id,
            email=email,
            name=name,
            role=UserRole(role),
            terms_accepted_at=None,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
        )

    async def get_user(self, user_id: str) -> User | None:
        """Get user by ID."""
        async with self.db.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return self._row_to_user(row)

    async def get_user_by_email(self, email: str) -> User | None:
        """Get user by email."""
        async with self.db.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return self._row_to_user(row)

    async def update_user(
        self,
        user_id: str,
        email: str | None = None,
        name: str | None = None,
    ) -> User | None:
        """Update user info."""
        user = await self.get_user(user_id)
        if not user:
            return None

        now = datetime.utcnow().isoformat()
        new_email = email if email is not None else user.email
        new_name = name if name is not None else user.name

        await self.db.execute(
            """
            UPDATE users SET email = ?, name = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_email, new_name, now, user_id),
        )
        await self.db.commit()

        return await self.get_user(user_id)

    async def accept_terms(self, user_id: str) -> User | None:
        """Record user's terms acceptance."""
        user = await self.get_user(user_id)
        if not user:
            return None

        now = datetime.utcnow().isoformat()

        await self.db.execute(
            """
            UPDATE users SET terms_accepted_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, now, user_id),
        )
        await self.db.commit()

        return await self.get_user(user_id)

    async def list_users(self, limit: int = 100, offset: int = 0) -> list[User]:
        """List all users."""
        async with self.db.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_user(row) for row in rows]

    def _row_to_user(self, row: aiosqlite.Row) -> User:
        """Convert database row to User model."""
        return User(
            id=row["id"],
            email=row["email"],
            name=row["name"],
            role=UserRole(row["role"]) if row["role"] else UserRole.COLLABORATOR,
            terms_accepted_at=datetime.fromisoformat(row["terms_accepted_at"]) if row["terms_accepted_at"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    # =========================================================================
    # Ideas
    # =========================================================================

    async def create_idea(self, input_data: IdeaInput, submitted_by: str | None = None) -> Idea:
        """Create a new idea."""
        idea_id = str(uuid4())
        now = datetime.utcnow().isoformat()

        # Serialize project_source if present
        project_source_json = None
        if input_data.project_source:
            project_source_json = json.dumps(input_data.project_source.model_dump())

        # Serialize preferred_tech_stack if present
        preferred_tech_stack_json = None
        if input_data.preferred_tech_stack:
            preferred_tech_stack_json = json.dumps(input_data.preferred_tech_stack)

        await self.db.execute(
            """
            INSERT INTO ideas (id, title, raw_content, tags, current_stage, current_status, submitted_at, updated_at, mode, project_source, preferred_tech_stack, submitted_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                input_data.mode.value,
                project_source_json,
                preferred_tech_stack_json,
                submitted_by,
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
            mode=input_data.mode,
            project_source=input_data.project_source,
            preferred_tech_stack=input_data.preferred_tech_stack,
            submitted_by=submitted_by,
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
        # Parse project_source if present
        project_source = None
        if row["project_source"]:
            source_data = json.loads(row["project_source"])
            project_source = ProjectSource(
                source_type=SourceType(source_data["source_type"]),
                location=source_data["location"],
                branch=source_data.get("branch"),
                subdirectory=source_data.get("subdirectory"),
            )

        # Parse preferred_tech_stack if present
        preferred_tech_stack = None
        if row["preferred_tech_stack"]:
            preferred_tech_stack = json.loads(row["preferred_tech_stack"])

        return Idea(
            id=row["id"],
            title=row["title"],
            raw_content=row["raw_content"],
            tags=json.loads(row["tags"]),
            current_stage=Stage(row["current_stage"]),
            current_status=Status(row["current_status"]),
            submitted_at=datetime.fromisoformat(row["submitted_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            mode=ProjectMode(row["mode"]) if row["mode"] else ProjectMode.NEW,
            project_source=project_source,
            preferred_tech_stack=preferred_tech_stack,
            submitted_by=row["submitted_by"],
        )

    async def list_ideas_by_user(
        self,
        user_id: str,
        stage: Stage | None = None,
        status: Status | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Idea]:
        """List ideas submitted by a specific user."""
        query = "SELECT * FROM ideas WHERE submitted_by = ?"
        params: list[Any] = [user_id]

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
    # Project Analysis Results (for existing projects)
    # =========================================================================

    async def save_project_analysis(
        self, idea_id: str, output: ProjectAnalysisOutput
    ) -> ProjectAnalysisResult:
        """Save project analysis result."""
        now = datetime.utcnow().isoformat()

        await self.db.execute(
            """
            INSERT OR REPLACE INTO project_analysis_results
            (idea_id, project_name, detected_tech_stack, detected_patterns, total_files,
             key_files, entry_points, completion_gaps, completeness_score,
             enhancement_opportunities, architecture_quality_score, readme_summary,
             existing_blueprint, constraints, analyzed_at, analyzed_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                idea_id,
                output.project_name,
                json.dumps(output.detected_tech_stack),
                json.dumps([p.model_dump() for p in output.detected_patterns]),
                output.total_files,
                json.dumps([f.model_dump() for f in output.key_files]),
                json.dumps(output.entry_points),
                json.dumps([g.model_dump() for g in output.completion_gaps]),
                output.completeness_score,
                json.dumps([o.model_dump() for o in output.enhancement_opportunities]),
                output.architecture_quality_score,
                output.readme_summary,
                output.existing_blueprint,
                json.dumps(output.constraints),
                now,
                "claude-sonnet-4",
            ),
        )
        await self.db.commit()

        return ProjectAnalysisResult(
            idea_id=idea_id,
            project_name=output.project_name,
            detected_tech_stack=output.detected_tech_stack,
            detected_patterns=output.detected_patterns,
            total_files=output.total_files,
            key_files=output.key_files,
            entry_points=output.entry_points,
            completion_gaps=output.completion_gaps,
            completeness_score=output.completeness_score,
            enhancement_opportunities=output.enhancement_opportunities,
            architecture_quality_score=output.architecture_quality_score,
            readme_summary=output.readme_summary,
            existing_blueprint=output.existing_blueprint,
            constraints=output.constraints,
            analyzed_at=datetime.fromisoformat(now),
            analyzed_by="claude-sonnet-4",
        )

    async def get_project_analysis(self, idea_id: str) -> ProjectAnalysisResult | None:
        """Get project analysis result for an idea."""
        async with self.db.execute(
            "SELECT * FROM project_analysis_results WHERE idea_id = ?", (idea_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None

            # Parse JSON fields back to models
            patterns_data = json.loads(row["detected_patterns"])
            patterns = [ArchitecturePattern(**p) for p in patterns_data]

            key_files_data = json.loads(row["key_files"])
            key_files = [FileAnalysis(**f) for f in key_files_data]

            gaps_data = json.loads(row["completion_gaps"]) if row["completion_gaps"] else []
            gaps = [CompletionGap(**g) for g in gaps_data]

            opps_data = json.loads(row["enhancement_opportunities"]) if row["enhancement_opportunities"] else []
            opportunities = [EnhancementOpportunity(**o) for o in opps_data]

            return ProjectAnalysisResult(
                idea_id=row["idea_id"],
                project_name=row["project_name"],
                detected_tech_stack=json.loads(row["detected_tech_stack"]),
                detected_patterns=patterns,
                total_files=row["total_files"],
                key_files=key_files,
                entry_points=json.loads(row["entry_points"]),
                completion_gaps=gaps,
                completeness_score=row["completeness_score"],
                enhancement_opportunities=opportunities,
                architecture_quality_score=row["architecture_quality_score"],
                readme_summary=row["readme_summary"],
                existing_blueprint=row["existing_blueprint"],
                constraints=json.loads(row["constraints"]),
                analyzed_at=datetime.fromisoformat(row["analyzed_at"]),
                analyzed_by=row["analyzed_by"],
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
    # Scaffolding Results
    # =========================================================================

    async def save_scaffolding(
        self, idea_id: str, output: ScaffoldingOutput
    ) -> ScaffoldingResult:
        """Save scaffolding result."""
        now = datetime.utcnow().isoformat()

        # Serialize existing project fields if present
        file_mods_json = json.dumps([m.model_dump() for m in output.file_modifications]) if output.file_modifications else None
        new_files_json = json.dumps([f.model_dump() for f in output.new_files]) if output.new_files else None
        preserved_json = json.dumps(output.preserved_files) if output.preserved_files else None

        await self.db.execute(
            """
            INSERT OR REPLACE INTO scaffolding_results
            (idea_id, blueprint_content, project_structure, tech_stack, estimated_hours,
             scaffolded_at, scaffolded_by, file_modifications, new_files, preserved_files)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                idea_id,
                output.blueprint_content,
                json.dumps(output.project_structure),
                json.dumps(output.tech_stack),
                output.estimated_hours,
                now,
                "claude-sonnet-4",
                file_mods_json,
                new_files_json,
                preserved_json,
            ),
        )
        await self.db.commit()

        return ScaffoldingResult(
            idea_id=idea_id,
            blueprint_content=output.blueprint_content,
            project_structure=output.project_structure,
            tech_stack=output.tech_stack,
            estimated_hours=output.estimated_hours,
            scaffolded_at=datetime.fromisoformat(now),
            scaffolded_by="claude-sonnet-4",
            file_modifications=output.file_modifications,
            new_files=output.new_files,
            preserved_files=output.preserved_files,
        )

    async def get_scaffolding(self, idea_id: str) -> ScaffoldingResult | None:
        """Get scaffolding result for an idea."""
        async with self.db.execute(
            "SELECT * FROM scaffolding_results WHERE idea_id = ?", (idea_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None

            # Parse existing project fields if present
            file_modifications = []
            if row["file_modifications"]:
                mods_data = json.loads(row["file_modifications"])
                file_modifications = [FileModification(**m) for m in mods_data]

            new_files = []
            if row["new_files"]:
                files_data = json.loads(row["new_files"])
                new_files = [NewFileSpec(**f) for f in files_data]

            preserved_files = []
            if row["preserved_files"]:
                preserved_files = json.loads(row["preserved_files"])

            return ScaffoldingResult(
                idea_id=row["idea_id"],
                blueprint_content=row["blueprint_content"],
                project_structure=json.loads(row["project_structure"]),
                tech_stack=json.loads(row["tech_stack"]),
                estimated_hours=row["estimated_hours"],
                scaffolded_at=datetime.fromisoformat(row["scaffolded_at"]),
                scaffolded_by=row["scaffolded_by"],
                file_modifications=file_modifications,
                new_files=new_files,
                preserved_files=preserved_files,
            )

    # =========================================================================
    # Build Results
    # =========================================================================

    async def save_build(
        self, idea_id: str, output: BuildOutput, started_at: datetime
    ) -> BuildResult:
        """Save build result."""
        now = datetime.utcnow().isoformat()

        await self.db.execute(
            """
            INSERT OR REPLACE INTO build_results
            (idea_id, github_repo, artifacts, outcome, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                idea_id,
                output.github_repo,
                json.dumps(output.artifacts),
                output.outcome,
                started_at.isoformat(),
                now,
            ),
        )
        await self.db.commit()

        return BuildResult(
            idea_id=idea_id,
            github_repo=output.github_repo,
            artifacts=output.artifacts,
            outcome=output.outcome,
            started_at=started_at,
            completed_at=datetime.fromisoformat(now),
        )

    async def update_build_drive_info(
        self, idea_id: str, drive_url: str, drive_file_id: str
    ) -> BuildResult | None:
        """Update build result with Google Drive info (legacy)."""
        await self.db.execute(
            """
            UPDATE build_results
            SET google_drive_url = ?, google_drive_file_id = ?
            WHERE idea_id = ?
            """,
            (drive_url, drive_file_id, idea_id),
        )
        await self.db.commit()
        return await self.get_build(idea_id)

    async def update_build_storage_info(
        self, idea_id: str, download_url: str, storage_key: str
    ) -> BuildResult | None:
        """Update build result with storage info (S3 or other).

        Reuses the google_drive_* columns for backward compatibility.
        """
        await self.db.execute(
            """
            UPDATE build_results
            SET google_drive_url = ?, google_drive_file_id = ?
            WHERE idea_id = ?
            """,
            (download_url, storage_key, idea_id),
        )
        await self.db.commit()
        return await self.get_build(idea_id)

    async def get_build(self, idea_id: str) -> BuildResult | None:
        """Get build result for an idea."""
        async with self.db.execute(
            "SELECT * FROM build_results WHERE idea_id = ?", (idea_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return BuildResult(
                idea_id=row["idea_id"],
                github_repo=row["github_repo"],
                artifacts=json.loads(row["artifacts"]) if row["artifacts"] else [],
                outcome=row["outcome"],
                started_at=datetime.fromisoformat(row["started_at"]),
                completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
                google_drive_url=row["google_drive_url"] if "google_drive_url" in row.keys() else None,
                google_drive_file_id=row["google_drive_file_id"] if "google_drive_file_id" in row.keys() else None,
            )

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
