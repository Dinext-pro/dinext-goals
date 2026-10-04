"""Energy points earned by the goal owner."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate

from dinext_goals.providers import MetricProvider


def energy_filters(user: str, date_from, date_to) -> dict:
	return {
		"user": user,
		"type": ["!=", "Review"],
		"reverted": 0,
		"creation": ["between", [getdate(date_from), getdate(date_to)]],
	}


def energy_points(user: str, date_from, date_to) -> float:
	rows = frappe.get_all(
		"Energy Point Log",
		filters=energy_filters(user, date_from, date_to),
		fields=["sum(points) as points"],
	)
	return flt(rows[0].points) if rows else 0.0


class EnergyPointsProvider(MetricProvider):
	key = "energy_points"
	label = "Energy points"
	description = "Sum of energy points of the goal owner in the period."
	details = (
		"Source: Energy Point Log of the goal owner created in the period (from the planned start to the earlier of today and the planned end).",
		"Value: the sum of points; review points and reverted entries are excluded.",
		"No parameters.",
	)

	def get_value(self, goal, params, date_from, date_to) -> float:
		return energy_points(goal.goal_owner, date_from, date_to)

	def source_documents(self, goal, params, date_from, date_to, *, side: str = "value") -> dict:
		if side != "value":
			frappe.throw(_("Metric provider {0} does not provide a target").format(_(self.label)))
		if not goal.goal_owner:
			return {"doctype": "Energy Point Log", "empty": 1}
		return {
			"doctype": "Energy Point Log",
			"filters": energy_filters(goal.goal_owner, date_from, date_to),
		}


provider = EnergyPointsProvider()
