"""Evaluation pipeline stage using Christensen MCP.

Takes enriched idea and produces strategic evaluation
using Jobs-to-be-Done and disruption theory frameworks.
"""

import logging

from ..core.models import (
    CapabilitiesFit,
    EnrichmentResult,
    EvaluationOutput,
    EvaluationScores,
    Idea,
    Recommendation,
)
from ..mcp.bridge import ChristensenAnalyzer, MCPToolResult

logger = logging.getLogger(__name__)


async def evaluate_idea(idea: Idea, enrichment: EnrichmentResult) -> EvaluationOutput:
    """Run evaluation stage on an enriched idea.

    Uses Christensen MCP to apply Jobs-to-be-Done and
    disruption theory frameworks.

    Args:
        idea: The original idea
        enrichment: The enrichment result

    Returns:
        EvaluationOutput with strategic analysis

    Raises:
        ValueError: If evaluation fails
    """
    logger.info(f"Starting evaluation for idea: {idea.id}")

    # Build evaluation context from enrichment
    scenario = f"""
IDEA: {enrichment.enhanced_title}

DESCRIPTION:
{enrichment.enhanced_description}

PROBLEM STATEMENT:
{enrichment.problem_statement}

POTENTIAL APPROACHES:
{chr(10).join(f"- {s}" for s in enrichment.potential_solutions)}

MARKET CONTEXT:
{enrichment.market_context}
"""

    try:
        async with ChristensenAnalyzer() as analyzer:
            # Call Christensen MCP for analysis
            result = await analyzer.analyze_decision(
                scenario=scenario,
                context=f"Original idea: {idea.raw_content}",
                constraints=idea.tags if idea.tags else None,
            )

            if not result.success:
                raise ValueError(f"Christensen analysis failed: {result.error}")

            # Parse the Christensen response
            output = _parse_christensen_response(result)
            logger.info(f"Evaluation completed for idea: {idea.id}")
            return output

    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        raise ValueError(f"Evaluation failed: {e}")


def _parse_christensen_response(result: MCPToolResult) -> EvaluationOutput:
    """Parse Christensen MCP response into EvaluationOutput.

    The Christensen MCP returns structured analysis that we
    map to our evaluation model.
    """
    content = result.content

    # Handle different response formats
    if isinstance(content, dict):
        return _parse_dict_response(content)
    elif isinstance(content, str):
        return _parse_text_response(content)
    else:
        raise ValueError(f"Unexpected response format: {type(content)}")


def _parse_dict_response(data: dict) -> EvaluationOutput:
    """Parse dictionary response from Christensen MCP."""
    # Map Christensen output fields to our model
    jtbd = data.get("jobs_to_be_done", data.get("jtbd_analysis", ""))
    disruption = data.get("disruption_analysis", data.get("disruption_potential", ""))

    # Extract scores
    disruption_score = data.get("disruption_score", 0.5)
    if isinstance(disruption_score, str):
        disruption_score = float(disruption_score.replace("%", "")) / 100

    overall_score = data.get("overall_score", data.get("score", 50))
    if isinstance(overall_score, str):
        overall_score = float(overall_score.replace("%", ""))

    # Map capabilities fit
    cap_fit_raw = data.get("capabilities_fit", data.get("fit", "developing"))
    cap_fit = _map_capabilities_fit(cap_fit_raw)

    # Map recommendation
    rec_raw = data.get("recommendation", data.get("action", "refine"))
    recommendation = _map_recommendation(rec_raw)

    return EvaluationOutput(
        jtbd_analysis=jtbd if isinstance(jtbd, str) else str(jtbd),
        disruption_potential=disruption if isinstance(disruption, str) else str(disruption),
        scores=EvaluationScores(
            disruption_score=min(max(disruption_score, 0.0), 1.0),
            overall_score=min(max(overall_score, 0.0), 100.0),
        ),
        capabilities_fit=cap_fit,
        recommendation=recommendation,
        recommendation_rationale=data.get("rationale", data.get("recommendation_rationale", "")),
        key_risks=data.get("risks", data.get("key_risks", [])),
        case_study_matches=data.get("case_studies", data.get("case_study_matches", [])),
    )


def _parse_text_response(text: str) -> EvaluationOutput:
    """Parse text response from Christensen MCP.

    Falls back to extracting what we can from unstructured text.
    """
    # Default structured response for text output
    return EvaluationOutput(
        jtbd_analysis=text,
        disruption_potential="Analysis provided in text format",
        scores=EvaluationScores(
            disruption_score=0.5,
            overall_score=50.0,
        ),
        capabilities_fit=CapabilitiesFit.DEVELOPING,
        recommendation=Recommendation.REFINE,
        recommendation_rationale="Requires human review of text analysis",
        key_risks=["Text-based analysis requires human interpretation"],
        case_study_matches=[],
    )


def _map_capabilities_fit(value: str) -> CapabilitiesFit:
    """Map string value to CapabilitiesFit enum."""
    value_lower = value.lower() if isinstance(value, str) else "developing"

    if "strong" in value_lower or "high" in value_lower:
        return CapabilitiesFit.STRONG
    elif "missing" in value_lower or "low" in value_lower or "none" in value_lower:
        return CapabilitiesFit.MISSING
    else:
        return CapabilitiesFit.DEVELOPING


def _map_recommendation(value: str) -> Recommendation:
    """Map string value to Recommendation enum."""
    value_lower = value.lower() if isinstance(value, str) else "refine"

    if any(w in value_lower for w in ["develop", "build", "proceed", "yes", "approve"]):
        return Recommendation.DEVELOP
    elif any(w in value_lower for w in ["reject", "no", "skip", "abandon"]):
        return Recommendation.REJECT
    elif any(w in value_lower for w in ["defer", "wait", "later", "pause"]):
        return Recommendation.DEFER
    else:
        return Recommendation.REFINE
