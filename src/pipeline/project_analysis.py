"""Project analysis pipeline stage.

Analyzes existing projects to understand structure, tech stack,
and identify gaps (COMPLETE mode) or opportunities (ENHANCE mode).
"""

import json
import logging
import os
import subprocess
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from ..core.models import (
    ArchitecturePattern,
    CompletionGap,
    EnhancementOpportunity,
    FileAnalysis,
    Idea,
    ProjectAnalysisOutput,
    ProjectMode,
    ProjectSource,
    SourceType,
)

load_dotenv()
logger = logging.getLogger(__name__)

# Configure Anthropic client
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

# Temp directory for cloned repos
CLONE_DIR = Path(__file__).parent.parent.parent / "temp" / "clones"

# File extensions to analyze
CODE_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".rs",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift",
    ".kt", ".scala", ".sql", ".sh", ".bash", ".yaml", ".yml",
    ".json", ".toml", ".md", ".html", ".css", ".scss",
}

# Files to prioritize for analysis
PRIORITY_FILES = {
    "README.md", "BLUEPRINT.md", "package.json", "requirements.txt",
    "Cargo.toml", "go.mod", "pyproject.toml", "setup.py",
    "Dockerfile", "docker-compose.yml", "Makefile",
    "tsconfig.json", ".env.example", "main.py", "app.py",
    "index.ts", "index.js", "main.ts", "main.js", "server.py",
}

COMPLETION_ANALYSIS_PROMPT = """You are an expert code analyst. Analyze this existing project to identify what needs to be completed.

PROJECT NAME: {project_name}
USER'S GOALS: {goals}

FILE STRUCTURE:
{file_tree}

KEY FILES CONTENT:
{key_files_content}

Analyze the project and provide a JSON response with this exact structure:

{{
  "project_name": "<extracted or inferred project name>",
  "detected_tech_stack": ["<technology1>", "<technology2>", ...],
  "detected_patterns": [
    {{
      "pattern_name": "<e.g., MVC, Clean Architecture>",
      "confidence": 0.0-1.0,
      "evidence": ["<file or pattern that suggests this>"]
    }}
  ],
  "total_files": <number>,
  "key_files": [
    {{
      "path": "<file path>",
      "language": "<language>",
      "purpose": "<what this file does>",
      "dependencies": ["<imports>"],
      "exports": ["<exports>"],
      "issues": ["<any problems found>"],
      "todos": ["<TODO comments found>"]
    }}
  ],
  "entry_points": ["<main entry files>"],
  "completion_gaps": [
    {{
      "gap_type": "missing_feature|incomplete_implementation|broken_test|todo",
      "description": "<what's missing or incomplete>",
      "location": "<file path or area>",
      "priority": "high|medium|low",
      "estimated_effort": "small|medium|large"
    }}
  ],
  "completeness_score": 0.0-1.0,
  "readme_summary": "<summary of README if exists>",
  "existing_blueprint": "<content of BLUEPRINT.md if exists>",
  "constraints": ["<any constraints like 'n8n-constrained'>"]
}}

Focus on:
1. Finding incomplete implementations (stubs, TODOs, NotImplementedError)
2. Missing tests for existing functionality
3. Broken or failing tests
4. Missing features referenced in documentation
5. Architecture gaps or inconsistencies

Return ONLY valid JSON, no markdown code blocks.
"""

ENHANCEMENT_ANALYSIS_PROMPT = """You are an expert code analyst. Analyze this existing project to identify enhancement opportunities.

PROJECT NAME: {project_name}
USER'S ENHANCEMENT GOALS: {goals}

FILE STRUCTURE:
{file_tree}

KEY FILES CONTENT:
{key_files_content}

Analyze the project and provide a JSON response with this exact structure:

{{
  "project_name": "<extracted or inferred project name>",
  "detected_tech_stack": ["<technology1>", "<technology2>", ...],
  "detected_patterns": [
    {{
      "pattern_name": "<e.g., MVC, Clean Architecture>",
      "confidence": 0.0-1.0,
      "evidence": ["<file or pattern that suggests this>"]
    }}
  ],
  "total_files": <number>,
  "key_files": [
    {{
      "path": "<file path>",
      "language": "<language>",
      "purpose": "<what this file does>",
      "dependencies": ["<imports>"],
      "exports": ["<exports>"],
      "issues": ["<any problems found>"],
      "todos": ["<TODO comments found>"]
    }}
  ],
  "entry_points": ["<main entry files>"],
  "enhancement_opportunities": [
    {{
      "opportunity_type": "new_feature|refactoring|performance|testing",
      "description": "<what could be enhanced>",
      "affected_areas": ["<files/modules affected>"],
      "integration_points": ["<where it connects to existing code>"],
      "estimated_effort": "small|medium|large"
    }}
  ],
  "architecture_quality_score": 0.0-1.0,
  "readme_summary": "<summary of README if exists>",
  "existing_blueprint": "<content of BLUEPRINT.md if exists>",
  "constraints": ["<any constraints like 'n8n-constrained'>"]
}}

Focus on:
1. Where the user's enhancement goals fit into the architecture
2. Integration points for new features
3. Patterns the enhancement should follow
4. Areas that could benefit from refactoring
5. Performance optimization opportunities
6. Testing improvements needed

Return ONLY valid JSON, no markdown code blocks.
"""


async def analyze_project(idea: Idea) -> ProjectAnalysisOutput:
    """Analyze an existing project.

    Args:
        idea: The idea with project_source configured

    Returns:
        ProjectAnalysisOutput with analysis results

    Raises:
        ValueError: If analysis fails
    """
    if not idea.project_source:
        raise ValueError("project_source required for project analysis")

    logger.info(f"Starting project analysis for idea: {idea.id}")

    # Get project path (clone if needed)
    project_path = await _get_project_path(idea.project_source)
    logger.info(f"Analyzing project at: {project_path}")

    # Scan project files
    file_tree = _scan_project_files(project_path)
    total_files = sum(len(files) for files in file_tree.values())
    logger.info(f"Found {total_files} files in project")

    # Read key files
    key_files_content = _read_key_files(project_path, file_tree)

    # Infer project name from directory
    project_name = project_path.name

    # Run Claude analysis based on mode
    output = await _run_analysis(
        idea.mode,
        project_name,
        idea.raw_content,  # User's goals
        file_tree,
        key_files_content,
        total_files,
    )

    logger.info(f"Project analysis completed for idea: {idea.id}")
    return output


async def _get_project_path(source: ProjectSource) -> Path:
    """Get local path to project, cloning if necessary."""
    if source.source_type == SourceType.LOCAL_PATH:
        path = Path(source.location).expanduser().resolve()
        if not path.exists():
            raise ValueError(f"Local path does not exist: {source.location}")
        return path

    elif source.source_type == SourceType.GIT_URL:
        # Clone to temp directory
        repo_name = source.location.split("/")[-1].replace(".git", "")
        clone_path = CLONE_DIR / repo_name

        CLONE_DIR.mkdir(parents=True, exist_ok=True)

        if clone_path.exists():
            # Pull latest
            logger.info(f"Updating existing clone: {clone_path}")
            subprocess.run(
                ["git", "-C", str(clone_path), "pull"],
                check=True,
                capture_output=True,
            )
        else:
            # Clone
            logger.info(f"Cloning repository: {source.location}")
            branch_args = ["-b", source.branch] if source.branch else []
            subprocess.run(
                ["git", "clone", *branch_args, source.location, str(clone_path)],
                check=True,
                capture_output=True,
            )

        if source.subdirectory:
            return clone_path / source.subdirectory
        return clone_path

    raise ValueError(f"Unknown source type: {source.source_type}")


def _scan_project_files(project_path: Path) -> dict[str, list[str]]:
    """Scan project and categorize files by directory."""
    file_tree: dict[str, list[str]] = {}

    for file_path in project_path.rglob("*"):
        if not file_path.is_file():
            continue

        # Skip common directories to ignore
        parts = file_path.parts
        if any(
            part in {
                "node_modules", ".git", "__pycache__", ".venv", "venv",
                "dist", "build", ".next", ".cache", "coverage",
                "target", ".idea", ".vscode",
            }
            for part in parts
        ):
            continue

        # Get relative path
        rel_path = file_path.relative_to(project_path)
        parent = str(rel_path.parent) if rel_path.parent != Path(".") else "root"

        if parent not in file_tree:
            file_tree[parent] = []
        file_tree[parent].append(str(rel_path))

    return file_tree


def _read_key_files(
    project_path: Path, file_tree: dict[str, list[str]]
) -> dict[str, str]:
    """Read content of key files for analysis."""
    key_files: dict[str, str] = {}
    files_read = 0
    max_files = 20  # Limit to avoid token explosion
    max_file_size = 50000  # 50KB per file

    # First, read priority files
    for dir_name, files in file_tree.items():
        for file_path in files:
            if files_read >= max_files:
                break

            file_name = Path(file_path).name
            if file_name in PRIORITY_FILES:
                full_path = project_path / file_path
                try:
                    content = full_path.read_text(encoding="utf-8", errors="ignore")
                    if len(content) <= max_file_size:
                        key_files[file_path] = content
                        files_read += 1
                except Exception as e:
                    logger.warning(f"Could not read {file_path}: {e}")

        if files_read >= max_files:
            break

    # Then, read additional source files with code extensions
    for dir_name, files in file_tree.items():
        for file_path in files:
            if files_read >= max_files:
                break
            if file_path in key_files:
                continue

            suffix = Path(file_path).suffix
            if suffix in CODE_EXTENSIONS:
                full_path = project_path / file_path
                try:
                    content = full_path.read_text(encoding="utf-8", errors="ignore")
                    if len(content) <= max_file_size:
                        key_files[file_path] = content
                        files_read += 1
                except Exception as e:
                    logger.warning(f"Could not read {file_path}: {e}")

        if files_read >= max_files:
            break

    return key_files


def _format_file_tree(file_tree: dict[str, list[str]]) -> str:
    """Format file tree for prompt."""
    lines = []
    for dir_name, files in sorted(file_tree.items()):
        lines.append(f"{dir_name}/")
        for f in sorted(files)[:20]:  # Limit files per directory
            lines.append(f"  {Path(f).name}")
        if len(files) > 20:
            lines.append(f"  ... and {len(files) - 20} more files")
    return "\n".join(lines)


def _format_key_files(key_files: dict[str, str]) -> str:
    """Format key files content for prompt."""
    parts = []
    for path, content in key_files.items():
        # Truncate very long files
        if len(content) > 10000:
            content = content[:10000] + "\n... [truncated]"
        parts.append(f"=== {path} ===\n{content}")
    return "\n\n".join(parts)


async def _run_analysis(
    mode: ProjectMode,
    project_name: str,
    goals: str,
    file_tree: dict[str, list[str]],
    key_files_content: dict[str, str],
    total_files: int,
) -> ProjectAnalysisOutput:
    """Run Claude analysis on the project."""
    # Choose prompt based on mode
    if mode == ProjectMode.EXISTING_COMPLETE:
        prompt_template = COMPLETION_ANALYSIS_PROMPT
    else:  # EXISTING_ENHANCE
        prompt_template = ENHANCEMENT_ANALYSIS_PROMPT

    file_tree_str = _format_file_tree(file_tree)
    key_files_str = _format_key_files(key_files_content)

    prompt = prompt_template.format(
        project_name=project_name,
        goals=goals,
        file_tree=file_tree_str,
        key_files_content=key_files_str,
    )

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = message.content[0].text.strip()

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

        # Build models from parsed data
        patterns = [
            ArchitecturePattern(**p) for p in data.get("detected_patterns", [])
        ]
        key_files = [FileAnalysis(**f) for f in data.get("key_files", [])]
        gaps = [CompletionGap(**g) for g in data.get("completion_gaps", [])]
        opportunities = [
            EnhancementOpportunity(**o)
            for o in data.get("enhancement_opportunities", [])
        ]

        return ProjectAnalysisOutput(
            project_name=data.get("project_name", project_name),
            detected_tech_stack=data.get("detected_tech_stack", []),
            detected_patterns=patterns,
            total_files=data.get("total_files", total_files),
            key_files=key_files,
            entry_points=data.get("entry_points", []),
            completion_gaps=gaps,
            completeness_score=data.get("completeness_score"),
            enhancement_opportunities=opportunities,
            architecture_quality_score=data.get("architecture_quality_score"),
            readme_summary=data.get("readme_summary"),
            existing_blueprint=data.get("existing_blueprint"),
            constraints=data.get("constraints", []),
        )

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse analysis response: {e}")
        raise ValueError(f"Invalid analysis response format: {e}")
    except KeyError as e:
        logger.error(f"Missing field in analysis response: {e}")
        raise ValueError(f"Missing required field in analysis: {e}")
    except Exception as e:
        logger.error(f"Project analysis failed: {e}")
        raise ValueError(f"Project analysis failed: {e}")
