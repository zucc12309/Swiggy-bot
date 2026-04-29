import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.adapters.base import Button, MessagingAdapter, OutboundMessage
from src.services.session import SessionService

logger = logging.getLogger(__name__)

FREQ_PATTERNS = [
    (r"every (\d+) days?", "days"),
    (r"every (\d+) weeks?", "weeks"),
    (r"every (\d+) months?", "months"),
    (r"(daily|every day)", "days"),
    (r"(weekly|every week)", "weeks"),
    (r"(fortnightly|every 2 weeks)", "weeks"),
    (r"(monthly|every month)", "months"),
]


def parse_frequency(text: str):
    text = text.lower().strip()
    for pattern, unit in FREQ_PATTERNS:
        m = re.search(pattern, text)
        if m:
            value = int(m.group(1)) if m.lastindex and m.group(1).isdigit() else (2 if "fortnight" in text else 1)
            return value, unit
    return None, None


async def handle_create_schedule_start(user_id: str, adapter: MessagingAdapter,
                                       session: SessionService) -> None:
    await session.update(user_id, {"state": "SCHEDULE_CREATE", "step": "name"})
    await adapter.send_message(user_id, OutboundMessage(
        text="📅 Let's set up an auto-restock schedule.\n\nWhat would you like to call this schedule? (e.g. *Weekly Veggies*, *Monthly Staples*)"
    ))


async def handle_schedule_name(user_id: str, name: str, adapter: MessagingAdapter,
                               session: SessionService) -> None:
    await session.update(user_id, {"schedule_name": name, "step": "frequency"})
    await adapter.send_message(user_id, OutboundMessage(
        text=f'✅ Got it — "{name}"\n\nHow often should this order repeat?\n\nExamples: *every 3 days*, *weekly*, *every 2 months*, *monthly*'
    ))


async def handle_schedule_frequency(user_id: str, text: str, adapter: MessagingAdapter,
                                    session: SessionService) -> None:
    value, unit = parse_frequency(text)
    if not value:
        await adapter.send_message(user_id, OutboundMessage(
            text="🤔 I didn't understand that frequency. Try something like *every 3 days*, *weekly*, or *monthly*."
        ))
        return

    await session.update(user_id, {"freq_value": value, "freq_unit": unit, "step": "items", "schedule_items": []})
    await adapter.send_message(user_id, OutboundMessage(
        text=f"⏱ Got it — every {value} {unit}.\n\nNow add items to your cart. Send them one by one or as a comma-separated list.\n\nWhen you're done, type *done*."
    ))


async def handle_schedule_items(user_id: str, text: str, adapter: MessagingAdapter,
                                session: SessionService) -> None:
    if text.lower().strip() == "done":
        await _confirm_schedule(user_id, adapter, session)
        return

    items = [i.strip() for i in text.split(",") if i.strip()]
    sess = await session.get(user_id)
    existing = sess.get("schedule_items", [])
    existing.extend(items)
    await session.update(user_id, {"schedule_items": existing})
    await adapter.send_message(user_id, OutboundMessage(
        text=f"✅ Added: {', '.join(items)}\n\nCurrent list: {', '.join(existing)}\n\nAdd more or type *done* to confirm."
    ))


async def _confirm_schedule(user_id: str, adapter: MessagingAdapter, session: SessionService) -> None:
    sess = await session.get(user_id)
    items = sess.get("schedule_items", [])
    name = sess.get("schedule_name")
    freq_value = sess.get("freq_value")
    freq_unit = sess.get("freq_unit")

    if not items:
        await adapter.send_message(user_id, OutboundMessage(text="⚠️ Please add at least one item before confirming."))
        return

    next_run = datetime.now(timezone.utc) + timedelta(days=freq_value if freq_unit == "days" else freq_value * 7)
    text = (f"📋 *Schedule Summary*\n\nName: {name}\nFrequency: Every {freq_value} {freq_unit}\n"
            f"Items ({len(items)}): {', '.join(items)}\nFirst order: {next_run.strftime('%d %b %Y')}")

    await session.update(user_id, {"step": "confirm", "next_run": next_run.isoformat()})
    await adapter.send_buttons(user_id, text, [
        [Button("✅ Confirm Schedule", "confirm_schedule"), Button("✏️ Edit", "edit_schedule")],
    ])
