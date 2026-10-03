"""Commercial utilization fulfillment from approved ``User Timesheet`` documents (dinext_timesheets).

The provider does not plan hours itself: ``dinext_timesheets`` stores the utilized hours and the
utilization plan of every timesheet. A timesheet belongs to the period it starts in, and the value
is a ratio of sums, so a short timesheet weighs less than a full one.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate

from dinext_goals.providers import MetricProvider, cost_center_with_descendants

APPROVED_TIMESHEET_STATUS = "Согласован"


def timesheet_totals(users: list[str], date_from, date_to) -> tuple[float, float]:
	"""Utilized hours and utilization plan hours of the approved timesheets starting in the period."""
	if not users:
		return 0.0, 0.0
	rows = frappe.get_all(
		"User Timesheet",
		filters={
			"timesheet_from": ["in", users],
			"ut_status": APPROVED_TIMESHEET_STATUS,
			"ts_valid_from": ["between", [getdate(date_from), getdate(date_to)]],
		},
		fields=["sum(total_hours_utilized) as utilized", "sum(utilization_hours_plan) as plan"],
	)
	if not rows:
		return 0.0, 0.0
	return flt(rows[0].utilized), flt(rows[0].plan)


def timesheet_utilization(users: list[str], date_from, date_to) -> float:
	utilized, plan = timesheet_totals(users, date_from, date_to)
	return utilized / plan * 100.0 if plan else 0.0


def team_users(cost_center: str, on_date) -> list[str]:
	"""Workers whose latest cost center assignment (valid on the date) is within the cost center."""
	centers = set(cost_center_with_descendants(cost_center))
	on_date = getdate(on_date)
	rows = frappe.get_all(
		"Cost Center Table",
		filters={"parenttype": "Worker", "cct_valid_from": ["<=", on_date]},
		fields=["parent", "cct_cost_center", "cct_valid_from"],
		order_by="cct_valid_from asc",
	)
	latest: dict[str, str] = {}
	for row in rows:
		latest[row.parent] = row.cct_cost_center
	workers = [worker for worker, center in latest.items() if center in centers]
	if not workers:
		return []
	return frappe.get_all("Worker", filters={"name": ["in", workers], "wuser": ["is", "set"]}, pluck="wuser")


def scope_users(goal, params, date_to) -> list[str]:
	if (params.get("scope") or "user") == "team":
		if not params.get("cost_center"):
			frappe.throw(_("Team utilization needs the cost_center parameter"))
		return team_users(params.get("cost_center"), date_to)
	return [goal.goal_owner]


class TimesheetUtilizationProvider(MetricProvider):
	key = "timesheet_utilization"
	label = "Commercial utilization (timesheets)"
	description = "Utilized hours against the utilization plan of approved user timesheets starting in the period, in percent. Parameter scope: user (goal owner) or team (workers of the cost_center parameter)."
	params = (
		{"code": "scope", "param_type": "Select", "options": "user\nteam", "required": False},
		{"code": "cost_center", "param_type": "Link", "link_doctype": "Cost Center", "required": False},
	)

	def is_available(self) -> bool:
		return bool(frappe.db.table_exists("User Timesheet"))

	def get_value(self, goal, params, date_from, date_to) -> float:
		return timesheet_utilization(scope_users(goal, params, date_to), date_from, date_to)


provider = TimesheetUtilizationProvider()
