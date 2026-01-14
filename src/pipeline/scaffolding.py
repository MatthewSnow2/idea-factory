"""Scaffolding pipeline stage using Claude.

Takes evaluated idea and generates project blueprint,
directory structure, and tech stack recommendations.
"""

import json
import logging
import os

import anthropic
from dotenv import load_dotenv

from ..core.models import (
    EnrichmentResult,
    EvaluationResult,
    Idea,
    ScaffoldingOutput,
)

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


async def scaffold_idea(
    idea: Idea,
    enrichment: EnrichmentResult,
    evaluation: EvaluationResult,
) -> ScaffoldingOutput:
    """Generate project scaffold for an approved idea.

    Uses two separate API calls for reliability:
    1. Generate blueprint (plain text)
    2. Generate structure (JSON)

    Args:
        idea: The original idea
        enrichment: The enrichment result
        evaluation: The evaluation result

    Returns:
        ScaffoldingOutput with project blueprint and structure

    Raises:
        ValueError: If scaffolding fails
    """
    logger.info(f"Starting scaffolding for idea: {idea.id}")

    try:
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

        logger.info(f"Scaffolding completed for idea: {idea.id}")
        return output

    except Exception as e:
        logger.error(f"Scaffolding failed: {e}")
        raise ValueError(f"Scaffolding failed: {e}")


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
