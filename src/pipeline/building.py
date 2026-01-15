"""Building pipeline stage using Claude.

Takes scaffolding blueprint and generates actual project files,
creating a working project structure with boilerplate code.

For existing projects, generates patches and targeted new files
that integrate with the existing codebase.
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
    FileModification,
    Idea,
    NewFileSpec,
    ProjectMode,
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

EXISTING_PROJECT_NEW_FILE_PROMPT = """You are an expert software engineer. Generate a NEW file that integrates with an existing project.

## PROJECT: {project_name}
## GOAL: {title}
{description}

## TECH STACK: {tech_stack}

## NEW FILE TO GENERATE: {file_path}
Purpose: {purpose}
Integrates with: {integrates_with}

Generate production-quality code for this NEW file. The code should:
1. Follow the same patterns as the existing project
2. Import from and integrate with the specified existing files
3. Be consistent with the project's architecture and coding style

Return ONLY the file content - no JSON wrapper, no markdown code blocks, just the raw file content.
"""

EXISTING_PROJECT_PATCH_PROMPT = """You are an expert software engineer. Generate a PATCH for an existing file.

## PROJECT: {project_name}
## GOAL: {title}
{description}

## FILE TO MODIFY: {file_path}
Modification Type: {modification_type}
Change Description: {change_description}
Rationale: {rationale}

Generate a unified diff patch (git diff format) that makes the required changes.
The patch should:
1. Be minimal - only change what's necessary
2. Preserve existing functionality
3. Follow the project's coding style

Return ONLY the patch in unified diff format, like:
--- a/{file_path}
+++ b/{file_path}
@@ -line,count +line,count @@
 context line
-removed line
+added line
 context line

Return ONLY the diff content - no JSON wrapper, no markdown code blocks.
"""


async def build_project(
    idea_id: str,
    enrichment: EnrichmentResult,
    scaffolding: ScaffoldingResult,
    idea: Idea | None = None,
) -> BuildOutput:
    """Build actual project files from scaffolding.

    For NEW projects:
        Creates complete project structure with all files.

    For EXISTING projects:
        Generates patches for modifications and new files
        that integrate with the existing codebase.

    Args:
        idea_id: The idea ID (used for output directory)
        enrichment: The enrichment result
        scaffolding: The scaffolding result with blueprint and structure
        idea: Optional idea for mode detection

    Returns:
        BuildOutput with generated artifacts

    Raises:
        ValueError: If building fails
    """
    logger.info(f"Starting build for idea: {idea_id}")

    # Determine mode
    if idea and idea.mode != ProjectMode.NEW:
        return await _build_existing_project(idea_id, enrichment, scaffolding, idea)
    else:
        return await _build_new_project(idea_id, enrichment, scaffolding)


async def _build_new_project(
    idea_id: str,
    enrichment: EnrichmentResult,
    scaffolding: ScaffoldingResult,
) -> BuildOutput:
    """Build a new project from scratch."""
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
            github_repo=None,
            artifacts=artifacts,
            outcome=outcome,
        )

    except Exception as e:
        logger.error(f"Build failed for idea {idea_id}: {e}")
        raise ValueError(f"Build failed: {e}")


async def _build_existing_project(
    idea_id: str,
    enrichment: EnrichmentResult,
    scaffolding: ScaffoldingResult,
    idea: Idea,
) -> BuildOutput:
    """Build patches and new files for an existing project."""
    # Create output directories
    project_dir = BUILD_OUTPUT_DIR / idea_id
    patches_dir = project_dir / "patches"
    new_files_dir = project_dir / "new"

    project_dir.mkdir(parents=True, exist_ok=True)
    patches_dir.mkdir(parents=True, exist_ok=True)
    new_files_dir.mkdir(parents=True, exist_ok=True)

    artifacts: list[str] = []
    project_name = idea.project_source.location.split("/")[-1] if idea.project_source else "project"

    try:
        # Generate patches for file modifications
        for modification in scaffolding.file_modifications:
            patch_content = await _generate_patch(
                project_name,
                enrichment.enhanced_title,
                enrichment.enhanced_description,
                scaffolding.tech_stack,
                modification,
            )

            if patch_content:
                # Write patch file
                safe_filename = modification.file_path.replace("/", "_").replace("\\", "_")
                patch_path = patches_dir / f"{safe_filename}.patch"
                patch_path.write_text(patch_content)
                artifacts.append(f"patches/{safe_filename}.patch")
                logger.debug(f"Generated patch for: {modification.file_path}")

        # Generate new files
        for new_file in scaffolding.new_files:
            content = await _generate_integration_file(
                project_name,
                enrichment.enhanced_title,
                enrichment.enhanced_description,
                scaffolding.tech_stack,
                new_file,
            )

            if content:
                written = await _write_single_file(new_files_dir, new_file.file_path, content)
                if written:
                    artifacts.append(f"new/{new_file.file_path}")
                    logger.debug(f"Generated new file: {new_file.file_path}")

        # Write the blueprint as BLUEPRINT.md
        blueprint_path = project_dir / "BLUEPRINT.md"
        blueprint_path.write_text(scaffolding.blueprint_content)
        artifacts.append("BLUEPRINT.md")

        # Write a manifest of preserved files
        if scaffolding.preserved_files:
            manifest_content = "# Preserved Files\n\nThese files should NOT be modified:\n\n"
            for f in scaffolding.preserved_files:
                manifest_content += f"- {f}\n"
            manifest_path = project_dir / "PRESERVED_FILES.md"
            manifest_path.write_text(manifest_content)
            artifacts.append("PRESERVED_FILES.md")

        # Write application instructions
        instructions = _generate_application_instructions(
            project_name,
            scaffolding.file_modifications,
            scaffolding.new_files,
            scaffolding.preserved_files,
        )
        instructions_path = project_dir / "APPLY_CHANGES.md"
        instructions_path.write_text(instructions)
        artifacts.append("APPLY_CHANGES.md")

        # Determine outcome
        total_expected = len(scaffolding.file_modifications) + len(scaffolding.new_files)
        actual_count = len(artifacts) - 3  # Exclude BLUEPRINT.md, PRESERVED_FILES.md, APPLY_CHANGES.md

        if total_expected == 0:
            outcome = "success"  # No changes expected
        elif actual_count >= total_expected * 0.8:
            outcome = "success"
        elif actual_count >= total_expected * 0.5:
            outcome = "partial"
        else:
            outcome = "failed"

        logger.info(
            f"Existing project build completed for idea {idea_id}: "
            f"{len(scaffolding.file_modifications)} patches, "
            f"{len(scaffolding.new_files)} new files, outcome={outcome}"
        )

        return BuildOutput(
            github_repo=None,
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


async def _generate_patch(
    project_name: str,
    title: str,
    description: str,
    tech_stack: list[str],
    modification: FileModification,
) -> str | None:
    """Generate a patch for an existing file."""
    prompt = EXISTING_PROJECT_PATCH_PROMPT.format(
        project_name=project_name,
        title=title,
        description=description,
        tech_stack=", ".join(tech_stack),
        file_path=modification.file_path,
        modification_type=modification.modification_type,
        change_description=modification.content,
        rationale=modification.rationale,
    )

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
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

        return response_text.strip()

    except anthropic.APIError as e:
        logger.error(f"Anthropic API error for patch {modification.file_path}: {e}")
        return None
    except Exception as e:
        logger.error(f"Patch generation failed for {modification.file_path}: {e}")
        return None


async def _generate_integration_file(
    project_name: str,
    title: str,
    description: str,
    tech_stack: list[str],
    new_file: NewFileSpec,
) -> str | None:
    """Generate a new file that integrates with existing project."""
    prompt = EXISTING_PROJECT_NEW_FILE_PROMPT.format(
        project_name=project_name,
        title=title,
        description=description,
        tech_stack=", ".join(tech_stack),
        file_path=new_file.file_path,
        purpose=new_file.purpose,
        integrates_with=", ".join(new_file.integrates_with) or "None specified",
    )

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
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

        return response_text.strip()

    except anthropic.APIError as e:
        logger.error(f"Anthropic API error for new file {new_file.file_path}: {e}")
        return None
    except Exception as e:
        logger.error(f"New file generation failed for {new_file.file_path}: {e}")
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


def _generate_application_instructions(
    project_name: str,
    modifications: list[FileModification],
    new_files: list[NewFileSpec],
    preserved_files: list[str],
) -> str:
    """Generate instructions for applying changes to the existing project."""
    instructions = f"""# How to Apply Changes to {project_name}

This document explains how to apply the generated changes to your existing project.

## Overview

- **Patches**: {len(modifications)} file(s) to modify
- **New Files**: {len(new_files)} new file(s) to add
- **Preserved Files**: {len(preserved_files)} file(s) to NOT touch

## Step 1: Review Changes

Before applying, review each patch and new file to ensure they align with your project's needs.

## Step 2: Apply Patches

Apply patches in the `patches/` directory to your project:

```bash
# Navigate to your project root
cd /path/to/{project_name}

# Apply each patch (review first!)
"""

    for mod in modifications:
        safe_filename = mod.file_path.replace("/", "_").replace("\\", "_")
        instructions += f"git apply /path/to/output/patches/{safe_filename}.patch\n"

    instructions += """```

## Step 3: Add New Files

Copy new files from the `new/` directory to your project:

```bash
"""

    for nf in new_files:
        instructions += f"cp /path/to/output/new/{nf.file_path} /path/to/{project_name}/{nf.file_path}\n"

    instructions += """```

## Step 4: Preserved Files

The following files were identified as critical and should NOT be modified:

"""

    for pf in preserved_files:
        instructions += f"- `{pf}`\n"

    instructions += """

## Step 5: Test

After applying changes:

1. Run your existing tests to ensure no regressions
2. Test the new/modified functionality
3. Review the integration points

## Notes

- Patches are in unified diff format and can be applied with `git apply` or `patch`
- If patches fail to apply cleanly, manually review and integrate the changes
- New files may need import adjustments based on your exact project structure
"""

    return instructions
