"""Fixtures for the goal Cypress suite.

`bootstrap_users` and `teardown_users` run through `bench execute` from the Cypress
config, so the password never leaves the test run. The seed and cleanup methods are
whitelisted only while `bench serve` sets `dev_server`. Every record they create
starts with `PREFIX` or belongs to `TEMPLATE`.
"""

from __future__ import annotations

import json
import os

import frappe
from frappe.tests.ui_test_helpers import whitelist_for_tests
from frappe.utils import add_days, nowdate
from frappe.utils.password import update_password

from dinext_goals.constants import GOAL, GOAL_LOG, GOAL_TEMPLATE
from dinext_goals.goals import hierarchy
from dinext_goals.progress import engine

PASSWORD_ENV = "DINEXT_GOALS_CYPRESS_PASSWORD"
PREFIX = "CY Goals"
TEMPLATE = f"{PREFIX} Template"
MANAGER = "goals.cy.manager@example.com"
OWNER = "goals.cy.owner@example.com"
USERS = {
	MANAGER: ("Cypress Goals Manager", ("Goal Manager", "Goal Approver", "Goal Owner", "Projects User")),
	OWNER: ("Cypress Goals Owner", ("Goal Owner",)),
}
# Dinext sites restrict Project, Task and Kanban Board to Dinext roles that every
# employee (and every project manager) has; granted when the site defines them.
SITE_ROLES = {
	MANAGER: ("Dinext_User", "Dinext_Project_Manager"),
	OWNER: ("Dinext_User",),
}


def bootstrap_users() -> dict:
	password = os.environ.get(PASSWORD_ENV)
	if not password:
		frappe.throw(f"{PASSWORD_ENV} is not set")
	for email, (full_name, roles) in USERS.items():
		if not frappe.db.exists("User", email):
			first, _sep, last = full_name.partition(" ")
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": first,
					"last_name": last,
					"user_type": "System User",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", email)
		user.language = "ru"
		user.enabled = 1
		user.save(ignore_permissions=True)
		user.add_roles(*roles, *(role for role in SITE_ROLES[email] if frappe.db.exists("Role", role)))
		update_password(email, password)
	frappe.db.commit()
	return {"manager": MANAGER, "owner": OWNER}


def teardown_users() -> None:
	_cleanup()
	for email in USERS:
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, ignore_permissions=True, force=True)
	frappe.db.commit()


def _goals() -> list[str]:
	names = set(frappe.get_all(GOAL, filters={"subject": ["like", f"{PREFIX}%"]}, pluck="name"))
	names.update(frappe.get_all(GOAL, filters={"goal_template": TEMPLATE}, pluck="name"))
	return list(names)


def _cleanup() -> None:
	goals = _goals()
	if goals:
		frappe.db.delete(GOAL_LOG, {"goal": ["in", goals]})
		for name in reversed(hierarchy.topological_order(goals)):
			frappe.delete_doc(GOAL, name, ignore_permissions=True, force=True)
	if frappe.db.exists(GOAL_TEMPLATE, TEMPLATE):
		frappe.delete_doc(GOAL_TEMPLATE, TEMPLATE, ignore_permissions=True, force=True)


def _goal(
	subject: str, owner: str, *, parent: str | None = None, is_group: int = 0, **values
) -> frappe.Document:
	doc = frappe.get_doc(
		{
			"doctype": GOAL,
			"subject": f"{PREFIX} {subject}",
			"goal_type": "KPI",
			"goal_owner": owner,
			"is_group": is_group,
			"exp_start_date": add_days(nowdate(), -30),
			"exp_end_date": add_days(nowdate(), 60),
			"progress_method": "Auto" if is_group else "Manual",
			"parents": [{"parent_goal": parent}] if parent else [],
		}
	)
	if not is_group:
		doc.update({"metric_type": "Numeric", "baseline": 0, "target": 100})
	doc.update(values)
	return doc.insert(ignore_permissions=True)


def _project_with_tasks() -> str:
	if frappe.db.count("Task", {"project": "DEMO-RU-01"}):
		return "DEMO-RU-01"
	rows = frappe.get_all(
		"Task",
		filters={"project": ["is", "set"]},
		fields=["project", "count(name) as tasks"],
		group_by="project",
		order_by="tasks desc",
		limit=1,
	)
	if not rows:
		frappe.throw("The goal Cypress suite needs a project with tasks")
	return rows[0].project


@whitelist_for_tests
def seed_goals_cypress() -> dict:
	frappe.only_for(("Goal Manager", "System Manager"))
	user = frappe.session.user
	frappe.set_user("Administrator")
	try:
		_cleanup()
		project = _project_with_tasks()
		cost_center = frappe.get_all(
			"Cost Center", filters={"is_group": 0}, pluck="name", order_by="name", limit=1
		)[0]
		root = _goal(
			"Root",
			MANAGER,
			is_group=1,
			parameters=[
				{
					"code": "projects",
					"label": "Проекты",
					"param_type": "Link List",
					"link_doctype": "Project",
					"value_list": project,
					"inherit": 1,
				}
			],
		)
		middle = _goal(
			"Middle",
			OWNER,
			parent=root.name,
			is_group=1,
			parameters=[
				{
					"code": "cost_center",
					"label": "ЦФО",
					"param_type": "Link",
					"link_doctype": "Cost Center",
					"value_link": cost_center,
					"inherit": 1,
				}
			],
		)
		history = _goal("History", OWNER, parent=middle.name, current_value=10)
		for value in (20, 30):
			history.reload()
			history.current_value = value
			history.save(ignore_permissions=True)
		tasks = _goal(
			"Tasks",
			MANAGER,
			parent=root.name,
			progress_method="Auto",
			metric_source="Linked Documents",
			linked_document_type="Task",
			aggregation="Count",
			linked_document_filter=json.dumps({"project": project}),
			target=100,
		)
		goals = [root.name, middle.name, history.name, tasks.name]
		frappe.db.set_value(GOAL, {"name": ["in", goals]}, {"workflow_state": "Approved", "status": "Active"})
		engine.recalculate(root.name)
		# A stale value for the form scenario: Recalculate must bring it back to the child's 30%.
		frappe.db.set_value(GOAL, middle.name, "progress", 0, update_modified=False)

		frappe.get_doc(
			{
				"doctype": GOAL_TEMPLATE,
				"template_name": TEMPLATE,
				"goal_type": "KPI",
				"is_active": 1,
				"default_duration_days": 90,
				"items": [
					{
						"item_key": "ROOT",
						"subject": f"{PREFIX} Template root",
						"is_group": 1,
						"progress_method": "Auto",
					},
					{
						"item_key": "PRJ",
						"parent_key": "ROOT",
						"subject": f"{PREFIX} Template projects",
						"progress_method": "Manual",
						"metric_type": "Numeric",
						"baseline": 0,
						"target": 10,
					},
				],
				"template_parameters": [
					{
						"code": "projects",
						"label": "Проекты",
						"param_type": "Link List",
						"link_doctype": "Project",
						"inherit": 1,
						"ask_on_create": 1,
					}
				],
			}
		).insert(ignore_permissions=True)
		return {
			"root": root.name,
			"middle": middle.name,
			"middle_subject": middle.subject,
			"history": history.name,
			"tasks": tasks.name,
			"project": project,
			"task_count": frappe.db.count("Task", {"project": project}),
			"template": TEMPLATE,
			"owner": OWNER,
			"owner_goals": frappe.db.count(GOAL, {"goal_owner": OWNER}),
		}
	finally:
		frappe.set_user(user)


@whitelist_for_tests
def cleanup_goals_cypress() -> None:
	frappe.only_for(("Goal Manager", "System Manager"))
	user = frappe.session.user
	frappe.set_user("Administrator")
	try:
		_cleanup()
	finally:
		frappe.set_user(user)
