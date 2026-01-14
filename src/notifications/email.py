"""Email notifications via Resend API."""

import logging
import os
from datetime import datetime

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL")
FROM_EMAIL = os.getenv("FROM_EMAIL", "Idea Factory <notifications@resend.dev>")


def generate_hil_email_html(
    idea_id: str,
    title: str,
    stage: str,
    enrichment_summary: str | None = None,
    evaluation_summary: str | None = None,
    scaffolding_summary: str | None = None,
    api_base_url: str = "http://localhost:8000",
) -> str:
    """Generate HTML email for HIL gate notification."""

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Determine which HIL gate this is
    if stage == "evaluation":
        gate_name = "First Review Gate"
        gate_description = "Review enrichment and evaluation results before scaffolding."
        next_action = "Approve to generate project blueprint"
    else:
        gate_name = "Second Review Gate"
        gate_description = "Review scaffolding blueprint before building."
        next_action = "Approve to generate project files"

    sections = []

    if enrichment_summary:
        sections.append(f"""
        <div style="margin-bottom: 20px; padding: 15px; background: #f8f9fa; border-radius: 8px;">
            <h3 style="margin: 0 0 10px 0; color: #495057;">📝 Enrichment</h3>
            <p style="margin: 0; color: #212529; white-space: pre-wrap;">{enrichment_summary}</p>
        </div>
        """)

    if evaluation_summary:
        sections.append(f"""
        <div style="margin-bottom: 20px; padding: 15px; background: #f8f9fa; border-radius: 8px;">
            <h3 style="margin: 0 0 10px 0; color: #495057;">🎯 Evaluation</h3>
            <p style="margin: 0; color: #212529; white-space: pre-wrap;">{evaluation_summary}</p>
        </div>
        """)

    if scaffolding_summary:
        sections.append(f"""
        <div style="margin-bottom: 20px; padding: 15px; background: #f8f9fa; border-radius: 8px;">
            <h3 style="margin: 0 0 10px 0; color: #495057;">🏗️ Scaffolding</h3>
            <p style="margin: 0; color: #212529; white-space: pre-wrap;">{scaffolding_summary}</p>
        </div>
        """)

    sections_html = "\n".join(sections)

    return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 12px 12px 0 0; text-align: center;">
        <h1 style="color: white; margin: 0; font-size: 24px;">🏭 Idea Factory</h1>
        <p style="color: rgba(255,255,255,0.9); margin: 10px 0 0 0; font-size: 14px;">{gate_name}</p>
    </div>

    <div style="background: white; padding: 30px; border: 1px solid #e9ecef; border-top: none;">
        <h2 style="margin: 0 0 10px 0; color: #212529;">{title}</h2>
        <p style="color: #6c757d; margin: 0 0 20px 0; font-size: 14px;">
            ID: <code style="background: #f1f3f4; padding: 2px 6px; border-radius: 4px;">{idea_id[:8]}...</code>
        </p>

        <div style="background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin-bottom: 20px;">
            <strong style="color: #856404;">⏳ Awaiting Review</strong>
            <p style="margin: 5px 0 0 0; color: #856404;">{gate_description}</p>
        </div>

        {sections_html}

        <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e9ecef;">
            <p style="margin: 0 0 15px 0; color: #495057;"><strong>Next Action:</strong> {next_action}</p>

            <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; font-family: monospace; font-size: 13px;">
                <p style="margin: 0 0 10px 0; color: #6c757d;"># Approve</p>
                <code style="color: #28a745;">curl -X POST {api_base_url}/api/reviews/{idea_id} \\<br>
                &nbsp;&nbsp;-H "Content-Type: application/json" \\<br>
                &nbsp;&nbsp;-d '{{"decision": "approve"}}'</code>

                <p style="margin: 20px 0 10px 0; color: #6c757d;"># Reject</p>
                <code style="color: #dc3545;">curl -X POST {api_base_url}/api/reviews/{idea_id} \\<br>
                &nbsp;&nbsp;-H "Content-Type: application/json" \\<br>
                &nbsp;&nbsp;-d '{{"decision": "reject", "notes": "reason"}}'</code>
            </div>
        </div>
    </div>

    <div style="background: #f8f9fa; padding: 20px; border-radius: 0 0 12px 12px; text-align: center; border: 1px solid #e9ecef; border-top: none;">
        <p style="margin: 0; color: #6c757d; font-size: 12px;">
            Sent by Idea Factory at {timestamp}
        </p>
    </div>
</body>
</html>
"""


async def send_email_notification(
    idea_id: str,
    title: str,
    stage: str,
    enrichment_summary: str | None = None,
    evaluation_summary: str | None = None,
    scaffolding_summary: str | None = None,
) -> bool:
    """Send email notification for HIL gate.

    Args:
        idea_id: The idea UUID
        title: The idea title
        stage: Current pipeline stage (evaluation or scaffolding)
        enrichment_summary: Optional enrichment details
        evaluation_summary: Optional evaluation details
        scaffolding_summary: Optional scaffolding details

    Returns:
        True if email sent successfully, False otherwise
    """
    if not RESEND_API_KEY or not NOTIFY_EMAIL:
        logger.warning("Email notifications disabled: missing RESEND_API_KEY or NOTIFY_EMAIL")
        return False

    try:
        html = generate_hil_email_html(
            idea_id=idea_id,
            title=title,
            stage=stage,
            enrichment_summary=enrichment_summary,
            evaluation_summary=evaluation_summary,
            scaffolding_summary=scaffolding_summary,
        )

        # Determine subject based on gate
        if stage == "evaluation":
            subject = f"🏭 Review Required: {title} (Gate 1)"
        else:
            subject = f"🏭 Review Required: {title} (Gate 2)"

        payload = {
            "from": FROM_EMAIL,
            "to": [NOTIFY_EMAIL],
            "subject": subject,
            "html": html,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30.0,
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Email sent successfully: {result.get('id')}")
                return True
            else:
                logger.error(f"Failed to send email: {response.status_code} - {response.text}")
                return False

    except Exception as e:
        logger.error(f"Email notification error: {e}")
        return False
