import express, { Request, Response } from 'express';
import cors from 'cors';
import { initializeDatabase } from './db';
import { enrichIdea, saveEnrichment, getEnrichment } from './services/enrichment';
import { evaluateIdea, saveEvaluation, getEvaluation, routeIdea } from './services/evaluation';
import { v4 as uuidv4 } from 'uuid';
import { Database } from 'sqlite';

const app = express();
const PORT = process.env.PORT || 3001;

let db: Database;

app.use(cors());
app.use(express.json());

// Initialize database on startup
app.listen(PORT, async () => {
  try {
    db = await initializeDatabase();
    console.log(`✅ Server running on http://localhost:${PORT}`);
    console.log(`📊 Ideas API available at /api/ideas`);
  } catch (error) {
    console.error('❌ Failed to start server:', error);
    process.exit(1);
  }
});

// Health check
app.get('/health', (_req: Request, res: Response) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// ============ IDEA MANAGEMENT ============

// Submit a new idea
app.post('/api/ideas', async (req: Request, res: Response) => {
  try {
    const { rawText, context, projectHint } = req.body;

    if (!rawText) {
      return res.status(400).json({ error: 'rawText is required' });
    }

    const ideaId = uuidv4();
    const source = 'manual';

    await db.run(
      `INSERT INTO ideas (id, source, raw_text, context, project_hint, status)
       VALUES (?, ?, ?, ?, ?, 'pending')`,
      [ideaId, source, rawText, context || null, projectHint || null]
    );

    res.status(201).json({
      id: ideaId,
      status: 'pending',
      message: 'Idea created. Run enrichment to analyze.'
    });
  } catch (error) {
    res.status(500).json({
      error: error instanceof Error ? error.message : 'Unknown error'
    });
  }
});

// Get all ideas with full details
app.get('/api/ideas', async (_req: Request, res: Response) => {
  try {
    const ideas = await db.all(`
      SELECT 
        i.id, i.raw_text, i.source, i.status, i.created_at, i.project_hint,
        e.evaluation_score, e.strategic_recommendation
      FROM ideas i
      LEFT JOIN idea_evaluation e ON i.id = e.idea_id
      ORDER BY i.created_at DESC
    `);

    const enrichedIdeas = await Promise.all(
      ideas.map(async (idea) => ({
        ...idea,
        enrichment: await getEnrichment(db, idea.id),
        evaluation: await getEvaluation(db, idea.id)
      }))
    );

    res.json({ ideas: enrichedIdeas, total: enrichedIdeas.length });
  } catch (error) {
    res.status(500).json({
      error: error instanceof Error ? error.message : 'Unknown error'
    });
  }
});

// Get single idea details
app.get('/api/ideas/:id', async (req: Request, res: Response) => {
  try {
    const { id } = req.params;

    const idea = await db.get(
      'SELECT * FROM ideas WHERE id = ?',
      [id]
    );

    if (!idea) {
      return res.status(404).json({ error: 'Idea not found' });
    }

    const enrichment = await getEnrichment(db, id);
    const evaluation = await getEvaluation(db, id);

    res.json({
      idea,
      enrichment,
      evaluation
    });
  } catch (error) {
    res.status(500).json({
      error: error instanceof Error ? error.message : 'Unknown error'
    });
  }
});

// ============ ENRICHMENT PIPELINE ============

// Run enrichment on an idea
app.post('/api/ideas/:id/enrich', async (req: Request, res: Response) => {
  try {
    const { id } = req.params;

    const idea = await db.get('SELECT * FROM ideas WHERE id = ?', [id]);
    if (!idea) {
      return res.status(404).json({ error: 'Idea not found' });
    }

    res.json({ status: 'enriching', message: 'Processing enrichment...' });

    // Run enrichment asynchronously
    (async () => {
      try {
        const enrichment = await enrichIdea(idea.raw_text, idea.context);
        await saveEnrichment(db, id, enrichment);
        await db.run(
          'UPDATE ideas SET status = ?, updated_at = ? WHERE id = ?',
          ['enriched', new Date().toISOString(), id]
        );
        console.log(`✅ Enrichment completed for idea ${id}`);
      } catch (error) {
        console.error(`❌ Enrichment failed for idea ${id}:`, error);
      }
    })();
  } catch (error) {
    res.status(500).json({
      error: error instanceof Error ? error.message : 'Unknown error'
    });
  }
});

// ============ EVALUATION PIPELINE ============

// Run evaluation on an enriched idea
app.post('/api/ideas/:id/evaluate', async (req: Request, res: Response) => {
  try {
    const { id } = req.params;

    const idea = await db.get('SELECT * FROM ideas WHERE id = ?', [id]);
    if (!idea) {
      return res.status(404).json({ error: 'Idea not found' });
    }

    const enrichment = await getEnrichment(db, id);
    if (!enrichment) {
      return res.status(400).json({
        error: 'Idea must be enriched before evaluation. Run /enrich first.'
      });
    }

    res.json({ status: 'evaluating', message: 'Processing strategic evaluation...' });

    // Run evaluation asynchronously
    (async () => {
      try {
        const evaluation = await evaluateIdea(idea.raw_text, enrichment);
        await saveEvaluation(db, id, evaluation);

        const route = routeIdea(
          evaluation.evaluationScore,
          evaluation.recommendation
        );
        const newStatus =
          route === 'GENERATE_BLUEPRINT'
            ? 'evaluated-ready'
            : route === 'DEFER_WITH_BLUEPRINT'
              ? 'deferred'
              : route === 'NEEDS_VALIDATION'
                ? 'research'
                : 'archived';

        await db.run(
          'UPDATE ideas SET status = ?, updated_at = ? WHERE id = ?',
          [newStatus, new Date().toISOString(), id]
        );

        console.log(
          `✅ Evaluation completed for idea ${id}. Route: ${route}, Status: ${newStatus}`
        );
      } catch (error) {
        console.error(`❌ Evaluation failed for idea ${id}:`, error);
      }
    })();
  } catch (error) {
    res.status(500).json({
      error: error instanceof Error ? error.message : 'Unknown error'
    });
  }
});

// Run full pipeline (enrich + evaluate) on an idea
app.post('/api/ideas/:id/analyze', async (req: Request, res: Response) => {
  try {
    const { id } = req.params;

    const idea = await db.get('SELECT * FROM ideas WHERE id = ?', [id]);
    if (!idea) {
      return res.status(404).json({ error: 'Idea not found' });
    }

    res.json({
      status: 'analyzing',
      message: 'Running full pipeline: enrichment → evaluation'
    });

    // Run full pipeline asynchronously
    (async () => {
      try {
        // Step 1: Enrich
        console.log(`🔄 Enriching idea ${id}...`);
        const enrichment = await enrichIdea(idea.raw_text, idea.context);
        await saveEnrichment(db, id, enrichment);
        console.log(`✅ Enrichment complete`);

        // Step 2: Evaluate
        console.log(`🔄 Evaluating idea ${id}...`);
        const evaluation = await evaluateIdea(idea.raw_text, enrichment);
        await saveEvaluation(db, id, evaluation);
        console.log(`✅ Evaluation complete`);

        // Step 3: Route
        const route = routeIdea(
          evaluation.evaluationScore,
          evaluation.recommendation
        );
        const newStatus =
          route === 'GENERATE_BLUEPRINT'
            ? 'evaluated-ready'
            : route === 'DEFER_WITH_BLUEPRINT'
              ? 'deferred'
              : route === 'NEEDS_VALIDATION'
                ? 'research'
                : 'archived';

        await db.run(
          'UPDATE ideas SET status = ?, updated_at = ? WHERE id = ?',
          [newStatus, new Date().toISOString(), id]
        );

        console.log(`✅ Analysis complete. Route: ${route}, Status: ${newStatus}`);
      } catch (error) {
        console.error(`❌ Analysis failed for idea ${id}:`, error);
      }
    })();
  } catch (error) {
    res.status(500).json({
      error: error instanceof Error ? error.message : 'Unknown error'
    });
  }
});

export default app;
