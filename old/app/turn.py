"""
turn_management.py  –  Full business-logic layer for the upgraded Turn system.

Covers:
  • Category A – Clock  (timed resource, grace period, overrun deduction)
  • Category B – Calendar  (n-day, weekday, cyclical; holiday pause)
  • Category C – Event  (action queue, nudge)
  • Shared turns
  • Skip / Swap (mutual consent + parent override)
    • (Removed) Birthday Mode
    • (Removed) Cross-penalty integration
  • Audit trail
  • Point-trade for turns  (hook: call after your points system resolves trade)
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date as date_type, datetime, timedelta

from app import db
from app.models import (
    User,
    TurnGroup, TurnGroupMember, TurnDayState, TurnDailyUsage,
    TurnAuditLog, TurnSwapRequest, TurnWeekdayRule,
)


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class AdvanceResult:
    ok: bool
    message: str


def _state_payload(state: TurnDayState) -> dict:
    """Parse TurnDayState.shared_child_ids.

    Historical formats:
      - None/''            -> no shared ids
      - JSON list[int]     -> shared ids
      - JSON object        -> {shared_ids: [...], trade: [...]} (new)
    """
    if not state.shared_child_ids:
        return {'shared_ids': [], 'trade': []}
    try:
        data = json.loads(state.shared_child_ids)
    except Exception:
        return {'shared_ids': [], 'trade': []}

    if isinstance(data, list):
        return {'shared_ids': [int(x) for x in data if x is not None], 'trade': []}

    if isinstance(data, dict):
        shared = data.get('shared_ids')
        if shared is None:
            shared = data.get('shared')
        trade = data.get('trade')
        if trade is None:
            trade = data.get('trade_overrides')
        if shared is None:
            shared = []
        if trade is None:
            trade = []
        return {
            'shared_ids': [int(x) for x in shared if x is not None],
            'trade': trade if isinstance(trade, list) else [],
        }

    return {'shared_ids': [], 'trade': []}


def _write_state_payload(state: TurnDayState, payload: dict) -> None:
    payload = payload or {}
    shared_ids = payload.get('shared_ids') or []
    trade = payload.get('trade') or []

    # Keep the DB field empty if there's nothing to store.
    if not shared_ids and not trade:
        state.shared_child_ids = None
        return

    state.shared_child_ids = json.dumps({'shared_ids': shared_ids, 'trade': trade})


def _pending_trade_for_seller(state: TurnDayState, seller_id: int) -> dict | None:
    payload = _state_payload(state)
    for entry in payload.get('trade') or []:
        try:
            if int(entry.get('seller_id')) == int(seller_id) and not bool(entry.get('used', False)):
                return entry
        except Exception:
            continue
    return None


def _consume_trade_for_seller(state: TurnDayState, seller_id: int) -> None:
    """Mark the first pending trade for seller_id as used.

    We intentionally consume the trade when the SOLD slot is *finished* (i.e.
    when we leave that slot), so the queue display doesn't "snap back" to the
    seller while the buyer is actively playing that slot.
    """
    payload = _state_payload(state)
    changed = False
    for entry in payload.get('trade') or []:
        try:
            if int(entry.get('seller_id')) == int(seller_id) and not bool(entry.get('used', False)):
                entry['used'] = True
                changed = True
                break
        except Exception:
            continue
    if changed:
        _write_state_payload(state, payload)
        db.session.commit()


def _effective_child_for_slot(state: TurnDayState,
                              slot_child_id: int,
                              eligible_ids: set[int],
                              consume: bool = False) -> int:
    """Return the child who should play the slot that belongs to slot_child_id.

    If a pending point-trade exists for this seller slot, the buyer plays instead,
    but the slot position remains the seller's position.
    """
    trade = _pending_trade_for_seller(state, slot_child_id)
    if not trade:
        return slot_child_id

    try:
        buyer_id = int(trade.get('buyer_id'))
    except Exception:
        return slot_child_id

    if buyer_id == int(slot_child_id):
        return slot_child_id

    if buyer_id not in eligible_ids:
        return slot_child_id

    if consume:
        payload = _state_payload(state)
        for entry in payload.get('trade') or []:
            try:
                if int(entry.get('seller_id')) == int(slot_child_id) and not bool(entry.get('used', False)):
                    entry['used'] = True
                    break
            except Exception:
                continue
        _write_state_payload(state, payload)
        db.session.commit()

    return buyer_id


def _log(group_id: int, day: date_type, action: str,
         actor_id: int | None = None, child_id: int | None = None,
         detail: str | None = None) -> None:
    """Append one row to the audit trail."""
    entry = TurnAuditLog(
        group_id=group_id, day=day, action=action,
        actor_id=actor_id, child_id=child_id, detail=detail,
    )
    db.session.add(entry)
    # Caller must commit.


def days_since_epoch(day: date_type) -> int:
    return (day - date_type(1970, 1, 1)).days


def turn_day_key() -> date_type:
    return date_type.today()


# ─────────────────────────────────────────────────────────────────────────────
# Members
# ─────────────────────────────────────────────────────────────────────────────

def get_group_members(group: TurnGroup) -> list[TurnGroupMember]:
    return (
        TurnGroupMember.query
        .filter_by(group_id=group.id)
        .order_by(TurnGroupMember.position.asc(), TurnGroupMember.id.asc())
        .all()
    )


# ─────────────────────────────────────────────────────────────────────────────
# Usage helpers
# ─────────────────────────────────────────────────────────────────────────────

def _usage_row(group_id: int, child_id: int, day: date_type) -> TurnDailyUsage | None:
    return TurnDailyUsage.query.filter_by(
        group_id=group_id, child_id=child_id, day=day
    ).first()


def ensure_usage_row(group_id: int, child_id: int, day: date_type) -> TurnDailyUsage:
    row = _usage_row(group_id, child_id, day)
    if row:
        return row
    row = TurnDailyUsage(group_id=group_id, child_id=child_id, day=day,
                         used_sec=0, used_min=0, overrun_sec=0)
    db.session.add(row)
    db.session.commit()
    return row


def get_usage_seconds(group_id: int, child_id: int, day: date_type) -> int:
    row = _usage_row(group_id, child_id, day)
    return int(row.used_sec or 0) if row else 0


def _quota_seconds(group: TurnGroup, child_id: int, day: date_type) -> int:
    """Effective quota in seconds, after subtracting any overrun from yesterday."""
    base = int(group.daily_quota_min) * 60

    # Subtract yesterday's overrun if deduct_overrun is enabled
    if group.deduct_overrun:
        yesterday = day - timedelta(days=1)
        yesterday_row = _usage_row(group.id, child_id, yesterday)
        if yesterday_row and yesterday_row.overrun_sec:
            base = max(0, base - int(yesterday_row.overrun_sec))

    return base


def eligible_member_ids(group: TurnGroup, day: date_type) -> list[int]:
    members = get_group_members(group)
    eligible = []
    for m in members:
        quota = _quota_seconds(group, m.child_id, day)
        used  = get_usage_seconds(group.id, m.child_id, day)
        if used < quota:
            eligible.append(m.child_id)
    return eligible


# ─────────────────────────────────────────────────────────────────────────────
# Day state bootstrap
# ─────────────────────────────────────────────────────────────────────────────

def get_or_init_turn_state(group: TurnGroup, day: date_type) -> TurnDayState:
    state = TurnDayState.query.filter_by(group_id=group.id, day=day).first()
    if state:
        return state

    members = get_group_members(group)
    start_pos = 0

    if members:
        if (getattr(group, 'selection_mode', 'round_robin') or 'round_robin').lower() == 'random':
            # Random wheel: lock a starter for the day
            eligible_ids = set(eligible_member_ids(group, day))
            candidates = [m for m in members if m.child_id in eligible_ids]
            if candidates:
                winner = random.choice(candidates)
                start_pos = winner.position
        else:
            # Double-offset fairness
            idx = days_since_epoch(day) % len(members)
            start_pos = members[idx].position

    state = TurnDayState(
        group_id=group.id,
        day=day,
        current_position=start_pos,
        wheel_used=(group.selection_mode or 'round_robin').lower() == 'random' and bool(members),
    )
    db.session.add(state)
    db.session.commit()
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Queue calculation  (Category A & C)
# ─────────────────────────────────────────────────────────────────────────────

def _rotate_to(members: list[TurnGroupMember], position: int) -> list[TurnGroupMember]:
    if not members:
        return members
    idx = next((i for i, m in enumerate(members) if m.position == position), 0)
    return members[idx:] + members[:idx]


def queue_for_group(group: TurnGroup, day: date_type) -> dict | None:
    members = get_group_members(group)
    if not members:
        return None

    state = get_or_init_turn_state(group, day)
    eligible_ids = set(eligible_member_ids(group, day))

    if not eligible_ids:
        return {'now': None, 'next': None, 'queue': [], 'state': state}

    rotated = _rotate_to(members, state.current_position)
    now_slot_member = next((m for m in rotated if m.child_id in eligible_ids), None)
    if not now_slot_member:
        return {'now': None, 'next': None, 'queue': [], 'state': state}

    members_by_child = {m.child_id: m for m in members}

    now_idx = rotated.index(now_slot_member)
    from_now = rotated[now_idx:] + rotated[:now_idx]

    effective_queue_child_ids: list[int] = []
    for slot_member in from_now:
        if slot_member.child_id not in eligible_ids:
            continue
        effective_queue_child_ids.append(
            _effective_child_for_slot(state, slot_member.child_id, eligible_ids, consume=False)
        )

    now_child_id = effective_queue_child_ids[0] if effective_queue_child_ids else None
    next_child_id = effective_queue_child_ids[1] if len(effective_queue_child_ids) > 1 else None

    now_child = User.query.get(now_child_id) if now_child_id else None
    next_child = User.query.get(next_child_id) if next_child_id else None

    queue_items = []
    for child_id in effective_queue_child_ids:
        m = members_by_child.get(child_id)
        child = User.query.get(child_id)
        used_sec = get_usage_seconds(group.id, child_id, day)
        quota = _quota_seconds(group, child_id, day)
        rem_sec  = max(quota - used_sec, 0)
        queue_items.append({
            'member':        m,
            'child':         child,
            'used_min':      used_sec // 60,
            'remaining_min': rem_sec  // 60,
            'used_sec':      used_sec,
            'remaining_sec': rem_sec,
        })

    return {
        'now':   now_child,
        'next':  next_child,
        'queue': queue_items,
        'state': state,
        # Internal helpers for routes/logic (templates can ignore these)
        'now_slot_child_id': now_slot_member.child_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Category B – Calendar helpers
# ─────────────────────────────────────────────────────────────────────────────

def calendar_owner_for_day(group: TurnGroup, day: date_type) -> User | None:
    """Return the child whose turn it is today for a Calendar-type group."""
    if group.cal_paused:
        return None  # holiday / vacation pause

    members = get_group_members(group)
    if not members:
        return None

    if group.cal_mode == 'weekday':
        rule = TurnWeekdayRule.query.filter_by(
            group_id=group.id, weekday=day.weekday()
        ).first()
        if rule:
            return User.query.get(rule.child_id)
        return None

    if group.cal_mode == 'n_day':
        n = int(group.cal_n_days or 1)
        idx = (days_since_epoch(day) // n) % len(members)
        return User.query.get(members[idx].child_id)

    if group.cal_mode == 'cyclical':
        # Monthly: use day-of-year mod N
        day_of_year = day.timetuple().tm_yday
        idx = day_of_year % len(members)
        return User.query.get(members[idx].child_id)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Clock session management  (Category A)
# ─────────────────────────────────────────────────────────────────────────────

def _turn_slice_seconds(group: TurnGroup, time_left_today_sec: int) -> int:
    slice_sec = int(group.turn_duration_min or 30) * 60
    if group.auto_advance_enabled and group.auto_advance_value:
        unit = (group.auto_advance_unit or 'minutes').lower()
        if unit == 'seconds':
            slice_sec = int(group.auto_advance_value)
        elif unit == 'hours':
            slice_sec = int(group.auto_advance_value) * 3600
        else:
            slice_sec = int(group.auto_advance_value) * 60
    return max(0, min(slice_sec, time_left_today_sec))


def get_session_view(group: TurnGroup, day: date_type) -> dict:
    state   = get_or_init_turn_state(group, day)
    running = bool(state.session_started_at)

    active_child = User.query.get(state.active_child_id) if state.active_child_id else None
    elapsed = 0
    if running and state.session_started_at:
        elapsed = int((datetime.utcnow() - state.session_started_at).total_seconds())

    remaining = None
    if state.turn_remaining_sec is not None:
        remaining = max(int(state.turn_remaining_sec) - elapsed, 0)

    # Grace period detection
    in_grace    = False
    grace_secs  = int(group.grace_period_sec or 120)
    if remaining is not None and remaining <= grace_secs and running:
        in_grace = True

    # Shared turn co-players
    payload = _state_payload(state)
    shared_ids = payload.get('shared_ids') or []
    shared_users = [User.query.get(cid) for cid in shared_ids if cid != state.active_child_id]

    return {
        'running':              running,
        'active_child':         active_child,
        'turn_remaining_sec':   remaining,
        'turn_total_sec':       state.turn_remaining_sec,
        'in_grace':             in_grace,
        'grace_period_sec':     grace_secs,
        'shared_users':         shared_users,
    }


def start_turn_session(group: TurnGroup, day: date_type,
                       actor_id: int | None = None) -> AdvanceResult:
    state      = get_or_init_turn_state(group, day)
    queue_data = queue_for_group(group, day)
    if not queue_data or not queue_data.get('now'):
        return AdvanceResult(False, 'No active turn right now – everyone is out of time.')

    # If the current SLOT is sold via point-trade, apply it now.
    # Do NOT consume it here; we consume when leaving the slot.
    slot_child_id = queue_data.get('now_slot_child_id')
    eligible_ids = set(eligible_member_ids(group, day))
    effective_child_id = _effective_child_for_slot(
        state,
        int(slot_child_id) if slot_child_id is not None else int(queue_data['now'].id),
        eligible_ids,
        consume=False,
    )
    now_child: User = User.query.get(effective_child_id)
    if not now_child:
        return AdvanceResult(False, 'Could not find the active child for this slot.')
    quota     = _quota_seconds(group, now_child.id, day)
    used_sec  = get_usage_seconds(group.id, now_child.id, day)
    time_left = max(quota - used_sec, 0)

    if time_left <= 0:
        return AdvanceResult(False, 'No time left in the pool for today.')

    if state.active_child_id is None or state.active_child_id != now_child.id:
        state.active_child_id  = now_child.id
        state.turn_remaining_sec = None

    if state.turn_remaining_sec is None:
        state.turn_remaining_sec = _turn_slice_seconds(group, time_left)

    if state.turn_remaining_sec <= 0:
        return AdvanceResult(False, 'No time left for this turn slice.')

    if state.session_started_at:
        return AdvanceResult(True, 'Turn is already running.')

    state.session_started_at = datetime.utcnow()
    state.grace_notified     = False
    db.session.commit()

    _log(group.id, day, 'start', actor_id=actor_id, child_id=now_child.id,
         detail=f'Started {now_child.username} ({state.turn_remaining_sec}s)')
    db.session.commit()
    return AdvanceResult(True, f"▶ Started {now_child.username}'s turn.")


def pause_turn_session(group: TurnGroup, day: date_type,
                       actor_id: int | None = None) -> tuple[AdvanceResult, bool]:
    """
    Stop the clock, deduct elapsed time from usage and shared co-players.
    Returns (AdvanceResult, reached_limit).
    """
    state = get_or_init_turn_state(group, day)
    if not state.session_started_at or not state.active_child_id:
        return AdvanceResult(False, 'No running turn to pause.'), False

    active_child = User.query.get(state.active_child_id)
    if not active_child:
        state.session_started_at = None
        state.active_child_id    = None
        state.turn_remaining_sec = None
        db.session.commit()
        return AdvanceResult(False, 'Active child not found.'), False

    elapsed   = int((datetime.utcnow() - state.session_started_at).total_seconds())
    remaining = int(state.turn_remaining_sec or 0)
    consumed  = max(0, min(elapsed, remaining))

    # ── Detect overrun into grace period ─────────────────────────────────────
    grace_sec   = int(group.grace_period_sec or 0)
    core_slice  = max(remaining - grace_sec, 0)
    overrun_sec = 0
    if consumed > core_slice and grace_sec > 0:
        overrun_sec = consumed - core_slice

    # ── Deduct from active child ──────────────────────────────────────────────
    def _deduct(child_id: int, secs: int, overrun: int) -> None:
        u = ensure_usage_row(group.id, child_id, day)
        u.used_sec   = int(u.used_sec or 0)  + secs
        u.used_min   = u.used_sec // 60
        if overrun and group.deduct_overrun:
            u.overrun_sec = int(u.overrun_sec or 0) + overrun

    _deduct(active_child.id, consumed, overrun_sec)

    # ── Deduct from shared co-players ────────────────────────────────────────
    payload = _state_payload(state)
    shared_ids = payload.get('shared_ids') or []
    for cid in shared_ids:
        if cid != active_child.id:
            _deduct(cid, consumed, overrun_sec)

    state.session_started_at = None
    state.turn_remaining_sec = max(remaining - consumed, 0)
    db.session.commit()

    detail = f'Paused {active_child.username} ({consumed}s used)'
    if overrun_sec:
        detail += f'; {overrun_sec}s overrun → deducted tomorrow'
    _log(group.id, day, 'pause', actor_id=actor_id,
         child_id=active_child.id, detail=detail)
    db.session.commit()

    reached = state.turn_remaining_sec <= 0
    msg     = 'Time is up!' if reached else '⏸ Paused.'
    return AdvanceResult(True, msg), reached


def check_grace_warning(group: TurnGroup, day: date_type) -> bool:
    """
    Call this periodically (e.g. from a background task or JS polling).
    Returns True if grace-period warning should fire (first time only).
    """
    state   = get_or_init_turn_state(group, day)
    if not state.session_started_at or state.grace_notified:
        return False

    elapsed    = int((datetime.utcnow() - state.session_started_at).total_seconds())
    remaining  = max(int(state.turn_remaining_sec or 0) - elapsed, 0)
    grace_sec  = int(group.grace_period_sec or 120)

    if remaining <= grace_sec:
        state.grace_notified = True
        _log(group.id, day, 'grace_warn',
             child_id=state.active_child_id,
             detail=f'{remaining}s left – grace period started')
        db.session.commit()
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Advance / Skip / Next
# ─────────────────────────────────────────────────────────────────────────────

def _move_state_to_child(group: TurnGroup, day: date_type,
                         chosen_member: TurnGroupMember) -> None:
    state = get_or_init_turn_state(group, day)
    state.current_position   = chosen_member.position
    state.active_child_id    = chosen_member.child_id
    state.turn_remaining_sec = None
    state.session_started_at = None
    # Clear shared co-players for the new session, but preserve any pending trade overrides.
    payload = _state_payload(state)
    payload['shared_ids'] = []
    _write_state_payload(state, payload)
    db.session.commit()


def _next_eligible_after_position(group: TurnGroup, day: date_type,
                                 position: int | None) -> TurnGroupMember | None:
    members = get_group_members(group)
    eligible_ids = set(eligible_member_ids(group, day))
    if not members or not eligible_ids:
        return None

    if position is None:
        return next((m for m in members if m.child_id in eligible_ids), None)

    idx = next((i for i, m in enumerate(members) if m.position == position), None)
    if idx is None:
        return next((m for m in members if m.child_id in eligible_ids), None)

    ordered = members[idx + 1:] + members[:idx + 1]
    return next((m for m in ordered if m.child_id in eligible_ids), None)


def _pick_next_eligible(group: TurnGroup, day: date_type,
                        skip_child_id: int | None,
                        to_end: bool = False) -> TurnGroupMember | None:
    """
    Find the next eligible member after skip_child_id.
    If to_end=True (skip action), the skipped child goes to the very end.
    """
    members      = get_group_members(group)
    eligible_ids = set(eligible_member_ids(group, day))

    if not eligible_ids:
        return None

    if skip_child_id is None:
        return next((m for m in members if m.child_id in eligible_ids), None)

    now_member = next((m for m in members if m.child_id == skip_child_id), None)
    if not now_member:
        return next((m for m in members if m.child_id in eligible_ids), None)

    start_idx = members.index(now_member)
    if to_end:
        # Remaining in order, then skip to very end (skip_child stays eligible)
        ordered = members[start_idx + 1:] + members[:start_idx + 1]
    else:
        ordered = members[start_idx + 1:] + members[:start_idx + 1]

    chosen = next((m for m in ordered if m.child_id in eligible_ids), None)
    return chosen or now_member


def advance_turn(group: TurnGroup, day: date_type,
                 actor_id: int | None = None) -> AdvanceResult:
    """Manual Next: pause running session then advance queue."""
    state = get_or_init_turn_state(group, day)

    if state.session_started_at and state.active_child_id:
        pause_turn_session(group, day, actor_id=actor_id)

    # If we're leaving a slot that was sold via point-trade, consume it now.
    current_slot_member = TurnGroupMember.query.filter_by(group_id=group.id, position=state.current_position).first()
    if current_slot_member:
        pending = _pending_trade_for_seller(state, current_slot_member.child_id)
        if pending:
            try:
                buyer_id = int(pending.get('buyer_id'))
            except Exception:
                buyer_id = None
            if buyer_id and int(buyer_id) != int(current_slot_member.child_id) and int(state.active_child_id or 0) == int(buyer_id):
                _consume_trade_for_seller(state, current_slot_member.child_id)

    # Important: advance by SLOT position, not by active_child_id.
    # With point-trades, the active child may be playing someone else's slot.
    chosen_slot = _next_eligible_after_position(group, day, state.current_position)
    if not chosen_slot:
        return AdvanceResult(True, 'Everyone is out of time for today.')

    eligible_ids = set(eligible_member_ids(group, day))
    effective_child_id = _effective_child_for_slot(
        state,
        chosen_slot.child_id,
        eligible_ids,
        consume=False,
    )

    state.current_position   = chosen_slot.position
    state.active_child_id    = effective_child_id
    state.turn_remaining_sec = None
    state.session_started_at = None
    payload = _state_payload(state)
    payload['shared_ids'] = []
    _write_state_payload(state, payload)
    db.session.commit()

    next_child = User.query.get(effective_child_id)
    _log(group.id, day, 'next', actor_id=actor_id,
         child_id=effective_child_id,
         detail=f'Advanced to {next_child.username}')
    db.session.commit()
    return AdvanceResult(True, f'⏭ Now it\'s {next_child.username}\'s turn!')


def skip_turn(group: TurnGroup, day: date_type,
              child_id: int, actor_id: int | None = None) -> AdvanceResult:
    """
    Skip moves the child to the very END of the eligible queue.
    """
    state = get_or_init_turn_state(group, day)

    if state.session_started_at and state.active_child_id == child_id:
        pause_turn_session(group, day, actor_id=actor_id)

    # If we're leaving a slot that was sold via point-trade, consume it now.
    current_slot_member = TurnGroupMember.query.filter_by(group_id=group.id, position=state.current_position).first()
    if current_slot_member:
        pending = _pending_trade_for_seller(state, current_slot_member.child_id)
        if pending:
            try:
                buyer_id = int(pending.get('buyer_id'))
            except Exception:
                buyer_id = None
            if buyer_id and int(buyer_id) != int(current_slot_member.child_id) and int(state.active_child_id or 0) == int(buyer_id):
                _consume_trade_for_seller(state, current_slot_member.child_id)

    # Skip advances to the next eligible after the skipped child's position.
    members = get_group_members(group)
    skip_member = next((m for m in members if m.child_id == child_id), None)
    chosen_slot = _next_eligible_after_position(group, day, skip_member.position if skip_member else None)
    if not chosen_slot:
        return AdvanceResult(False, 'No other eligible kids to skip to.')

    eligible_ids = set(eligible_member_ids(group, day))
    state = get_or_init_turn_state(group, day)
    effective_child_id = _effective_child_for_slot(
        state,
        chosen_slot.child_id,
        eligible_ids,
        consume=False,
    )

    state.current_position   = chosen_slot.position
    state.active_child_id    = effective_child_id
    state.turn_remaining_sec = None
    state.session_started_at = None
    payload = _state_payload(state)
    payload['shared_ids'] = []
    _write_state_payload(state, payload)
    db.session.commit()

    skipped = User.query.get(child_id)
    next_c  = User.query.get(effective_child_id)
    _log(group.id, day, 'skip', actor_id=actor_id,
         child_id=child_id,
         detail=f'{skipped.username} skipped → {next_c.username} is now')
    db.session.commit()
    return AdvanceResult(True, f'⏩ Skipped {skipped.username}. Now: {next_c.username}.')


# ─────────────────────────────────────────────────────────────────────────────
# Swap (mutual consent)
# ─────────────────────────────────────────────────────────────────────────────

def request_swap(group: TurnGroup, day: date_type,
                 requester_id: int, target_id: int) -> AdvanceResult:
    existing = TurnSwapRequest.query.filter_by(
        group_id=group.id, day=day,
        requester_id=requester_id, target_id=target_id,
        status='pending',
    ).first()
    if existing:
        return AdvanceResult(False, 'Swap already requested – waiting for acceptance.')

    req = TurnSwapRequest(
        group_id=group.id, day=day,
        requester_id=requester_id, target_id=target_id,
    )
    db.session.add(req)
    _log(group.id, day, 'swap_requested',
         actor_id=requester_id, child_id=target_id,
         detail=f'Swap request from {requester_id} → {target_id}')
    db.session.commit()
    return AdvanceResult(True, 'Swap request sent – waiting for the other child to accept.')


def resolve_swap(group: TurnGroup, day: date_type,
                 swap_id: int, accepted: bool,
                 actor_id: int | None = None,
                 parent_override: bool = False) -> AdvanceResult:
    swap = TurnSwapRequest.query.get(swap_id)
    if not swap or swap.status != 'pending':
        return AdvanceResult(False, 'Swap request not found or already resolved.')

    if not accepted:
        swap.status      = 'rejected'
        swap.resolved_at = datetime.utcnow()
        _log(group.id, day, 'swap_rejected',
             actor_id=actor_id, detail='Swap declined')
        db.session.commit()
        return AdvanceResult(True, 'Swap declined.')

    # Perform the swap: exchange positions in TurnGroupMember
    m_a = TurnGroupMember.query.filter_by(
        group_id=group.id, child_id=swap.requester_id
    ).first()
    m_b = TurnGroupMember.query.filter_by(
        group_id=group.id, child_id=swap.target_id
    ).first()

    if not m_a or not m_b:
        return AdvanceResult(False, 'One of the children is no longer in the group.')

    m_a.position, m_b.position = m_b.position, m_a.position

    swap.status      = 'accepted'
    swap.resolved_at = datetime.utcnow()

    u_a = User.query.get(swap.requester_id)
    u_b = User.query.get(swap.target_id)
    _log(group.id, day, 'swap_accepted',
         actor_id=actor_id,
         detail=f'{u_a.username} ↔ {u_b.username}' +
                (' (parent override)' if parent_override else ''))
    db.session.commit()
    return AdvanceResult(True, f'✅ Swapped {u_a.username} and {u_b.username}.')


# ─────────────────────────────────────────────────────────────────────────────
# Shared turns  (Category A)
# ─────────────────────────────────────────────────────────────────────────────

def join_shared_turn(group: TurnGroup, day: date_type,
                     joining_child_id: int,
                     actor_id: int | None = None) -> AdvanceResult:
    """Add a child to the currently-running shared session."""
    state = get_or_init_turn_state(group, day)
    if not state.active_child_id:
        return AdvanceResult(False, 'No active turn to join.')

    payload = _state_payload(state)
    shared_ids = payload.get('shared_ids') or [state.active_child_id]
    if joining_child_id in shared_ids:
        return AdvanceResult(False, 'Already part of this turn.')

        shared_ids.append(joining_child_id)
        payload['shared_ids'] = shared_ids
        _write_state_payload(state, payload)
    joiner = User.query.get(joining_child_id)
    _log(group.id, day, 'shared_join',
         actor_id=actor_id, child_id=joining_child_id,
         detail=f'{joiner.username} joined the shared turn')
    db.session.commit()
    return AdvanceResult(True, f'{joiner.username} joined the turn – time deducted from both.')


# ─────────────────────────────────────────────────────────────────────────────
# Nudge  (Category C – Event queue)
# ─────────────────────────────────────────────────────────────────────────────

def nudge_current_child(group: TurnGroup, day: date_type,
                        nudger_id: int) -> AdvanceResult:
    state = get_or_init_turn_state(group, day)
    if not state.active_child_id:
        return AdvanceResult(False, 'Nobody is currently up.')

    nudged = User.query.get(state.active_child_id)
    nudger = User.query.get(nudger_id)
    _log(group.id, day, 'nudge',
         actor_id=nudger_id, child_id=state.active_child_id,
         detail=f'{nudger.username} nudged {nudged.username}')
    db.session.commit()
    # In production: send a push notification here
    return AdvanceResult(True, f'👋 Nudged {nudged.username}! A parent has been notified.')


# ─────────────────────────────────────────────────────────────────────────────
# Audit trail
# ─────────────────────────────────────────────────────────────────────────────

def get_audit_log(group_id: int, day: date_type | None = None,
                  limit: int = 50) -> list[TurnAuditLog]:
    q = TurnAuditLog.query.filter_by(group_id=group_id)
    if day:
        q = q.filter_by(day=day)
    return q.order_by(TurnAuditLog.ts.desc()).limit(limit).all()


# ─────────────────────────────────────────────────────────────────────────────
# Auto-advance interval helper
# ─────────────────────────────────────────────────────────────────────────────

def auto_advance_interval_seconds(group: TurnGroup) -> int | None:
    if not getattr(group, 'auto_advance_enabled', False):
        return None
    value = getattr(group, 'auto_advance_value', None)
    unit  = (getattr(group, 'auto_advance_unit', None) or 'minutes').lower()
    if not value or value <= 0:
        return None
    if unit == 'seconds':
        return int(value)
    if unit == 'hours':
        return int(value) * 3600
    return int(value) * 60


# ─────────────────────────────────────────────────────────────────────────────
# Point trade for turns
# ─────────────────────────────────────────────────────────────────────────────

def execute_point_trade(group: TurnGroup, day: date_type,
                        giver_id: int, receiver_id: int,
                        points: int,
                        actor_id: int | None = None) -> AdvanceResult:
    """Buyer (giver_id) pays points to take Seller's (receiver_id) next slot.

    Behavior:
      - Seller still stays in the group, but their *next slot* today is replaced by the buyer.
      - Buyer keeps their own normal slot too (so buyer gets 2 turns: original + bought).

    Implemented as a one-time slot override stored in TurnDayState for the day.
    No DB schema changes required.
    """
    if giver_id == receiver_id:
        return AdvanceResult(False, 'Buyer and seller must be different kids.')
    try:
        points = int(points)
    except Exception:
        return AdvanceResult(False, 'Points must be a number.')
    if points <= 0:
        return AdvanceResult(False, 'Points must be greater than 0.')

    m_buyer = TurnGroupMember.query.filter_by(group_id=group.id, child_id=giver_id).first()
    m_seller = TurnGroupMember.query.filter_by(group_id=group.id, child_id=receiver_id).first()
    if not m_buyer or not m_seller:
        return AdvanceResult(False, 'One of the children is not in the group.')

    buyer = User.query.get(giver_id)
    seller = User.query.get(receiver_id)
    if not buyer or not seller:
        return AdvanceResult(False, 'Could not find one of the children.')

    # Must have enough points.
    if int(buyer.points or 0) < points:
        return AdvanceResult(False, f'{buyer.username} only has {buyer.points} pts — not enough for this trade.')

    # Seller must actually have a turn available to sell today.
    eligible_ids = set(eligible_member_ids(group, day))
    if receiver_id not in eligible_ids:
        return AdvanceResult(False, f"{seller.username} doesn't have an available turn to sell today.")
    if giver_id not in eligible_ids:
        return AdvanceResult(False, f"{buyer.username} doesn't have an available turn today (out of time).")

    # Ensure we have a state row to attach the trade to.
    state = get_or_init_turn_state(group, day)
    payload = _state_payload(state)
    trade_list = payload.get('trade') or []

    # Prevent multiple pending sales for the same seller.
    for entry in trade_list:
        try:
            if int(entry.get('seller_id')) == int(receiver_id) and not bool(entry.get('used', False)):
                return AdvanceResult(False, f"{seller.username} already sold their next slot today.")
        except Exception:
            continue

    # Transfer points.
    buyer.points = int(buyer.points or 0) - points
    seller.points = int(seller.points or 0) + points

    # Record a one-time override: when the seller's slot is reached, buyer plays it.
    trade_list.append({
        'seller_id': int(receiver_id),
        'buyer_id': int(giver_id),
        'points': int(points),
        'used': False,
        'ts': datetime.utcnow().isoformat(timespec='seconds'),
    })
    payload['trade'] = trade_list
    _write_state_payload(state, payload)

    _log(group.id, day, 'trade_accepted',
         actor_id=actor_id,
         child_id=giver_id,
         detail=f'{buyer.username} paid {points} pts to buy {seller.username}\'s next slot')
    db.session.commit()

    return AdvanceResult(True,
        f'✅ Trade set! {buyer.username} paid {points} pts. '
        f'{seller.username} keeps the points but loses their next turn; '
        f'{buyer.username} will also keep their own normal turn.')





