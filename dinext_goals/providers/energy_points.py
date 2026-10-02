"""Energy points earned by the goal owner."""

from __future__ import annotations

import frappe
from frappe.utils import flt, getdate

from dinext_goals.providers import MetricProvider


def energy_points(user: str, date_from, date_to) -> float:
	rows = frappe.get_all(
		"Energy Point Log",
		filters={
			"user": user,
			"type": ["!=", "Review"],
			"reverted": 0,
			"creation": ["between", [getdate(date_from), getdate(date_to)]],
		},
		fields=["sum(points) as points"],
	)
	return flt(rows[0].points) if rows else 0.0


class EnergyPointsProvider(MetricProvider):
	key = "energy_points"
	label = "Energy points"
	description = "Sum of energy points of the goal owner in the period."

	def get_value(self, goal, params, date_from, date_to) -> float:
		return energy_points(goal.goal_owner, date_from, date_to)


provider = EnergyPointsProvider()
