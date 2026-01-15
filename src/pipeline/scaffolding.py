"""Scaffolding pipeline stage using Claude.

Takes evaluated idea and generates project blueprint,
directory structure, and tech stack recommendations.

For existing projects, generates diff-based blueprints with
file modifications and new file specifications.
"""

import json
import logging
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from ..core.models import (
    EnrichmentResult,
    EvaluationResult,
    FileModification,
    Idea,
    NewFileSpec,
    ProjectAnalysisResult,
    ProjectMode,
    ScaffoldingOutput,
)

# Load shared env first, then local can override
shared_env = Path.home() / ".env.shared"
if shared_env.exists():
    load_dotenv(shared_env)
load_dotenv()
logger = logging.getLogger(__name__)

# Initialize Anthropic client
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

BLUEPRINT_PROMPT = """You are an expert software architect. Create a project blueprint for:

**{title}**

{description}

Problem: {problem_statement}

Write a concise markdown blueprint (500-800 words) covering:
1. Architecture overview
2. Key components
3. Tech stack choices
4. Implementation phases

Return ONLY the markdown content, no code blocks wrapping it.
"""

STRUCTURE_PROMPT = """For a {tech_primary} project called "{title}", generate a JSON project structure.

Return ONLY valid JSON with this exact format:
{{
  "src": ["src/app.ts", "src/config/index.ts"],
  "tests": ["tests/app.test.ts"],
  "docs": ["docs/README.md"],
  "config": ["package.json", "tsconfig.json"],
  "tech_stack": ["Node.js", "TypeScript"],
  "estimated_hours": 40
}}

Keep the file lists short (5-8 files per category max).
"""

EXISTING_PROJECT_BLUEPRINT_PROMPT = """You are an expert software architect. Create an enhancement/completion blueprint for an EXISTING project.

**Project**: {project_name}
**Goal**: {title}
**Description**: {description}

EXISTING PROJECT CONTEXT:
- Tech Stack: {tech_stack}
- Architecture Patterns: {patterns}
- Entry Points: {entry_points}

{mode_specific_context}

Write a concise markdown blueprint (500-800 words) covering:
1. How this integrates with existing architecture
2. Files to modify (and how)
3. New files to add
4. Files to preserve (not touch)
5. Implementation approach
6. Testing strategy

Focus on INTEGRATION with existing code, not starting from scratch.

Return ONLY the markdown content, no code blocks wrapping it.
"""

EXISTING_PROJECT_STRUCTURE_PROMPT = """For the existing {tech_primary} project "{project_name}", generate a JSON change specification.

GOAL: {title}
DESCRIPTION: {description}

EXISTING STRUCTURE:
{existing_structure}

Return ONLY valid JSON with this exact format:
{{
  "file_modifications": [
    {{
      "file_path": "src/existing.ts",
      "modification_type": "patch",
      "content": "Description of changes to make",
      "rationale": "Why this change is needed"
    }}
  ],
  "new_files": [
    {{
      "file_path": "src/new-feature.ts",
      "purpose": "What this new file does",
      "integrates_with": ["src/existing.ts", "src/app.ts"]
    }}
  ],
  "preserved_files": ["src/core.ts", "config/settings.json"],
  "tech_stack": ["existing", "plus", "new"],
  "estimated_hours": 20
}}

modification_type can be: "patch" (add/change), "replace" (full rewrite), "append" (add to end), "insert" (add at specific location)

Keep modifications minimal and focused. Only modify what's necessary.
"""


async def scaffold_idea(
    idea: Idea,
    enrichment: EnrichmentResult,
    evaluation: EvaluationResult,
    analysis: ProjectAnalysisResult | None = None,
) -> ScaffoldingOutput:
    """Generate project scaffold for an approved idea.

    For NEW projects:
        Uses two separate API calls for reliability:
        1. Generate blueprint (plain text)
        2. Generate structure (JSON)

    For EXISTING projects:
        Uses context-aware prompts to generate:
        1. Integration-focused blueprint
        2. Diff-based change specification

    Args:
        idea: The original idea
        enrichment: The enrichment result
        evaluation: The evaluation result
        analysis: Optional project analysis result (for existing projects)

    Returns:
        ScaffoldingOutput with project blueprint and structure

    Raises:
        ValueError: If scaffolding fails
    """
    logger.info(f"Starting scaffolding for idea: {idea.id}")

    try:
        if idea.mode == ProjectMode.NEW or not analysis:
            # New project: use standard scaffolding
            return await _scaffold_new_project(idea, enrichment)
        else:
            # Existing project: use diff-based scaffolding
            return await _scaffold_existing_project(idea, enrichment, analysis)

    except Exception as e:
        logger.error(f"Scaffolding failed: {e}")
        raise ValueError(f"Scaffolding failed: {e}")


async def _scaffold_new_project(
    idea: Idea, enrichment: EnrichmentResult
) -> ScaffoldingOutput:
    """Generate scaffold for a new project."""
    # Step 1: Generate blueprint (plain markdown)
    blueprint = await _generate_blueprint(enrichment)

    # Step 2: Generate structure (JSON)
    structure_data = await _generate_structure(enrichment.enhanced_title)

    output = ScaffoldingOutput(
        blueprint_content=blueprint,
        project_structure=structure_data.get("project_structure", {
            "src": ["src/index.ts"],
            "tests": ["tests/index.test.ts"],
            "docs": ["docs/README.md"],
            "config": ["package.json"],
        }),
        tech_stack=structure_data.get("tech_stack", ["Node.js", "TypeScript"]),
        estimated_hours=structure_data.get("estimated_hours"),
    )

    logger.info(f"New project scaffolding completed for idea: {idea.id}")
    return output


async def _scaffold_existing_project(
    idea: Idea,
    enrichment: EnrichmentResult,
    analysis: ProjectAnalysisResult,
) -> ScaffoldingOutput:
    """Generate scaffold for an existing project (diff-based)."""
    # Step 1: Generate integration-focused blueprint
    blueprint = await _generate_existing_project_blueprint(idea, enrichment, analysis)

    # Step 2: Generate change specification (JSON)
    change_spec = await _generate_existing_project_structure(idea, enrichment, analysis)

    # Build file modifications list
    file_modifications = [
        FileModification(**mod)
        for mod in change_spec.get("file_modifications", [])
    ]

    # Build new files list
    new_files = [
        NewFileSpec(**spec)
        for spec in change_spec.get("new_files", [])
    ]

    # Get preserved files
    preserved_files = change_spec.get("preserved_files", [])

    # Build project structure from new files
    project_structure = {"src": [], "tests": [], "docs": [], "config": []}
    for new_file in new_files:
        path = new_file.file_path
        if path.startswith("src/"):
            project_structure["src"].append(path)
        elif path.startswith("test"):
            project_structure["tests"].append(path)
        elif path.startswith("doc"):
            project_structure["docs"].append(path)
        else:
            project_structure["config"].append(path)

    output = ScaffoldingOutput(
        blueprint_content=blueprint,
        project_structure=project_structure,
        tech_stack=change_spec.get("tech_stack", analysis.detected_tech_stack),
        estimated_hours=change_spec.get("estimated_hours"),
        file_modifications=file_modifications,
        new_files=new_files,
        preserved_files=preserved_files,
    )

    logger.info(f"Existing project scaffolding completed for idea: {idea.id}")
    return output


async def _generate_blueprint(enrichment: EnrichmentResult) -> str:
    """Generate project blueprint as plain markdown."""
    prompt = BLUEPRINT_PROMPT.format(
        title=enrichment.enhanced_title,
        description=enrichment.enhanced_description,
        problem_statement=enrichment.problem_statement,
    )

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text.strip()


async def _generate_structure(title: str) -> dict:
    """Generate project structure as JSON."""
    prompt = STRUCTURE_PROMPT.format(
        title=title,
        tech_primary="Node.js/TypeScript",
    )

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = message.content[0].text.strip()

    # Clean up if wrapped in code blocks
    if response_text.startswith("```"):
        first_newline = response_text.find("\n")
        if first_newline > 0:
            response_text = response_text[first_newline + 1:]
    if response_text.endswith("```"):
        response_text = response_text[:-3]

    data = json.loads(response_text.strip())

    # Normalize structure
    return {
        "project_structure": {
            "src": data.get("src", []),
            "tests": data.get("tests", []),
            "docs": data.get("docs", []),
            "config": data.get("config", []),
        },
        "tech_stack": data.get("tech_stack", []),
        "estimated_hours": data.get("estimated_hours"),
    }


async def _generate_existing_project_blueprint(
    idea: Idea,
    enrichment: EnrichmentResult,
    analysis: ProjectAnalysisResult,
) -> str:
    """Generate integration-focused blueprint for existing project."""
    # Format patterns
    patterns = ", ".join(p.pattern_name for p in analysis.detected_patterns) or "None detected"

    # Build mode-specific context
    if idea.mode == ProjectMode.EXISTING_COMPLETE:
        gaps_list = "\n".join(
            f"  - [{g.priority}] {g.description} (in {g.location})"
            for g in analysis.completion_gaps[:5]
        )
        mode_context = f"""COMPLETION GAPS TO ADDRESS:
{gaps_list}
Completeness Score: {analysis.completeness_score or 'N/A'}"""
    else:  # EXISTING_ENHANCE
        opps_list = "\n".join(
            f"  - [{o.opportunity_type}] {o.description}"
            for o in analysis.enhancement_opportunities[:5]
        )
        mode_context = f"""ENHANCEMENT OPPORTUNITIES:
{opps_list}
Architecture Quality: {analysis.architecture_quality_score or 'N/A'}"""

    prompt = EXISTING_PROJECT_BLUEPRINT_PROMPT.format(
        project_name=analysis.project_name,
        title=enrichment.enhanced_title,
        description=enrichment.enhanced_description,
        tech_stack=", ".join(analysis.detected_tech_stack) or "Not detected",
        patterns=patterns,
        entry_points=", ".join(analysis.entry_points) or "Not detected",
        mode_specific_context=mode_context,
    )

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text.strip()


async def _generate_existing_project_structure(
    idea: Idea,
    enrichment: EnrichmentResult,
    analysis: ProjectAnalysisResult,
) -> dict:
    """Generate change specification for existing project."""
    # Format existing structure from key files
    existing_structure = "\n".join(
        f"  - {f.path}: {f.purpose}"
        for f in analysis.key_files[:10]
    )

    prompt = EXISTING_PROJECT_STRUCTURE_PROMPT.format(
        tech_primary=", ".join(analysis.detected_tech_stack[:3]) or "Unknown",
        project_name=analysis.project_name,
        title=enrichment.enhanced_title,
        description=enrichment.enhanced_description,
        existing_structure=existing_structure,
    )

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = message.content[0].text.strip()

    # Clean up if wrapped in code blocks
    if response_text.startswith("```"):
        first_newline = response_text.find("\n")
        if first_newline > 0:
            response_text = response_text[first_newline + 1:]
    if response_text.endswith("```"):
        response_text = response_text[:-3]

    return json.loads(response_text.strip())
