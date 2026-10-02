"""Weighted roll-up of child progress."""

from __future__ import annotations

from frappe.utils import flt

from dinext_goals.constants import STATUS_CANCELLED


def weighted_progress(children) -> float | None:
	"""``children``: dicts with progress, weight and status; cancelled and zero-weight goals are ignored."""
	total_weight = 0.0
	total = 0.0
	for child in children:
		if child.get("status") == STATUS_CANCELLED:
			continue
		weight = flt(child.get("weight"))
		if weight <= 0:
			continue
		total_weight += weight
		total += weight * flt(child.get("progress"))
	if not total_weight:
		return None
	return total / total_weight
