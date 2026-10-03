"""Planned project profit from ``Project Budget`` (dinext_projects_pl).

Budget amounts are monthly (``pba_year``/``pba_month``); a month counts when it overlaps the period.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate

from dinext_goals.providers import MetricProvider, as_list
from dinext_goals.providers.gl_profit import account_root_types


def period_months(date_from, date_to) -> set[tuple[int, int]]:
	start, end = getdate(date_from), getdate(date_to)
	months: set[tuple[int, int]] = set()
	year, month = start.year, start.month
	while (year, month) <= (end.year, end.month):
		months.add((year, month))
		year, month = (year + 1, 1) if month == 12 else (year, month + 1)
	return months


def planned_project_profit(projects, date_from=None, date_to=None) -> float:
	"""Income minus expense budget; without both dates every budget month counts."""
	project_list = as_list(projects)
	if not project_list:
		frappe.throw(_("Planned project profit needs the projects parameter"))
	months = period_months(date_from, date_to) if date_from and date_to else None
	if months == set():
		return 0.0
	budgets = frappe.get_all(
		"Project Budget", filters={"pb_project": ["in", project_list]}, fields=["name", "pb_account"]
	)
	if not budgets:
		return 0.0
	account_by_budget = {row.name: row.pb_account for row in budgets}
	root_types = account_root_types(list({row.pb_account for row in budgets if row.pb_account}))
	filters: dict = {"parent": ["in", list(account_by_budget)], "parenttype": "Project Budget"}
	if months is not None:
		filters["pba_year"] = ["in", sorted({year for year, _month in months})]
	amounts = frappe.get_all(
		"Project Budget Amount", filters=filters, fields=["parent", "pba_year", "pba_month", "pba_plan"]
	)
	profit = 0.0
	for row in amounts:
		if months is not None and (int(row.pba_year or 0), int(row.pba_month or 0)) not in months:
			continue
		root_type = root_types.get(account_by_budget.get(row.parent))
		if root_type == "Income":
			profit += flt(row.pba_plan)
		elif root_type == "Expense":
			profit -= flt(row.pba_plan)
	return profit


class ProjectBudgetProfitProvider(MetricProvider):
	key = "project_budget_profit"
	label = "Planned project profit (budget)"
	description = "Income budget minus expense budget of the projects parameter for the months overlapping the period; as a target, the planned period of the goal."
	params = ({"code": "projects", "param_type": "Link List", "link_doctype": "Project", "required": True},)
	supports_target = True

	def is_available(self) -> bool:
		return bool(
			frappe.db.table_exists("Project Budget") and frappe.db.table_exists("Project Budget Amount")
		)

	def get_value(self, goal, params, date_from, date_to) -> float:
		return planned_project_profit(params.get("projects"), date_from, date_to)

	def get_target(self, goal, params) -> float:
		return planned_project_profit(
			params.get("projects"), goal.get("exp_start_date"), goal.get("exp_end_date")
		)


provider = ProjectBudgetProfitProvider()
