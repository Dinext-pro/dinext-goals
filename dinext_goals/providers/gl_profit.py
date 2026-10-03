"""Gross profit (income minus expense) from posted GL entries.

Cancelled documents drop out through ``is_cancelled`` (both the original and the mirror rows carry
it); with the immutable ledger the mirror rows stay active and net the original by posting date,
as reversal Journal Entries do. Period closing rows zero income and expense accounts and opening
rows are balances, so both are excluded, as are entries of a non-default finance book.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from dinext_goals.providers import MetricProvider, as_list, cost_center_with_descendants

PERIOD_CLOSING_VOUCHER = "Period Closing Voucher"


def account_root_types(accounts: list[str]) -> dict[str, str]:
	if not accounts:
		return {}
	return {
		row.name: row.root_type
		for row in frappe.get_all("Account", filters={"name": ["in", accounts]}, fields=["name", "root_type"])
	}


def _ensure_one_currency(companies: set[str]) -> None:
	currencies = {frappe.get_cached_value("Company", company, "default_currency") for company in companies}
	if len(currencies) > 1:
		frappe.throw(
			_("Gross profit spans companies with different currencies ({0}); set the goal company").format(
				", ".join(sorted(filter(None, currencies)))
			)
		)


def gl_profit(
	*, date_from, date_to, cost_center: str | None = None, projects=None, company: str | None = None
) -> float:
	filters: dict = {
		"is_cancelled": 0,
		"is_opening": ["!=", "Yes"],
		"voucher_type": ["!=", PERIOD_CLOSING_VOUCHER],
		"posting_date": ["between", [date_from, date_to]],
	}
	or_filters = [["finance_book", "is", "not set"]]
	if company:
		filters["company"] = company
		default_book = frappe.get_cached_value("Company", company, "default_finance_book")
		if default_book:
			or_filters.append(["finance_book", "=", default_book])
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
		or_filters=or_filters,
		fields=["account", "company", "sum(debit) as debit", "sum(credit) as credit"],
		group_by="account, company",
	)
	if not company:
		_ensure_one_currency({row.company for row in rows})
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
	details = (
		"Source: submitted GL entries posted in the period (from the planned start to the earlier of today and the planned end).",
		"Value: credit minus debit of Income accounts minus debit minus credit of Expense accounts.",
		"Filter: the projects parameter; when it is empty, the cost_center parameter with its child cost centers.",
		"Excluded: cancelled entries, period closing vouchers, opening entries and entries of a finance book other than the company default; reversals net with the reversed entry.",
		"Without a goal company all entries must share one company currency.",
	)
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
