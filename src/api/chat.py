"""Chat API for idea vetting conversations.

Uses Claude Haiku for cost-effective idea refinement conversations.
"""

import json
import logging
import os
from typing import Annotated
from uuid import uuid4

from anthropic import Anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth.middleware import get_current_user, require_terms_accepted
from ..core.models import IdeaInput, User
from ..db.repository import repository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


# Conversation storage (in-memory for simplicity, could use Redis/DB)
conversations: dict[str, dict] = {}


class ChatMessage(BaseModel):
    """A chat message."""
    message: str = Field(..., min_length=1, max_length=5000)
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    """Response from chat endpoint."""
    message: str
    conversation_id: str
    idea_submitted: bool = False
    idea_id: str | None = None


# Vetting persona prompt
VETTING_PERSONA = """You are a pragmatic idea vetting assistant for Idea Factory. Your role:

- Help users refine rough ideas into buildable project specs
- Ask clarifying questions ONE AT A TIME (don't overwhelm)
- Push back on vague ideas with specific feedback
- Celebrate well-formed submissions

Your conversation flow:
1. Listen to the initial idea
2. Ask: "What problem does this solve?" (if not clear)
3. Ask: "Who would use this?" (if not clear)
4. Ask: "What's the simplest version that would be useful?"
5. Summarize and ask for confirmation

When you have enough information (problem, users, MVP scope), output a JSON block like this:
```json
{"ready_to_submit": true, "title": "...", "description": "...", "tags": ["tag1", "tag2"]}
```

Tone: Direct, helpful, efficient. Not gatekeeping - ensuring quality.

IMPORTANT: Be conversational and helpful. Don't be a bureaucrat. If the user has a clear, well-formed idea, don't force them through unnecessary questions."""


def get_anthropic_client() -> Anthropic:
    """Get Anthropic client."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")
    return Anthropic(api_key=api_key)


def extract_submission(text: str) -> dict | None:
    """Extract submission JSON from assistant response if present."""
    import re

    # Look for JSON block with ready_to_submit
    pattern = r'```json\s*(\{[^`]+\})\s*```'
    match = re.search(pattern, text)
    if match:
        try:
            data = json.loads(match.group(1))
            if data.get("ready_to_submit"):
                return data
        except json.JSONDecodeError:
            pass
    return None


@router.post("/vetting", response_model=ChatResponse)
async def vetting_chat(
    chat_input: ChatMessage,
    user: Annotated[User, Depends(require_terms_accepted)],
) -> ChatResponse:
    """Vetting chatbot endpoint.

    Processes user messages through Claude Haiku to refine ideas
    into structured submissions.
    """
    # Get or create conversation
    conv_id = chat_input.conversation_id or str(uuid4())

    if conv_id not in conversations:
        conversations[conv_id] = {
            "user_id": user.id,
            "messages": [],
            "submitted": False,
        }

    conv = conversations[conv_id]

    # Security: ensure user owns this conversation
    if conv["user_id"] != user.id:
        raise HTTPException(status_code=403, detail="Not your conversation")

    # Check if already submitted
    if conv["submitted"]:
        return ChatResponse(
            message="This idea has already been submitted. Start a new conversation for a new idea.",
            conversation_id=conv_id,
            idea_submitted=True,
        )

    # Add user message
    conv["messages"].append({
        "role": "user",
        "content": chat_input.message
    })

    try:
        # Call Claude Haiku
        client = get_anthropic_client()

        response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=1024,
            system=VETTING_PERSONA,
            messages=conv["messages"]
        )

        assistant_message = response.content[0].text

        # Add assistant response to history
        conv["messages"].append({
            "role": "assistant",
            "content": assistant_message
        })

        # Check if idea is ready to submit
        submission = extract_submission(assistant_message)

        if submission:
            # Create the idea
            idea_input = IdeaInput(
                title=submission.get("title", "Untitled Idea"),
                raw_content=submission.get("description", chat_input.message),
                tags=submission.get("tags", []),
            )

            idea = await repository.create_idea(idea_input, submitted_by=user.id)
            conv["submitted"] = True
            conv["idea_id"] = idea.id

            # Clean up the response (remove JSON block)
            clean_message = assistant_message.split("```json")[0].strip()
            if not clean_message:
                clean_message = f"Your idea '{idea.title}' has been submitted to the pipeline."

            return ChatResponse(
                message=clean_message,
                conversation_id=conv_id,
                idea_submitted=True,
                idea_id=idea.id,
            )

        return ChatResponse(
            message=assistant_message,
            conversation_id=conv_id,
            idea_submitted=False,
        )

    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")


@router.get("/vetting/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Get conversation history."""
    if conversation_id not in conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv = conversations[conversation_id]

    if conv["user_id"] != user.id:
        raise HTTPException(status_code=403, detail="Not your conversation")

    return {
        "conversation_id": conversation_id,
        "messages": conv["messages"],
        "submitted": conv["submitted"],
        "idea_id": conv.get("idea_id"),
    }


@router.delete("/vetting/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Delete a conversation."""
    if conversation_id not in conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv = conversations[conversation_id]

    if conv["user_id"] != user.id:
        raise HTTPException(status_code=403, detail="Not your conversation")

    del conversations[conversation_id]
    return {"deleted": True}
