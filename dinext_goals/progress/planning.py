"""Linear plan, deviation and RAG status."""

from __future__ import annotations

from datetime import date

from frappe.utils import flt, getdate

from dinext_goals.constants import LIVE_STATUSES, RAG_GREEN, RAG_RED, RAG_YELLOW


def planned_progress(start, end, on_date) -> float:
	if not start or not end:
		return 0.0
	start, end, on_date = getdate(start), getdate(end), getdate(on_date)
	if on_date <= start:
		return 0.0
	if on_date >= end:
		return 100.0
	return (on_date - start).days / (end - start).days * 100.0


def planned_value(baseline, target, planned_percent) -> float:
	return flt(baseline) + (flt(target) - flt(baseline)) * flt(planned_percent) / 100.0


def is_overdue(status: str | None, end, progress, on_date) -> bool:
	if status not in LIVE_STATUSES or not end:
		return False
	return getdate(on_date) > getdate(end) and flt(progress) < 100.0


def rag(deviation, overdue: bool, yellow_threshold, red_threshold) -> str:
	"""``deviation`` is actual minus planned progress; the thresholds limit the lag behind the plan."""
	lag = -flt(deviation)
	if overdue or lag > flt(red_threshold):
		return RAG_RED
	if lag > flt(yellow_threshold):
		return RAG_YELLOW
	return RAG_GREEN


def calculation_period(start, end, on_date) -> tuple[date | None, date | None]:
	if not start:
		return None, None
	start, on_date = getdate(start), getdate(on_date)
	period_end = min(on_date, getdate(end)) if end else on_date
	return start, max(start, period_end)
