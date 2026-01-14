-- Agentic Idea Factory - SQLite Schema
-- Version: 1.0.0

PRAGMA foreign_keys = ON;

-- Core ideas table
CREATE TABLE IF NOT EXISTS ideas (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    raw_content TEXT NOT NULL,
    tags TEXT DEFAULT '[]',  -- JSON array
    current_stage TEXT NOT NULL DEFAULT 'input',
    current_status TEXT NOT NULL DEFAULT 'pending',
    submitted_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Enrichment results (Gemini analysis)
CREATE TABLE IF NOT EXISTS enrichment_results (
    idea_id TEXT PRIMARY KEY,
    enhanced_title TEXT NOT NULL,
    enhanced_description TEXT NOT NULL,
    problem_statement TEXT NOT NULL,
    potential_solutions TEXT NOT NULL,  -- JSON array
    market_context TEXT NOT NULL,
    enriched_at TEXT NOT NULL,
    enriched_by TEXT NOT NULL DEFAULT 'gemini-1.5-flash',
    FOREIGN KEY (idea_id) REFERENCES ideas(id) ON DELETE CASCADE
);

-- Evaluation results (Christensen MCP analysis)
CREATE TABLE IF NOT EXISTS evaluation_results (
    idea_id TEXT PRIMARY KEY,
    jtbd_analysis TEXT NOT NULL,
    disruption_potential TEXT NOT NULL,
    disruption_score REAL NOT NULL,
    capabilities_fit TEXT NOT NULL,  -- 'strong', 'developing', 'missing'
    recommendation TEXT NOT NULL,     -- 'develop', 'refine', 'reject', 'defer'
    recommendation_rationale TEXT NOT NULL,
    key_risks TEXT NOT NULL,          -- JSON array
    case_study_matches TEXT NOT NULL, -- JSON array
    overall_score REAL NOT NULL,
    evaluated_at TEXT NOT NULL,
    evaluated_by TEXT NOT NULL DEFAULT 'christensen-mcp',
    FOREIGN KEY (idea_id) REFERENCES ideas(id) ON DELETE CASCADE
);

-- Human-in-the-loop reviews
CREATE TABLE IF NOT EXISTS human_reviews (
    id TEXT PRIMARY KEY,
    idea_id TEXT NOT NULL,
    stage TEXT NOT NULL,              -- Which stage triggered this review
    decision TEXT NOT NULL,           -- 'approve', 'refine', 'reject', 'defer'
    decision_rationale TEXT,
    reviewer TEXT DEFAULT 'human',
    reviewed_at TEXT NOT NULL,
    FOREIGN KEY (idea_id) REFERENCES ideas(id) ON DELETE CASCADE
);

-- Scaffolding results (project templates)
CREATE TABLE IF NOT EXISTS scaffolding_results (
    idea_id TEXT PRIMARY KEY,
    blueprint_content TEXT NOT NULL,
    project_structure TEXT NOT NULL,  -- JSON object
    tech_stack TEXT NOT NULL,         -- JSON array
    estimated_hours REAL,
    scaffolded_at TEXT NOT NULL,
    scaffolded_by TEXT NOT NULL DEFAULT 'claude-3-5-sonnet',
    FOREIGN KEY (idea_id) REFERENCES ideas(id) ON DELETE CASCADE
);

-- Build tracking
CREATE TABLE IF NOT EXISTS build_results (
    idea_id TEXT PRIMARY KEY,
    github_repo TEXT,
    artifacts TEXT,                   -- JSON array of artifact paths
    outcome TEXT,                     -- 'success', 'partial', 'failed'
    started_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (idea_id) REFERENCES ideas(id) ON DELETE CASCADE
);

-- State transition audit log
CREATE TABLE IF NOT EXISTS state_transitions (
    id TEXT PRIMARY KEY,
    idea_id TEXT NOT NULL,
    from_stage TEXT NOT NULL,
    from_status TEXT NOT NULL,
    to_stage TEXT NOT NULL,
    to_status TEXT NOT NULL,
    triggered_by TEXT NOT NULL,       -- 'system', 'human', 'pipeline'
    metadata TEXT,                    -- JSON object for extra context
    created_at TEXT NOT NULL,
    FOREIGN KEY (idea_id) REFERENCES ideas(id) ON DELETE CASCADE
);

-- LLM response cache
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    response_content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    hit_count INTEGER DEFAULT 0,
    last_hit_at TEXT
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_ideas_stage ON ideas(current_stage);
CREATE INDEX IF NOT EXISTS idx_ideas_status ON ideas(current_status);
CREATE INDEX IF NOT EXISTS idx_transitions_idea ON state_transitions(idea_id);
CREATE INDEX IF NOT EXISTS idx_reviews_idea ON human_reviews(idea_id);
CREATE INDEX IF NOT EXISTS idx_cache_model ON llm_cache(model);
