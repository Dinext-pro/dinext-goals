"""Stepped coefficient scales."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt


def coefficient(rows, achievement) -> float | None:
	"""Coefficient of the highest threshold not above the achievement; 0 below the first step."""
	steps = sorted(
		((flt(row.get("threshold_percent")), flt(row.get("coefficient"))) for row in rows or []),
		key=lambda step: step[0],
	)
	if not steps:
		return None
	result = 0.0
	for threshold, value in steps:
		if flt(achievement) >= threshold:
			result = value
		else:
			break
	return result


def parse_spec(spec: str | None) -> list[dict]:
	"""Parse ``threshold:coefficient`` lines (also comma or semicolon separated)."""
	rows = []
	for chunk in (spec or "").replace(";", "\n").replace(",", "\n").splitlines():
		chunk = chunk.strip()
		if not chunk:
			continue
		if ":" not in chunk:
			frappe.throw(_("Scale step {0} must look like threshold:coefficient").format(chunk))
		threshold, value = chunk.split(":", 1)
		try:
			rows.append({"threshold_percent": float(threshold), "coefficient": float(value)})
		except ValueError:
			frappe.throw(_("Scale step {0} must contain numbers").format(chunk))
	return rows


def to_spec(rows) -> str:
	return "\n".join(f"{flt(row.threshold_percent):g}:{flt(row.coefficient):g}" for row in rows or [])
