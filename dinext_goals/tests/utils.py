"""Shared fixtures of the goals test suite: users with fixed role sets and goal factories.

Every test runs inside one transaction that ``GoalTestCase.tearDown`` rolls back, so users and
documents are recreated per test and never reach the site.
"""

from __future__ import annotations

import importlib.util
import json
from functools import cache
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from dinext_goals.constants import (
	GOAL,
	ROLE_APPROVER,
	ROLE_FINANCE,
	ROLE_MANAGER,
	ROLE_OWNER,
	STATE_APPROVED,
	STATUS_ACTIVE,
)

T_MANAGER = "Бонус руководителя подразделения"
T_SPECIALIST = "Бонус сотрудника"
T_MONTHLY = "Премия за утилизацию"
T_PROJECT = "Проектный бонус"

START = "2026-01-01"
END = "2026-12-31"

MANAGER = "goals.test.manager@example.com"
DIRECTOR = "goals.test.director@example.com"
OWNER = "goals.test.owner@example.com"
OWNER_B = "goals.test.owner.b@example.com"
FINANCE = "goals.test.finance@example.com"
OUTSIDER = "goals.test.outsider@example.com"
PLAIN = "goals.test.plain@example.com"

USERS = {
	MANAGER: ("Goals Manager", (ROLE_MANAGER, ROLE_APPROVER, ROLE_OWNER)),
	DIRECTOR: ("Goals Director", (ROLE_APPROVER, ROLE_OWNER)),
	OWNER: ("Goals Owner", (ROLE_OWNER,)),
	OWNER_B: ("Goals Owner B", (ROLE_OWNER,)),
	FINANCE: ("Goals Finance", (ROLE_FINANCE,)),
	OUTSIDER: ("Goals Outsider", (ROLE_OWNER,)),
	PLAIN: ("Goals Plain", ()),
}


def ensure_user(email: str, full_name: str, roles) -> None:
	if not frappe.db.exists("User", email):
		first, _sep, last = full_name.partition(" ")
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": first,
				"last_name": last,
				"enabled": 1,
				"user_type": "System User",
				"send_welcome_email": 0,
				"roles": [{"role": role} for role in roles],
			}
		).insert(ignore_permissions=True)
	missing = [role for role in roles if role not in frappe.get_roles(email)]
	if missing:
		frappe.get_doc("User", email).add_roles(*missing)


def clear_user_caches() -> None:
	for email in USERS:
		frappe.clear_cache(user=email)


def ensure_users() -> None:
	clear_user_caches()
	for email, (full_name, roles) in USERS.items():
		ensure_user(email, full_name, roles)


def param(
	code,
	param_type="Float",
	value=None,
	*,
	link_doctype=None,
	options=None,
	inherit=1,
	editable=0,
	label=None,
):
	row = {
		"code": code,
		"label": label or code,
		"param_type": param_type,
		"link_doctype": link_doctype,
		"select_options": options,
		"inherit": inherit,
		"editable_when_active": editable,
	}
	if value is None:
		return row
	if param_type in ("Int", "Float", "Currency", "Percent"):
		row["value_number"] = value
	elif param_type == "Link":
		row["value_link"] = value
	elif param_type == "Link List":
		row["value_list"] = "\n".join(value)
	elif param_type == "Date":
		row["value_date"] = value
	elif param_type == "Check":
		row["value_check"] = value
	else:
		row["value_data"] = value
	return row


def new_goal(subject, *, owner=OWNER, parents=(), is_group=0, params=(), scale=(), **values):
	leaf_defaults = {} if is_group else {"metric_type": "Numeric", "baseline": 0, "target": 100}
	doc = frappe.get_doc(
		{
			"doctype": GOAL,
			"subject": subject,
			"goal_type": "KPI",
			"goal_owner": owner,
			"exp_start_date": START,
			"exp_end_date": END,
			"is_group": is_group,
			"progress_method": "Auto" if is_group else "Manual",
			**leaf_defaults,
			**values,
		}
	)
	for parent in parents:
		doc.append("parents", {"parent_goal": parent})
	for row in params:
		doc.append("parameters", row)
	for threshold, coefficient in scale:
		doc.append("scale", {"threshold_percent": threshold, "coefficient": coefficient})
	return doc


def make_goal(subject, **kwargs):
	return new_goal(subject, **kwargs).insert(ignore_permissions=True)


def make_group(subject, **kwargs):
	return make_goal(subject, is_group=1, **kwargs)


def activate(name: str) -> None:
	"""Mark a goal as approved without driving the approval engine."""
	frappe.db.set_value(
		GOAL, name, {"workflow_state": STATE_APPROVED, "status": STATUS_ACTIVE}, update_modified=False
	)


def as_user(user: str):
	class _AsUser:
		def __enter__(self):
			frappe.set_user(user)

		def __exit__(self, *exc):
			frappe.set_user("Administrator")

	return _AsUser()


def insert_raw(doctype: str, values: dict, *, name: str | None = None, children: dict | None = None):
	"""Insert a record of another app without its controller, for provider inputs."""
	doc = frappe.get_doc({"doctype": doctype, **values})
	if name:
		doc.name = name
	else:
		doc.set_new_name()
	doc.db_insert()
	for parentfield, rows in (children or {}).items():
		child_doctype = frappe.get_meta(doctype).get_field(parentfield).options
		for idx, row in enumerate(rows, start=1):
			child = frappe.get_doc(
				{
					"doctype": child_doctype,
					"parent": doc.name,
					"parenttype": doctype,
					"parentfield": parentfield,
					"idx": idx,
					**row,
				}
			)
			child.set_new_name()
			child.db_insert()
	return doc


def make_project(name: str, company: str = "Dinext") -> str:
	if not frappe.db.exists("Project", name):
		insert_raw("Project", {"project_name": name, "status": "Open", "company": company}, name=name)
	return name


def _parallel_approval_installed() -> bool:
	"""True when dinext_common ships the parallel approval package.

	``find_spec('a.b.c')`` imports ``a.b`` and raises ModuleNotFoundError if that
	package is absent, instead of returning None.
	"""
	try:
		if importlib.util.find_spec("dinext_common.workflow_approval") is None:
			return False
		return importlib.util.find_spec("dinext_common.workflow_approval.notifications") is not None
	except ModuleNotFoundError:
		return False


class GoalTestCase(FrappeTestCase):
	"""Users live for the class (rolled back by FrappeTestCase); each test rolls back to a savepoint."""

	SAVEPOINT = "dinext_goals_test"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		ensure_users()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		super().tearDownClass()
		clear_user_caches()

	def setUp(self):
		super().setUp()
		# The visibility set is cached on the request, and the test runner keeps one request.
		if hasattr(frappe.local, "dinext_goals_visible_goals"):
			delattr(frappe.local, "dinext_goals_visible_goals")
		# Tests run background jobs inline; approval e-mails would need an outgoing Email Account.
		# The parallel engine lives on dinext_common feat/dinext_workflow and is absent from the CI seed.
		# find_spec("pkg.missing.sub") raises when the middle package is missing; check the package first.
		if _parallel_approval_installed():
			notifier = patch("dinext_common.workflow_approval.notifications.send_immediate_notification")
			notifier.start()
			self.addCleanup(notifier.stop)
		frappe.set_user("Administrator")
		frappe.db.savepoint(self.SAVEPOINT)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point=self.SAVEPOINT)
		frappe.db.value_cache.clear()
		clear_user_caches()
		super().tearDown()

	def reload(self, name: str):
		return frappe.get_doc(GOAL, name)


@cache
def shipped_templates() -> dict[str, dict]:
	"""Goal templates of `fixtures/goal_template.json` by name."""
	path = frappe.get_app_path("dinext_goals", "fixtures", "goal_template.json")
	with open(path, encoding="utf-8") as fixture:
		return {row["name"]: row for row in json.load(fixture)}


def shipped_formula(template: str) -> str:
	"""Result formula of the root item of a shipped template."""
	items = shipped_templates()[template]["items"]
	return next(row for row in items if not row.get("parent_key"))["result_formula"]
