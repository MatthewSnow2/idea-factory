import { GoogleGenerativeAI } from '@google/generative-ai';
import { Database } from 'sqlite';

const genAI = new GoogleGenerativeAI(process.env.GOOGLE_API_KEY || '');

export interface EnrichmentOutput {
  category: 'feature' | 'product' | 'integration' | 'research';
  complexityScore: number;
  marketValidation: {
    searchVolume?: string;
    competitors: string[];
    marketGap: string;
  };
  technicalFeasibility: {
    stackFit: 'perfect' | 'good' | 'requires-learning' | 'blocker';
    dependencies: string[];
    riskFactors: string[];
  };
  resourceEstimate: {
    estimatedHours: number;
    skillsRequired: string[];
    costEstimate?: number;
  };
}

const ENRICHMENT_PROMPT = (idea: string, context: string) => `
You are an expert product and technical analyst. Analyze this idea and provide structured enrichment data.

IDEA: ${idea}

CONTEXT: ${context || 'No additional context provided'}

Provide a JSON response with this exact structure:
{
  "category": "feature" or "product" or "integration" or "research",
  "complexityScore": <number 0-1>,
  "marketValidation": {
    "searchVolume": "<estimated relative search volume: low/medium/high>",
    "competitors": [<list of 2-3 direct competitors or similar solutions>],
    "marketGap": "<1-2 sentence description of market gap this fills>"
  },
  "technicalFeasibility": {
    "stackFit": "perfect" or "good" or "requires-learning" or "blocker",
    "dependencies": [<list of required technologies/services>],
    "riskFactors": [<list of 2-3 technical risks>]
  },
  "resourceEstimate": {
    "estimatedHours": <number>,
    "skillsRequired": [<list of required skills>],
    "costEstimate": <optional number>
  }
}

Be specific and analytical. Return ONLY valid JSON, no markdown or explanation.
`;

export async function enrichIdea(
  idea: string,
  context: string
): Promise<EnrichmentOutput> {
  try {
    const model = genAI.getGenerativeModel({ model: 'gemini-1.5-flash' });
    
    const result = await model.generateContent(
      ENRICHMENT_PROMPT(idea, context)
    );

    const response = result.response.text();
    const enrichedData = JSON.parse(response);

    return enrichedData as EnrichmentOutput;
  } catch (error) {
    console.error('Enrichment failed:', error);
    throw new Error(`Failed to enrich idea: ${error instanceof Error ? error.message : String(error)}`);
  }
}

export async function saveEnrichment(
  db: Database,
  ideaId: string,
  enrichment: EnrichmentOutput
): Promise<void> {
  await db.run(
    `
    INSERT OR REPLACE INTO idea_enrichment
    (idea_id, category, complexity_score, market_validation, technical_feasibility, resource_estimate, enriched_at, enriched_by)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `,
    [
      ideaId,
      enrichment.category,
      enrichment.complexityScore,
      JSON.stringify(enrichment.marketValidation),
      JSON.stringify(enrichment.technicalFeasibility),
      JSON.stringify(enrichment.resourceEstimate),
      new Date().toISOString(),
      'gemini-1.5-flash'
    ]
  );
}

export async function getEnrichment(
  db: Database,
  ideaId: string
): Promise<EnrichmentOutput | null> {
  const row = await db.get(
    'SELECT * FROM idea_enrichment WHERE idea_id = ?',
    [ideaId]
  );

  if (!row) return null;

  return {
    category: row.category,
    complexityScore: row.complexity_score,
    marketValidation: JSON.parse(row.market_validation),
    technicalFeasibility: JSON.parse(row.technical_feasibility),
    resourceEstimate: JSON.parse(row.resource_estimate)
  };
}
