import { Anthropic } from '@anthropic-sdk/sdk';
import { Database } from 'sqlite';
import { EnrichmentOutput } from './enrichment';

const client = new Anthropic();

export interface EvaluationOutput {
  jtbdAnalysis: string;
  disruptionScore: number;
  capabilitiesFit: 'strong' | 'developing' | 'missing';
  recommendation: 'build-now' | 'build-later' | 'partner' | 'skip';
  caseStudyMatches: string[];
  evaluationScore: number;
  rationale: string;
}

const EVALUATION_PROMPT = (
  idea: string,
  enrichedData: EnrichmentOutput
) => `
You are Clayton Christensen's innovation strategist. Analyze this idea using Jobs-to-be-Done, disruption theory, and capabilities fit.

IDEA: ${idea}

ENRICHED ANALYSIS:
- Category: ${enrichedData.category}
- Complexity: ${enrichedData.complexityScore}/1
- Market Gap: ${enrichedData.marketValidation.marketGap}
- Competitors: ${enrichedData.marketValidation.competitors.join(', ')}
- Technical Stack Fit: ${enrichedData.technicalFeasibility.stackFit}
- Estimated Effort: ${enrichedData.resourceEstimate.estimatedHours} hours

PROVIDE STRUCTURED EVALUATION:

1. JOBS-TO-BE-DONE ANALYSIS
   - What job is this solving?
   - Who has this job?
   - Current workarounds?

2. DISRUPTION POTENTIAL (0-1 scale)
   - Is this a low-end, mid-market, or high-end disruptor?
   - Timeline to impact?

3. CAPABILITIES FIT
   - Does our organization have the capabilities? (strong/developing/missing)
   - What capabilities are gaps?

4. RECOMMENDATION
   - build-now: Strategic imperative, resources available
   - build-later: Important but defer pending resources/market
   - partner: Better executed with external partner
   - skip: Misaligned with strategy or non-viable

5. RELEVANT CASE STUDIES
   - What Christensen case studies does this resemble?
   - What lessons apply?

PROVIDE JSON RESPONSE (no markdown):
{
  "jtbdAnalysis": "<paragraph on jobs being served>",
  "disruptionScore": <0-1>,
  "capabilitiesFit": "strong" or "developing" or "missing",
  "recommendation": "build-now" or "build-later" or "partner" or "skip",
  "caseStudyMatches": ["<case1>", "<case2>"],
  "evaluationScore": <0-100>,
  "rationale": "<paragraph explaining score and recommendation>"
}
`;

export async function evaluateIdea(
  idea: string,
  enrichedData: EnrichmentOutput
): Promise<EvaluationOutput> {
  try {
    const response = await client.messages.create({
      model: 'claude-3-5-sonnet-20241022',
      max_tokens: 1024,
      messages: [
        {
          role: 'user',
          content: EVALUATION_PROMPT(idea, enrichedData)
        }
      ]
    });

    const textContent = response.content.find((block) => block.type === 'text');
    if (!textContent || textContent.type !== 'text') {
      throw new Error('No text response from Claude');
    }

    const evaluationData = JSON.parse(textContent.text);
    return evaluationData as EvaluationOutput;
  } catch (error) {
    console.error('Evaluation failed:', error);
    throw new Error(
      `Failed to evaluate idea: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function saveEvaluation(
  db: Database,
  ideaId: string,
  evaluation: EvaluationOutput
): Promise<void> {
  await db.run(
    `
    INSERT OR REPLACE INTO idea_evaluation
    (idea_id, jtbd_analysis, disruption_score, capabilities_fit, strategic_recommendation, case_study_matches, evaluation_score, evaluated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `,
    [
      ideaId,
      evaluation.jtbdAnalysis,
      evaluation.disruptionScore,
      evaluation.capabilitiesFit,
      evaluation.recommendation,
      JSON.stringify(evaluation.caseStudyMatches),
      evaluation.evaluationScore,
      new Date().toISOString()
    ]
  );
}

export async function getEvaluation(
  db: Database,
  ideaId: string
): Promise<EvaluationOutput | null> {
  const row = await db.get(
    'SELECT * FROM idea_evaluation WHERE idea_id = ?',
    [ideaId]
  );

  if (!row) return null;

  return {
    jtbdAnalysis: row.jtbd_analysis,
    disruptionScore: row.disruption_score,
    capabilitiesFit: row.capabilities_fit,
    recommendation: row.strategic_recommendation,
    caseStudyMatches: JSON.parse(row.case_study_matches || '[]'),
    evaluationScore: row.evaluation_score,
    rationale: row.jtbd_analysis // Using JTBD as rationale for Phase 1
  };
}

export const ROUTING_THRESHOLDS = {
  BUILD_NOW: 80,
  BUILD_LATER: 60,
  RESEARCH: 40,
  ARCHIVE: 0
};

export function routeIdea(
  evaluationScore: number,
  recommendation: string
): 'GENERATE_BLUEPRINT' | 'DEFER_WITH_BLUEPRINT' | 'NEEDS_VALIDATION' | 'ARCHIVE_WITH_LEARNING' {
  if (
    evaluationScore >= ROUTING_THRESHOLDS.BUILD_NOW &&
    recommendation === 'build-now'
  ) {
    return 'GENERATE_BLUEPRINT';
  }

  if (evaluationScore >= ROUTING_THRESHOLDS.BUILD_LATER) {
    return 'DEFER_WITH_BLUEPRINT';
  }

  if (evaluationScore >= ROUTING_THRESHOLDS.RESEARCH) {
    return 'NEEDS_VALIDATION';
  }

  return 'ARCHIVE_WITH_LEARNING';
}
