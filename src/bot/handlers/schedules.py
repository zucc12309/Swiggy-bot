import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from src.adapters.base import Button, MessagingAdapter, OutboundMessage
from src.services.session import SessionService

logger = logging.getLogger(__name__)

FREQ_PATTERNS = [
    (r"every (\d+) days?", lambda m: (int(m.group(1)), "days", None)),
    (r"every (\d+) weeks?", lambda m: (int(m.group(1)), "weeks", None)),
    (r"every (\d+) months?", lambda m: (int(m.group(1)), "months", None)),
    (r"fortnightly|every 2 weeks", lambda m: (2, "weeks", None)),
    (r"daily|every day", lambda m: (1, "days", None)),
    (r"weekly|every week", lambda m: (1, "weeks", None)),
    (r"monthly|every month", lambda m: (1, "months", None)),
    (r"every (monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
     lambda m: (1, "weeks", m.group(1))),
    (r"on the (\d+)(?:st|nd|rd|th)? of every month",
     lambda m: (1, "months", m.group(1))),
]

MAX_SCHEDULES_PER_USER = 10

EDIT_OPTIONS = [
    [Button("➕ Add Item", "edit_add_item"), Button("➖ Remove Item", "edit_remove_item")],
    [Button("🔢 Change Quantity", "edit_change_qty"), Button("⏱ Change Frequency", "edit_change_freq")],
    [Button("✏️ Rename", "edit_rename"), Button("⏸ Pause", "sched_pause")],
    [Button("🗑 Cancel Schedule", "sched_cancel")],
]


def parse_frequency(text: str) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    text = text.lower().strip()
    for pattern, extractor in FREQ_PATTERNS:
        m = re.search(pattern, text)
        if m:
            return extractor(m)
    return None, None, None


def _calc_next_run(freq_value: int, freq_unit: str, anchor: Optional[str] = None) -> datetime:
    now = datetime.now(timezone.utc)
    if freq_unit == "days":
        return now + timedelta(days=freq_value)
    if freq_unit == "weeks":
        if anchor and anchor in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"):
            days_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                        "friday": 4, "saturday": 5, "sunday": 6}
            target = days_map[anchor]
            days_ahead = (target - now.weekday()) % 7 or 7
            return now + timedelta(days=days_ahead)
        return now + timedelta(weeks=freq_value)
    if freq_unit == "months":
        from dateutil.relativedelta import relativedelta
        if anchor and anchor.isdigit():
            day = int(anchor)
            next_month = now + relativedelta(months=1)
            return next_month.replace(day=min(day, 28))
        return now + relativedelta(months=freq_value)
    return now + timedelta(days=freq_value)


async def handle_create_schedule_start(user_id: str, adapter: MessagingAdapter,
                                       session: SessionService) -> None:
    sess = await session.get(user_id) or {}
    schedule_count = sess.get("schedule_count", 0)
    if schedule_count >= MAX_SCHEDULES_PER_USER:
        await adapter.send_message(user_id, OutboundMessage(
            text=f"⚠️ You have reached the maximum of {MAX_SCHEDULES_PER_USER} schedules. "
                 f"Delete or cancel an existing one before creating a new one."
        ))
        return

    await session.update(user_id, {"state": "SCHEDULE_CREATE", "step": "name"})
    await adapter.send_message(user_id, OutboundMessage(
        text="📅 Let's set up an auto-restock schedule.\n\nWhat would you like to call it?\n(e.g. *Weekly Veggies*, *Monthly Staples*)"
    ))


async def handle_schedule_name(user_id: str, name: str, adapter: MessagingAdapter,
                               session: SessionService) -> None:
    await session.update(user_id, {"schedule_name": name.strip(), "step": "frequency"})
    await adapter.send_message(user_id, OutboundMessage(
        text=f'✅ Got it — *"{name.strip()}"*\n\nHow often should this order repeat?\n\n'
             f'Examples: *every 3 days*, *weekly*, *every 2 months*, *monthly*, *every Monday*, *on the 1st of every month*'
    ))


async def handle_schedule_frequency(user_id: str, text: str, adapter: MessagingAdapter,
                                    session: SessionService) -> None:
    value, unit, anchor = parse_frequency(text)
    if not value:
        await adapter.send_message(user_id, OutboundMessage(
            text="🤔 I didn't understand that frequency.\n\nTry: *every 3 days*, *weekly*, *monthly*, *every Monday*, *on the 1st of every month*"
        ))
        return

    next_run = _calc_next_run(value, unit, anchor)
    await session.update(user_id, {
        "freq_value": value, "freq_unit": unit, "anchor_day": anchor,
        "next_run": next_run.isoformat(), "step": "items", "schedule_items": [],
    })
    await adapter.send_message(user_id, OutboundMessage(
        text=f"⏱ Every {value} {unit}{f' ({anchor})' if anchor else ''}.\n\n"
             f"Now add items. Send them one by one or as a comma-separated list.\n\n"
             f"Type *done* when finished."
    ))


async def handle_schedule_items(user_id: str, text: str, adapter: MessagingAdapter,
                                session: SessionService) -> None:
    if text.lower().strip() in ("done", "confirm", "finish"):
        await _confirm_schedule(user_id, adapter, session)
        return

    new_items = [i.strip() for i in text.split(",") if i.strip()]
    sess = await session.get(user_id)
    existing = sess.get("schedule_items", [])
    for item_name in new_items:
        existing.append({"name": item_name, "qty": 1, "unit": "pcs"})

    await session.update(user_id, {"schedule_items": existing})
    names = [i["name"] for i in existing]
    await adapter.send_message(user_id, OutboundMessage(
        text=f"✅ Added: *{', '.join(new_items)}*\n\n"
             f"Cart so far: {', '.join(names)}\n\n"
             f"Add more or type *done* to confirm."
    ))


async def _confirm_schedule(user_id: str, adapter: MessagingAdapter, session: SessionService) -> None:
    sess = await session.get(user_id)
    items = sess.get("schedule_items", [])
    name = sess.get("schedule_name", "My Schedule")
    freq_value = sess.get("freq_value")
    freq_unit = sess.get("freq_unit")
    anchor = sess.get("anchor_day")
    next_run_str = sess.get("next_run")

    if not items:
        await adapter.send_message(user_id, OutboundMessage(
            text="⚠️ Please add at least one item before confirming."
        ))
        return

    next_run_dt = datetime.fromisoformat(next_run_str)
    freq_label = f"Every {freq_value} {freq_unit}{f' ({anchor})' if anchor else ''}"
    items_text = "\n".join(f"  • {i['name']} × {i['qty']} {i['unit']}" for i in items)

    await session.update(user_id, {"step": "confirm"})
    await adapter.send_buttons(
        user_id,
        f"📋 *Schedule Summary*\n\n"
        f"Name: *{name}*\n"
        f"Frequency: {freq_label}\n"
        f"Items ({len(items)}):\n{items_text}\n\n"
        f"First order: *{next_run_dt.strftime('%d %b %Y')}*",
        [
            [Button("✅ Save Schedule", "confirm_schedule"), Button("✏️ Edit Items", "edit_items_again")],
            [Button("❌ Cancel", "cancel_schedule")],
        ],
    )


async def handle_list_schedules(user_id: str, adapter: MessagingAdapter,
                                session: SessionService) -> None:
    from src.db.database import AsyncSessionLocal
    from src.models.schedule import Schedule, ScheduleStatus
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        sess_db = await session.get(user_id)
        phone = (sess_db or {}).get("phone", user_id)
        result = await db.execute(
            select(Schedule).where(Schedule.user_phone == phone,
                                   Schedule.status == ScheduleStatus.ACTIVE)
        )
        schedules = result.scalars().all()

    if not schedules:
        await adapter.send_message(user_id, OutboundMessage(
            text="You have no active schedules. Type *auto restock* to create one."
        ))
        return

    lines = [f"{i + 1}. *{s.name}* — every {s.freq_value} {s.freq_unit.value}, "
             f"next: {s.next_run.strftime('%d %b')}"
             for i, s in enumerate(schedules)]
    buttons = [[Button(f"✏️ Edit {s.name}", f"edit_sched_{s.id}")] for s in schedules]

    await adapter.send_buttons(
        user_id,
        "📅 *Your Active Schedules*\n\n" + "\n".join(lines),
        buttons,
    )


async def handle_schedule_edit_start(user_id: str, schedule_id: int, adapter: MessagingAdapter,
                                     session: SessionService) -> None:
    await session.update(user_id, {"state": "SCHEDULE_EDIT", "editing_schedule_id": schedule_id})
    await adapter.send_buttons(user_id, "What would you like to edit?", EDIT_OPTIONS)


async def handle_schedule_control(user_id: str, action: str, adapter: MessagingAdapter,
                                  session: SessionService) -> None:
    """Handle SKIP / PAUSE / RESUME / CANCEL / DELAY controls."""
    sess = await session.get(user_id)
    schedule_id = sess.get("editing_schedule_id")
    if not schedule_id:
        await adapter.send_message(user_id, OutboundMessage(
            text="No schedule selected. Use /schedules to pick one."
        ))
        return

    from src.db.database import AsyncSessionLocal
    from src.models.schedule import Schedule, ScheduleStatus

    async with AsyncSessionLocal() as db:
        sched = await db.get(Schedule, schedule_id)
        if not sched:
            return

        if action == "pause":
            sched.status = ScheduleStatus.PAUSED
            msg = f"⏸ *{sched.name}* paused. Type *resume* to reactivate."
        elif action == "resume":
            sched.status = ScheduleStatus.ACTIVE
            from datetime import datetime, timezone
            next_run = _calc_next_run(sched.freq_value, sched.freq_unit.value, sched.anchor_day)
            sched.next_run = next_run
            msg = f"▶️ *{sched.name}* resumed. Next order: {next_run.strftime('%d %b %Y')}."
        elif action == "cancel":
            sched.status = ScheduleStatus.CANCELLED
            msg = f"🗑 *{sched.name}* cancelled permanently."
        elif action == "skip":
            next_run = _calc_next_run(sched.freq_value, sched.freq_unit.value, sched.anchor_day)
            sched.next_run = next_run
            msg = f"⏭ Next run skipped. Following order: {next_run.strftime('%d %b %Y')}."
        else:
            return

        await db.commit()

    await session.update(user_id, {"state": "IDLE", "editing_schedule_id": None})
    await adapter.send_message(user_id, OutboundMessage(text=msg))


async def handle_reminder_response(user_id: str, action: str, schedule_id: int,
                                   adapter: MessagingAdapter, session: SessionService) -> None:
    if action == "ok":
        await adapter.send_message(user_id, OutboundMessage(
            text="✅ Confirmed! Your order will be placed automatically at the scheduled time."
        ))
    elif action == "skip":
        await handle_schedule_control(user_id, "skip", adapter, session)
    elif action == "pause":
        await handle_schedule_control(user_id, "pause", adapter, session)
    elif action == "edit":
        await session.update(user_id, {"editing_schedule_id": schedule_id})
        await handle_schedule_edit_start(user_id, schedule_id, adapter, session)
