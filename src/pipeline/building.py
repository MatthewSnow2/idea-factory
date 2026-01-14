"""Building pipeline stage using Claude.

Takes scaffolding blueprint and generates actual project files,
creating a working project structure with boilerplate code.
"""

import json
import logging
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from ..core.models import (
    BuildOutput,
    EnrichmentResult,
    ScaffoldingResult,
)

load_dotenv()
logger = logging.getLogger(__name__)

# Initialize Anthropic client
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

# Output directory for generated projects
BUILD_OUTPUT_DIR = Path(__file__).parent.parent.parent / "output" / "projects"

SINGLE_FILE_PROMPT = """You are an expert software engineer. Generate code for a single file.

## PROJECT: {title}
{description}

## TECH STACK: {tech_stack}

## FILE TO GENERATE: {file_path}

Generate production-quality code for this file. The code should:
1. Follow best practices for the tech stack
2. Include proper imports
3. Be consistent with the project architecture

Return ONLY the file content - no JSON wrapper, no markdown code blocks, just the raw file content.
"""

CONFIG_FILE_PROMPT = """Generate a config file for a {tech_stack_primary} project.

## PROJECT: {title}
## FILE: {file_path}
## TECH STACK: {tech_stack}

Generate appropriate settings for a production project.
Return ONLY the file content - no JSON wrapper, no markdown code blocks, just the raw config file content.
"""


async def build_project(
    idea_id: str,
    enrichment: EnrichmentResult,
    scaffolding: ScaffoldingResult,
) -> BuildOutput:
    """Build actual project files from scaffolding.

    Args:
        idea_id: The idea ID (used for output directory)
        enrichment: The enrichment result
        scaffolding: The scaffolding result with blueprint and structure

    Returns:
        BuildOutput with generated artifacts

    Raises:
        ValueError: If building fails
    """
    logger.info(f"Starting build for idea: {idea_id}")

    # Create output directory
    project_dir = BUILD_OUTPUT_DIR / idea_id
    project_dir.mkdir(parents=True, exist_ok=True)

    artifacts: list[str] = []

    try:
        # Prioritize essential files to generate (limit to avoid long builds)
        essential_files = _select_essential_files(scaffolding.project_structure)

        # Generate essential files one at a time
        for category, file_path in essential_files:
            is_config = category == "config"
            content = await _generate_single_file(
                enrichment.enhanced_title,
                enrichment.enhanced_description,
                scaffolding.tech_stack,
                file_path,
                is_config=is_config,
            )

            if content:
                written = await _write_single_file(project_dir, file_path, content)
                if written:
                    artifacts.append(file_path)

        # Write the blueprint as BLUEPRINT.md
        blueprint_path = project_dir / "BLUEPRINT.md"
        blueprint_path.write_text(scaffolding.blueprint_content)
        artifacts.append("BLUEPRINT.md")

        # Determine outcome based on essential files generated
        essential_count = len(essential_files)
        actual_count = len(artifacts) - 1  # Exclude BLUEPRINT.md from count

        if actual_count >= essential_count * 0.8:
            outcome = "success"
        elif actual_count >= essential_count * 0.5:
            outcome = "partial"
        else:
            outcome = "failed"

        logger.info(
            f"Build completed for idea {idea_id}: "
            f"{actual_count}/{essential_count} essential files, outcome={outcome}"
        )

        return BuildOutput(
            github_repo=None,  # GitHub integration not implemented yet
            artifacts=artifacts,
            outcome=outcome,
        )

    except Exception as e:
        logger.error(f"Build failed for idea {idea_id}: {e}")
        raise ValueError(f"Build failed: {e}")


def _select_essential_files(
    project_structure: dict[str, list[str]],
    max_files: int = 10,
) -> list[tuple[str, str]]:
    """Select essential files to generate for the MVP build.

    Prioritizes:
    1. package.json and tsconfig.json (config)
    2. Main entry point (src/app.ts, src/index.ts, etc.)
    3. Core service files
    4. README.md

    Returns list of (category, file_path) tuples.
    """
    selected: list[tuple[str, str]] = []

    # Priority config files
    config_priority = ["package.json", "tsconfig.json", ".env.example", "Dockerfile"]
    for cf in config_priority:
        if cf in project_structure.get("config", []):
            selected.append(("config", cf))
            if len(selected) >= max_files:
                return selected

    # Priority source files (entry points and core)
    src_priority_patterns = ["app.ts", "index.ts", "main.ts", "server.ts"]
    src_files = project_structure.get("src", [])
    for pattern in src_priority_patterns:
        for sf in src_files:
            if sf.endswith(pattern):
                selected.append(("src", sf))
                if len(selected) >= max_files:
                    return selected
                break

    # Add a few more src files
    for sf in src_files[:3]:
        if ("src", sf) not in selected:
            selected.append(("src", sf))
            if len(selected) >= max_files:
                return selected

    # README
    if "docs/README.md" in project_structure.get("docs", []):
        selected.append(("docs", "docs/README.md"))
    elif "README.md" in project_structure.get("docs", []):
        selected.append(("docs", "README.md"))

    return selected


async def _generate_single_file(
    title: str,
    description: str,
    tech_stack: list[str],
    file_path: str,
    is_config: bool = False,
) -> str | None:
    """Generate a single file's content using Claude."""
    if is_config:
        prompt = CONFIG_FILE_PROMPT.format(
            title=title,
            tech_stack=", ".join(tech_stack),
            tech_stack_primary=tech_stack[0] if tech_stack else "Node.js",
            file_path=file_path,
        )
    else:
        prompt = SINGLE_FILE_PROMPT.format(
            title=title,
            description=description,
            tech_stack=", ".join(tech_stack),
            file_path=file_path,
        )

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        response_text = message.content[0].text.strip()

        # Clean up response if wrapped in markdown code blocks
        if response_text.startswith("```"):
            # Find the end of the first line (language specifier)
            first_newline = response_text.find("\n")
            if first_newline > 0:
                response_text = response_text[first_newline + 1:]
            else:
                response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]

        return response_text.strip()

    except anthropic.APIError as e:
        logger.error(f"Anthropic API error for {file_path}: {e}")
        return None
    except Exception as e:
        logger.error(f"File generation failed for {file_path}: {e}")
        return None


async def _write_single_file(project_dir: Path, file_path: str, content: str) -> bool:
    """Write a single generated file to disk."""
    try:
        full_path = project_dir / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)
        logger.debug(f"Wrote file: {file_path}")
        return True
    except Exception as e:
        logger.warning(f"Failed to write file {file_path}: {e}")
        return False
