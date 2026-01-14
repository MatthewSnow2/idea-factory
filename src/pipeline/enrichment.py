"""Enrichment pipeline stage using Gemini.

Takes raw idea input and produces enhanced description,
problem statement, and market context.
"""

import json
import logging
import os

import google.generativeai as genai
from dotenv import load_dotenv

from ..core.models import EnrichmentOutput, Idea

load_dotenv()
logger = logging.getLogger(__name__)

# Configure Gemini
genai.configure(api_key=os.getenv("GOOGLE_API_KEY", ""))

ENRICHMENT_PROMPT = """You are an expert product analyst and innovation strategist.
Analyze this idea and provide structured enrichment data.

IDEA TITLE: {title}

IDEA DESCRIPTION:
{raw_content}

TAGS: {tags}

Your task is to enhance this idea with deeper analysis. Provide a JSON response with this exact structure:

{{
  "enhanced_title": "<improved, more specific title>",
  "enhanced_description": "<2-3 paragraph comprehensive description of what this idea entails>",
  "problem_statement": "<clear articulation of the problem this solves>",
  "potential_solutions": [
    "<approach 1>",
    "<approach 2>",
    "<approach 3>"
  ],
  "market_context": "<analysis of market opportunity, competitors, and positioning>"
}}

Be specific and analytical. Focus on:
1. Clarifying the core value proposition
2. Identifying the target user/customer
3. Articulating the problem clearly
4. Suggesting concrete implementation approaches
5. Understanding the competitive landscape

Return ONLY valid JSON, no markdown code blocks or explanation.
"""


async def enrich_idea(idea: Idea) -> EnrichmentOutput:
    """Run enrichment stage on an idea.

    Args:
        idea: The idea to enrich

    Returns:
        EnrichmentOutput with enhanced analysis

    Raises:
        ValueError: If enrichment fails or returns invalid data
    """
    logger.info(f"Starting enrichment for idea: {idea.id}")

    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = ENRICHMENT_PROMPT.format(
        title=idea.title,
        raw_content=idea.raw_content,
        tags=", ".join(idea.tags) if idea.tags else "None",
    )

    try:
        response = await model.generate_content_async(prompt)
        response_text = response.text.strip()

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

        output = EnrichmentOutput(
            enhanced_title=data["enhanced_title"],
            enhanced_description=data["enhanced_description"],
            problem_statement=data["problem_statement"],
            potential_solutions=data["potential_solutions"],
            market_context=data["market_context"],
        )

        logger.info(f"Enrichment completed for idea: {idea.id}")
        return output

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse enrichment response: {e}")
        raise ValueError(f"Invalid enrichment response format: {e}")
    except KeyError as e:
        logger.error(f"Missing field in enrichment response: {e}")
        raise ValueError(f"Missing required field in enrichment: {e}")
    except Exception as e:
        logger.error(f"Enrichment failed: {e}")
        raise ValueError(f"Enrichment failed: {e}")
