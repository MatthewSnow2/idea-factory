"""Enrichment pipeline stage using Gemini.

Takes raw idea input and produces enhanced description,
problem statement, and market context.
"""

import json
import logging
import os
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv

from ..core.models import EnrichmentOutput, Idea, ProjectAnalysisResult, ProjectMode

# Load shared env first, then local can override
shared_env = Path.home() / ".env.shared"
if shared_env.exists():
    load_dotenv(shared_env)
load_dotenv()
logger = logging.getLogger(__name__)

# Configure Gemini
genai.configure(api_key=os.getenv("GOOGLE_API_KEY", ""))

ENRICHMENT_PROMPT = """You are an expert product analyst and innovation strategist.
Analyze this idea and provide structured enrichment data.

IDEA TITLE: {title}

IDEA DESCRIPTION:
{raw_content}

TAGS: {tags}

Your task is to enhance this idea with deeper analysis. Provide a JSON response with this exact structure:

{{
  "enhanced_title": "<improved, more specific title>",
  "enhanced_description": "<2-3 paragraph comprehensive description of what this idea entails>",
  "problem_statement": "<clear articulation of the problem this solves>",
  "potential_solutions": [
    "<approach 1>",
    "<approach 2>",
    "<approach 3>"
  ],
  "market_context": "<analysis of market opportunity, competitors, and positioning>"
}}

Be specific and analytical. Focus on:
1. Clarifying the core value proposition
2. Identifying the target user/customer
3. Articulating the problem clearly
4. Suggesting concrete implementation approaches
5. Understanding the competitive landscape

Return ONLY valid JSON, no markdown code blocks or explanation.
"""

EXISTING_PROJECT_ENRICHMENT_PROMPT = """You are an expert product analyst and innovation strategist.
Analyze this enhancement/completion idea for an EXISTING project.

IDEA TITLE: {title}

IDEA DESCRIPTION (User's Goals):
{raw_content}

TAGS: {tags}

EXISTING PROJECT CONTEXT:
- Project Name: {project_name}
- Tech Stack: {tech_stack}
- Architecture Patterns: {patterns}
- Detected Entry Points: {entry_points}

{mode_specific_context}

README Summary:
{readme_summary}

Your task is to enhance this idea with context-aware analysis. Provide a JSON response with this exact structure:

{{
  "enhanced_title": "<improved title that references the existing project>",
  "enhanced_description": "<2-3 paragraph description of what this enhancement/completion entails, referencing existing architecture>",
  "problem_statement": "<clear articulation of the problem this solves, in context of the existing project>",
  "potential_solutions": [
    "<approach 1 that integrates with existing patterns>",
    "<approach 2 that builds on existing architecture>",
    "<approach 3 alternative approach>"
  ],
  "market_context": "<value this enhancement adds to the project, competitive positioning>"
}}

Be specific and reference the existing project context. Focus on:
1. How this enhancement fits into the existing architecture
2. What existing patterns to follow
3. Integration points with current code
4. Maintaining consistency with the project's style

Return ONLY valid JSON, no markdown code blocks or explanation.
"""


def _build_existing_project_prompt(
    idea: Idea, analysis: ProjectAnalysisResult
) -> str:
    """Build enrichment prompt for existing projects."""
    # Format patterns
    patterns = ", ".join(p.pattern_name for p in analysis.detected_patterns) or "None detected"

    # Build mode-specific context
    if idea.mode == ProjectMode.EXISTING_COMPLETE:
        gaps_list = "\n".join(
            f"  - [{g.priority}] {g.description} (in {g.location})"
            for g in analysis.completion_gaps[:5]
        )
        mode_context = f"""COMPLETION GAPS (what needs to be finished):
{gaps_list}
Completeness Score: {analysis.completeness_score or 'N/A'}"""
    else:  # EXISTING_ENHANCE
        opps_list = "\n".join(
            f"  - [{o.opportunity_type}] {o.description}"
            for o in analysis.enhancement_opportunities[:5]
        )
        mode_context = f"""ENHANCEMENT OPPORTUNITIES:
{opps_list}
Architecture Quality Score: {analysis.architecture_quality_score or 'N/A'}"""

    return EXISTING_PROJECT_ENRICHMENT_PROMPT.format(
        title=idea.title,
        raw_content=idea.raw_content,
        tags=", ".join(idea.tags) if idea.tags else "None",
        project_name=analysis.project_name,
        tech_stack=", ".join(analysis.detected_tech_stack) or "None detected",
        patterns=patterns,
        entry_points=", ".join(analysis.entry_points) or "None detected",
        mode_specific_context=mode_context,
        readme_summary=analysis.readme_summary or "No README found",
    )


async def enrich_idea(
    idea: Idea, analysis: ProjectAnalysisResult | None = None
) -> EnrichmentOutput:
    """Run enrichment stage on an idea.

    Args:
        idea: The idea to enrich
        analysis: Optional project analysis result (for existing projects)

    Returns:
        EnrichmentOutput with enhanced analysis

    Raises:
        ValueError: If enrichment fails or returns invalid data
    """
    logger.info(f"Starting enrichment for idea: {idea.id}")

    model = genai.GenerativeModel("gemini-2.0-flash")

    # Build prompt based on mode
    if analysis and idea.mode != ProjectMode.NEW:
        # Existing project: use context-aware prompt
        prompt = _build_existing_project_prompt(idea, analysis)
    else:
        # New project: use standard prompt
        prompt = ENRICHMENT_PROMPT.format(
            title=idea.title,
            raw_content=idea.raw_content,
            tags=", ".join(idea.tags) if idea.tags else "None",
        )

    try:
        response = await model.generate_content_async(prompt)
        response_text = response.text.strip()

        # Clean up response if wrapped in markdown
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()

        # Parse JSON response
        data = json.loads(response_text)

        output = EnrichmentOutput(
            enhanced_title=data["enhanced_title"],
            enhanced_description=data["enhanced_description"],
            problem_statement=data["problem_statement"],
            potential_solutions=data["potential_solutions"],
            market_context=data["market_context"],
        )

        logger.info(f"Enrichment completed for idea: {idea.id}")
        return output

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse enrichment response: {e}")
        raise ValueError(f"Invalid enrichment response format: {e}")
    except KeyError as e:
        logger.error(f"Missing field in enrichment response: {e}")
        raise ValueError(f"Missing required field in enrichment: {e}")
    except Exception as e:
        logger.error(f"Enrichment failed: {e}")
        raise ValueError(f"Enrichment failed: {e}")
