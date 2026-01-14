"""Slack notifications via Webhook URL."""

import logging
import os
from datetime import datetime

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")


def build_slack_blocks(
    idea_id: str,
    title: str,
    stage: str,
    enrichment_summary: str | None = None,
    evaluation_summary: str | None = None,
    scaffolding_summary: str | None = None,
) -> list[dict]:
    """Build Slack Block Kit message for HIL gate notification."""

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Determine which HIL gate
    if stage == "evaluation":
        gate_emoji = "1️⃣"
        gate_name = "First Review Gate"
        gate_description = "Enrichment & evaluation complete. Review before scaffolding."
    else:
        gate_emoji = "2️⃣"
        gate_name = "Second Review Gate"
        gate_description = "Scaffolding complete. Review blueprint before building."

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🏭 Idea Factory - {gate_name}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{title}*\n`{idea_id[:8]}...`",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"{gate_emoji} {gate_description}",
                }
            ],
        },
        {"type": "divider"},
    ]

    # Add enrichment section if available
    if enrichment_summary:
        # Truncate if too long for Slack
        summary = enrichment_summary[:500] + "..." if len(enrichment_summary) > 500 else enrichment_summary
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*📝 Enrichment*\n{summary}",
            },
        })

    # Add evaluation section if available
    if evaluation_summary:
        summary = evaluation_summary[:500] + "..." if len(evaluation_summary) > 500 else evaluation_summary
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🎯 Evaluation*\n{summary}",
            },
        })

    # Add scaffolding section if available (Gate 2)
    if scaffolding_summary:
        summary = scaffolding_summary[:500] + "..." if len(scaffolding_summary) > 500 else scaffolding_summary
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🏗️ Scaffolding*\n{summary}",
            },
        })

    blocks.append({"type": "divider"})

    # Add action hints
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "*Actions*\n```"
                    f"# Approve\n"
                    f"curl -X POST http://localhost:8000/api/reviews/{idea_id} \\\n"
                    f"  -H 'Content-Type: application/json' \\\n"
                    f"  -d '{{\"decision\": \"approve\"}}'\n\n"
                    f"# Reject\n"
                    f"curl -X POST http://localhost:8000/api/reviews/{idea_id} \\\n"
                    f"  -H 'Content-Type: application/json' \\\n"
                    f"  -d '{{\"decision\": \"reject\", \"notes\": \"reason\"}}'```",
        },
    })

    # Footer
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"⏰ {timestamp}",
            }
        ],
    })

    return blocks


async def send_slack_notification(
    idea_id: str,
    title: str,
    stage: str,
    enrichment_summary: str | None = None,
    evaluation_summary: str | None = None,
    scaffolding_summary: str | None = None,
) -> bool:
    """Send Slack notification for HIL gate.

    Args:
        idea_id: The idea UUID
        title: The idea title
        stage: Current pipeline stage (evaluation or scaffolding)
        enrichment_summary: Optional enrichment details
        evaluation_summary: Optional evaluation details
        scaffolding_summary: Optional scaffolding details

    Returns:
        True if notification sent successfully, False otherwise
    """
    if not SLACK_WEBHOOK_URL:
        logger.warning("Slack notifications disabled: missing SLACK_WEBHOOK_URL")
        return False

    try:
        blocks = build_slack_blocks(
            idea_id=idea_id,
            title=title,
            stage=stage,
            enrichment_summary=enrichment_summary,
            evaluation_summary=evaluation_summary,
            scaffolding_summary=scaffolding_summary,
        )

        payload = {
            "blocks": blocks,
            "text": f"🏭 Idea Factory: Review required for '{title}'",  # Fallback
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                SLACK_WEBHOOK_URL,
                json=payload,
                timeout=30.0,
            )

            if response.status_code == 200:
                logger.info(f"Slack notification sent for idea: {idea_id[:8]}")
                return True
            else:
                logger.error(f"Failed to send Slack notification: {response.status_code} - {response.text}")
                return False

    except Exception as e:
        logger.error(f"Slack notification error: {e}")
        return False
