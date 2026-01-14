"""Unified notification service for HIL gates."""

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

from .email import send_email_notification
from .slack import send_slack_notification

load_dotenv()
logger = logging.getLogger(__name__)


@dataclass
class NotificationContext:
    """Context for HIL gate notification."""

    idea_id: str
    title: str
    stage: str  # "evaluation" (Gate 1) or "scaffolding" (Gate 2)
    enrichment_summary: str | None = None
    evaluation_summary: str | None = None
    scaffolding_summary: str | None = None


@dataclass
class NotificationResult:
    """Result of notification attempt."""

    email_sent: bool = False
    slack_sent: bool = False
    email_error: str | None = None
    slack_error: str | None = None

    @property
    def any_sent(self) -> bool:
        return self.email_sent or self.slack_sent


class NotificationService:
    """Service for sending HIL gate notifications via multiple channels."""

    def __init__(self):
        self.email_enabled = bool(os.getenv("RESEND_API_KEY") and os.getenv("NOTIFY_EMAIL"))
        self.slack_enabled = bool(os.getenv("SLACK_WEBHOOK_URL"))

        if self.email_enabled:
            logger.info("Email notifications enabled (Resend)")
        else:
            logger.info("Email notifications disabled (missing RESEND_API_KEY or NOTIFY_EMAIL)")

        if self.slack_enabled:
            logger.info("Slack notifications enabled")
        else:
            logger.info("Slack notifications disabled (missing SLACK_WEBHOOK_URL)")

    async def notify_hil_gate(self, context: NotificationContext) -> NotificationResult:
        """Send notifications for HIL gate via all enabled channels.

        Args:
            context: The notification context with idea details

        Returns:
            NotificationResult with status of each channel
        """
        result = NotificationResult()

        gate_num = "1" if context.stage == "evaluation" else "2"
        logger.info(f"Sending HIL Gate {gate_num} notifications for: {context.title}")

        # Send email notification
        if self.email_enabled:
            try:
                result.email_sent = await send_email_notification(
                    idea_id=context.idea_id,
                    title=context.title,
                    stage=context.stage,
                    enrichment_summary=context.enrichment_summary,
                    evaluation_summary=context.evaluation_summary,
                    scaffolding_summary=context.scaffolding_summary,
                )
                if result.email_sent:
                    logger.info(f"Email notification sent for idea: {context.idea_id[:8]}")
            except Exception as e:
                result.email_error = str(e)
                logger.error(f"Email notification failed: {e}")

        # Send Slack notification
        if self.slack_enabled:
            try:
                result.slack_sent = await send_slack_notification(
                    idea_id=context.idea_id,
                    title=context.title,
                    stage=context.stage,
                    enrichment_summary=context.enrichment_summary,
                    evaluation_summary=context.evaluation_summary,
                    scaffolding_summary=context.scaffolding_summary,
                )
                if result.slack_sent:
                    logger.info(f"Slack notification sent for idea: {context.idea_id[:8]}")
            except Exception as e:
                result.slack_error = str(e)
                logger.error(f"Slack notification failed: {e}")

        # Log summary
        if result.any_sent:
            channels = []
            if result.email_sent:
                channels.append("email")
            if result.slack_sent:
                channels.append("slack")
            logger.info(f"Notifications sent via: {', '.join(channels)}")
        else:
            logger.warning("No notifications were sent (all channels failed or disabled)")

        return result


# Singleton instance
_notification_service: NotificationService | None = None


def get_notification_service() -> NotificationService:
    """Get the singleton notification service instance."""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service
