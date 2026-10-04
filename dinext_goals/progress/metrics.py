"""Pure metric arithmetic."""

from __future__ import annotations

from frappe.utils import flt


def achievement(metric_type: str | None, baseline, target, current) -> float:
	"""Share of the way from baseline to target, in percent; not capped."""
	if metric_type == "Boolean":
		return 100.0 if flt(current) else 0.0
	baseline, target, current = flt(baseline), flt(target), flt(current)
	span = target - baseline
	if span == 0:
		return 100.0 if current == target else 0.0
	return (current - baseline) / span * 100.0


def clamp_progress(value) -> float:
	return max(0.0, min(100.0, flt(value)))
