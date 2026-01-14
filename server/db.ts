import sqlite3 from 'sqlite3';
import { open, Database } from 'sqlite';
import path from 'path';
import fs from 'fs';

const DB_PATH = path.join(process.cwd(), 'data', 'ideas.db');

// Ensure data directory exists
if (!fs.existsSync(path.dirname(DB_PATH))) {
  fs.mkdirSync(path.dirname(DB_PATH), { recursive: true });
}

export async function initializeDatabase(): Promise<Database> {
  const db = await open({
    filename: DB_PATH,
    driver: sqlite3.Database
  });

  await db.exec('PRAGMA foreign_keys = ON');

  // Core ideas table
  await db.exec(`
    CREATE TABLE IF NOT EXISTS ideas (
      id TEXT PRIMARY KEY,
      source TEXT NOT NULL,
      raw_text TEXT NOT NULL,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      context TEXT,
      project_hint TEXT,
      status TEXT DEFAULT 'pending',
      updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
  `);

  // Enrichment results (AI analysis)
  await db.exec(`
    CREATE TABLE IF NOT EXISTS idea_enrichment (
      idea_id TEXT PRIMARY KEY,
      category TEXT,
      complexity_score DECIMAL,
      market_validation TEXT,
      technical_feasibility TEXT,
      resource_estimate TEXT,
      enriched_at DATETIME,
      enriched_by TEXT,
      FOREIGN KEY (idea_id) REFERENCES ideas(id)
    )
  `);

  // Strategic evaluation (Christensen analysis)
  await db.exec(`
    CREATE TABLE IF NOT EXISTS idea_evaluation (
      idea_id TEXT PRIMARY KEY,
      jtbd_analysis TEXT,
      disruption_score DECIMAL,
      capabilities_fit TEXT,
      strategic_recommendation TEXT,
      case_study_matches TEXT,
      evaluation_score DECIMAL,
      evaluated_at DATETIME,
      FOREIGN KEY (idea_id) REFERENCES ideas(id)
    )
  `);

  // Execution plan (for high-scoring ideas)
  await db.exec(`
    CREATE TABLE IF NOT EXISTS idea_blueprints (
      idea_id TEXT PRIMARY KEY,
      architecture TEXT,
      implementation_steps TEXT,
      dependencies TEXT,
      success_criteria TEXT,
      estimated_hours DECIMAL,
      planned_at DATETIME,
      FOREIGN KEY (idea_id) REFERENCES ideas(id)
    )
  `);

  // Build tracking
  await db.exec(`
    CREATE TABLE IF NOT EXISTS idea_builds (
      idea_id TEXT PRIMARY KEY,
      started_at DATETIME,
      completed_at DATETIME,
      n8n_workflow_id TEXT,
      github_repo TEXT,
      artifacts TEXT,
      outcome TEXT,
      FOREIGN KEY (idea_id) REFERENCES ideas(id)
    )
  `);

  // Learning archive
  await db.exec(`
    CREATE TABLE IF NOT EXISTS idea_archive (
      idea_id TEXT PRIMARY KEY,
      archived_reason TEXT,
      lessons_learned TEXT,
      related_ideas TEXT,
      archived_at DATETIME,
      FOREIGN KEY (idea_id) REFERENCES ideas(id)
    )
  `);

  // Evaluation history
  await db.exec(`
    CREATE TABLE IF NOT EXISTS evaluation_runs (
      id TEXT PRIMARY KEY,
      run_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      ideas_processed INTEGER,
      ideas_promoted INTEGER,
      ideas_archived INTEGER,
      avg_evaluation_score DECIMAL
    )
  `);

  console.log(`✅ Database initialized at ${DB_PATH}`);
  return db;
}

export function getDbPath(): string {
  return DB_PATH;
}

// Run initialization if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  initializeDatabase()
    .then(() => {
      console.log('✅ SQLite schema created successfully');
      process.exit(0);
    })
    .catch((err) => {
      console.error('❌ Database initialization failed:', err);
      process.exit(1);
    });
}
