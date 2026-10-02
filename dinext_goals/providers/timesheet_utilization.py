"""Commercial utilization: approved utilized hours against the planned utilization hours.

The plan follows ``dinext_timesheets`` ``calculate_ut_hours`` for an arbitrary period: working days
of the worker's holiday list, standard and shortened-day hours of the timesheet template, minus
approved absences (except "Отгул"), times the utilization percent valid on that day.
"""

from __future__ import annotations

from datetime import date

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, flt, getdate

from dinext_goals.providers import MetricProvider, cost_center_with_descendants

APPROVED_STATUS = "Согласовано"
NON_ABSENCE_LEAVE = "Отгул"


def _worker(user: str):
	name = frappe.db.get_value("Worker", {"wuser": user}, "name")
	if not name:
		frappe.throw(_("No Worker card for user {0}").format(user))
	return frappe.get_doc("Worker", name)


def _override_hours(working_hours_on_date: str | None) -> dict[date, float]:
	if not working_hours_on_date:
		return {}
	child = frappe.get_meta("Working Hours On Date").get_field("hod_working_hours_table").options
	return {
		getdate(row.wht_date): flt(row.wht_hours)
		for row in frappe.get_all(
			child,
			filters={"parent": working_hours_on_date, "parenttype": "Working Hours On Date"},
			fields=["wht_date", "wht_hours"],
		)
	}


def planned_hours(user: str, date_from, date_to) -> float:
	date_from, date_to = getdate(date_from), getdate(date_to)
	if date_to < date_from:
		return 0.0
	worker = _worker(user)
	holidays: set[date] = set()
	if worker.wholiday_list:
		holidays = {
			getdate(d)
			for d in frappe.get_all(
				"Holiday",
				filters={
					"parent": worker.wholiday_list,
					"parenttype": "Holiday List",
					"holiday_date": ["between", [date_from, date_to]],
				},
				pluck="holiday_date",
			)
		}
	template = (
		frappe.db.get_value(
			"Timesheet Template",
			worker.wtimesheet_template,
			["hours_on_date", "tt_working_hours_on_date"],
			as_dict=True,
		)
		if worker.wtimesheet_template
		else None
	)
	standard_hours = flt(template.hours_on_date) if template else 8.0
	override = _override_hours(template.tt_working_hours_on_date if template else None)
	leaves = frappe.get_all(
		"Application For Leave",
		filters={
			"lauser": user,
			"status": APPROVED_STATUS,
			"alfrom_date": ["<=", date_to],
			"alto_date": [">=", date_from],
		},
		fields=["alfrom_date", "alto_date", "alfrom_hours", "alto_hours", "altype_of_leave"],
	)
	utilization = sorted(
		((getdate(row.util_valid_from), flt(row.utilization)) for row in worker.get("utilization") or []),
		key=lambda item: item[0],
	)

	total = 0.0
	for offset in range(date_diff(date_to, date_from) + 1):
		day = getdate(add_days(date_from, offset))
		if day in holidays:
			continue
		scheduled = override.get(day, standard_hours)
		absence = 0.0
		for leave in leaves:
			start, end = getdate(leave.alfrom_date), getdate(leave.alto_date)
			if day < start or day > end or leave.altype_of_leave == NON_ABSENCE_LEAVE:
				continue
			if day == start and flt(leave.alfrom_hours) > 0:
				absence += flt(leave.alfrom_hours)
			elif day == end and end != start and flt(leave.alto_hours) > 0:
				absence += flt(leave.alto_hours)
			else:
				absence += scheduled
		percent = 0.0
		for valid_from, value in utilization:
			if valid_from <= day:
				percent = value
		total += max(0.0, scheduled - absence) * percent / 100.0
	return total


def utilized_hours(users: list[str], date_from, date_to) -> float:
	if not users:
		return 0.0
	positions = frappe.get_all(
		"User Timesheet Position", filters={"user": ["in", users], "status": APPROVED_STATUS}, pluck="name"
	)
	if not positions:
		return 0.0
	rows = frappe.get_all(
		"User Timesheet Position Details",
		filters={
			"parent": ["in", positions],
			"parenttype": "User Timesheet Position",
			"date": ["between", [getdate(date_from), getdate(date_to)]],
		},
		fields=["sum(utilized_hours) as hours"],
	)
	return flt(rows[0].hours) if rows else 0.0


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
	description = "Approved utilized hours against planned utilization hours, in percent. Parameter scope: user (goal owner) or team (workers of the cost_center parameter)."
	params = (
		{"code": "scope", "param_type": "Select", "options": "user\nteam", "required": False},
		{"code": "cost_center", "param_type": "Link", "link_doctype": "Cost Center", "required": False},
	)

	def is_available(self) -> bool:
		return bool(
			frappe.db.table_exists("Worker")
			and frappe.db.table_exists("User Timesheet Position")
			and frappe.db.table_exists("Timesheet Template")
		)

	def get_value(self, goal, params, date_from, date_to) -> float:
		users = scope_users(goal, params, date_to)
		plan = sum(planned_hours(user, date_from, date_to) for user in users)
		if not plan:
			return 0.0
		return utilized_hours(users, date_from, date_to) / plan * 100.0


provider = TimesheetUtilizationProvider()
