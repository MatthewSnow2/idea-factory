# Agentic Idea Factory

Python-orchestrated idea pipeline with MCP persona agents for strategic evaluation.

## Overview

Three-stage pipeline that transforms raw ideas into validated project blueprints:

```
INPUT → ENRICHMENT → EVALUATION → [HIL] → SCAFFOLDING → [HIL] → BUILDING → COMPLETED
         (Gemini)    (Christensen)
```

**Key Innovation**: MCP Tool Bridge - Python orchestrator spawns TypeScript MCP servers and communicates via JSON-RPC. Same persona works both interactively (Claude Desktop) AND as pipeline stage.

## Architecture

| Component | Technology | Purpose |
|-----------|------------|---------|
| Orchestration | Python + FastAPI | Pipeline coordination, API |
| Enrichment | Gemini 1.5 Flash | Idea enhancement, market context |
| Evaluation | Christensen MCP | JTBD analysis, disruption scoring |
| Persistence | SQLite | Local-first database |
| HIL Gates | Human Review API | Approve/refine/reject/defer |

## Quick Start

```bash
# 1. Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 2. Install dependencies
pip install -e .

# 3. Set up environment
cp .env.example .env
# Edit .env with your API keys

# 4. Start the server
uvicorn src.main:app --reload

# 5. Open API docs
open http://localhost:8000/docs
```

## API Endpoints

### Ideas
- `POST /api/ideas` - Create new idea
- `GET /api/ideas` - List ideas (with filtering)
- `GET /api/ideas/{id}` - Get idea with all data
- `GET /api/ideas/{id}/status` - Pipeline status
- `POST /api/ideas/{id}/start` - Start pipeline
- `POST /api/ideas/{id}/analyze` - Run full analysis

### Reviews
- `POST /api/reviews/{id}` - Submit review decision
- `GET /api/reviews/{id}` - Get review history
- `GET /api/reviews/pending/count` - Count pending reviews

### Status
- `GET /health` - Health check
- `GET /api/stats` - Pipeline statistics

## Pipeline Stages

### 1. INPUT
Raw idea submitted. Status: `pending`

### 2. ENRICHMENT (Gemini)
AI-powered enhancement:
- Enhanced title and description
- Problem statement clarification
- Potential solutions
- Market context analysis

### 3. EVALUATION (Christensen MCP)
Strategic analysis using Clayton Christensen frameworks:
- Jobs-to-be-Done analysis
- Disruption potential scoring
- Capabilities fit assessment
- Recommendation (develop/refine/reject/defer)

### 4. HUMAN REVIEW (HIL Gate)
Human decision required:
- **Approve** → Advance to scaffolding
- **Refine** → Return to enrichment
- **Reject** → Archive
- **Defer** → Pause for later

### 5. SCAFFOLDING (Claude)
Project template generation:
- BLUEPRINT.md
- Project structure
- Tech stack recommendations

### 6. BUILDING
Implementation phase (future)

## MCP Tool Bridge

The key architectural innovation - Python calls TypeScript MCP servers:

```python
async with MCPToolBridge("/path/to/christensen-mcp") as bridge:
    result = await bridge.call_tool("analyze_decision", {
        "scenario": "Should we build X?"
    })
```

Same MCP server works both ways:
- **Interactive**: Claude Desktop calls it directly
- **Pipeline**: Python orchestrator calls via bridge

## Configuration

### Environment Variables

```bash
GOOGLE_API_KEY=your-gemini-api-key
ANTHROPIC_API_KEY=your-anthropic-api-key
```

### MCP Server Paths

By default, looks for Christensen MCP at:
```
~/projects/christensen-mcp
```

## Development

```bash
# Run tests
pytest

# Type checking
mypy src/

# Linting
ruff check src/
ruff format src/
```

## Project Structure

```
agentic-idea-factory/
├── src/
│   ├── api/           # FastAPI routes
│   ├── core/          # Pydantic models, state machine
│   ├── db/            # SQLite repository
│   ├── mcp/           # MCP Tool Bridge
│   ├── pipeline/      # Stage implementations
│   └── main.py        # FastAPI entry point
├── data/              # SQLite database
├── mcp-personas/      # Symlinks to MCP servers
└── tests/
```

## Related Projects

- [christensen-mcp](https://github.com/m2ai-mcp-servers/christensen-mcp) - Christensen analysis MCP server
- [Perceptor](https://github.com/m2ai-portfolio/perceptor) - Context sharing between Claude Desktop/Code

## License

MIT
