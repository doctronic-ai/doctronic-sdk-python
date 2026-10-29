"""Create a user, open a chat, and stream the first assistant message in staging.

The docs quickstart (https://docs.doctronic.ai/docs/quickstart/), using the SDK. Run it from your
backend or a terminal, never a browser:

    export DOCTRONIC_API_TOKEN="replace-with-your-staging-token"
    python examples/quickstart.py
"""

from __future__ import annotations

import uuid

from doctronic import Doctronic
from doctronic.types import MessageContentEvent, MessageStartEvent, MessageStopEvent

# Reads DOCTRONIC_API_TOKEN, and DOCTRONIC_ENVIRONMENT (default: staging). Pass base_url= to send
# the requests somewhere else.
client = Doctronic()

# 1. Create a user. The SDK sends an Idempotency-Key and reuses it if it retries.
user = client.users.create(
    first_name="Avery",
    last_name="Chen",
    date_of_birth="1990-06-15",
    # Email and phone number must be unique per user, so each run uses a new email and no phone.
    email=f"avery+quickstart-{uuid.uuid4()}@example.com",
    sex="female",
)
# Save user.id on the patient record in your system.
patient = client.for_user(user.id)  # Every request from here on sends X-Doctronic-User-ID.

# 2. Create a chat.
chat = patient.chats.create(timezone="America/New_York")

# 3. Stream a patient turn. Leaving the `with` block closes the connection.
messages: dict[str, dict[str, str]] = {}
with patient.chats.stream(
    chat.id,
    user_input="I have had a sore throat and fever since yesterday.",
    timezone="America/New_York",
) as stream:
    for event in stream:
        if isinstance(event, MessageStartEvent):
            messages[event.message_id] = {"role": event.role, "text": ""}
        elif isinstance(event, MessageContentEvent):
            messages[event.message_id]["text"] += event.content
        elif isinstance(event, MessageStopEvent):
            print(messages[event.message_id])
        else:
            print(event.type, event)  # guardian, conversation.end, error, and any new event

client.close()
