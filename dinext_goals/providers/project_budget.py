"""Planned project profit from ``Project Budget`` (dinext_projects_pl)."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from dinext_goals.providers import MetricProvider, as_list
from dinext_goals.providers.gl_profit import account_root_types


def planned_project_profit(projects) -> float:
	project_list = as_list(projects)
	if not project_list:
		frappe.throw(_("Planned project profit needs the projects parameter"))
	budgets = frappe.get_all(
		"Project Budget", filters={"pb_project": ["in", project_list]}, fields=["name", "pb_account"]
	)
	if not budgets:
		return 0.0
	account_by_budget = {row.name: row.pb_account for row in budgets}
	root_types = account_root_types(list({row.pb_account for row in budgets if row.pb_account}))
	amounts = frappe.get_all(
		"Project Budget Amount",
		filters={"parent": ["in", list(account_by_budget)], "parenttype": "Project Budget"},
		fields=["parent", "pba_plan"],
	)
	profit = 0.0
	for row in amounts:
		root_type = root_types.get(account_by_budget.get(row.parent))
		if root_type == "Income":
			profit += flt(row.pba_plan)
		elif root_type == "Expense":
			profit -= flt(row.pba_plan)
	return profit


class ProjectBudgetProfitProvider(MetricProvider):
	key = "project_budget_profit"
	label = "Planned project profit (budget)"
	description = "Income budget minus expense budget of the projects parameter."
	params = ({"code": "projects", "param_type": "Link List", "link_doctype": "Project", "required": True},)
	supports_target = True

	def is_available(self) -> bool:
		return bool(
			frappe.db.table_exists("Project Budget") and frappe.db.table_exists("Project Budget Amount")
		)

	def get_value(self, goal, params, date_from, date_to) -> float:
		return planned_project_profit(params.get("projects"))

	def get_target(self, goal, params) -> float:
		return planned_project_profit(params.get("projects"))


provider = ProjectBudgetProfitProvider()
