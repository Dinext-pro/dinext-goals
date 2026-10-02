"""Gross profit (income minus expense) from posted GL entries."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from dinext_goals.providers import MetricProvider, as_list, cost_center_with_descendants


def account_root_types(accounts: list[str]) -> dict[str, str]:
	if not accounts:
		return {}
	return {
		row.name: row.root_type
		for row in frappe.get_all("Account", filters={"name": ["in", accounts]}, fields=["name", "root_type"])
	}


def gl_profit(
	*, date_from, date_to, cost_center: str | None = None, projects=None, company: str | None = None
) -> float:
	filters: dict = {"is_cancelled": 0, "posting_date": ["between", [date_from, date_to]]}
	if company:
		filters["company"] = company
	project_list = as_list(projects)
	# Projects win over cost_center: a project goal under a cost center branch inherits both, and
	# project postings are often booked on a generic cost center.
	if project_list:
		filters["project"] = ["in", project_list]
	elif cost_center:
		filters["cost_center"] = ["in", cost_center_with_descendants(cost_center)]
	else:
		frappe.throw(_("Gross profit needs the cost_center or projects parameter"))

	rows = frappe.get_all(
		"GL Entry",
		filters=filters,
		fields=["account", "sum(debit) as debit", "sum(credit) as credit"],
		group_by="account",
	)
	root_types = account_root_types([row.account for row in rows])
	profit = 0.0
	for row in rows:
		root_type = root_types.get(row.account)
		if root_type == "Income":
			profit += flt(row.credit) - flt(row.debit)
		elif root_type == "Expense":
			profit -= flt(row.debit) - flt(row.credit)
	return profit


class GLProfitProvider(MetricProvider):
	key = "gl_profit"
	label = "Gross profit (GL)"
	description = "Income minus expense from GL entries of the projects parameter, or of the cost_center parameter (with child cost centers) when no projects are set."
	params = (
		{"code": "cost_center", "param_type": "Link", "link_doctype": "Cost Center", "required": False},
		{"code": "projects", "param_type": "Link List", "link_doctype": "Project", "required": False},
	)

	def get_value(self, goal, params, date_from, date_to) -> float:
		return gl_profit(
			date_from=date_from,
			date_to=date_to,
			cost_center=params.get("cost_center"),
			projects=params.get("projects"),
			company=goal.get("company"),
		)


provider = GLProfitProvider()
