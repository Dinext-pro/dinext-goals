"""Row-level write rules for goals; read access follows role permissions."""

from __future__ import annotations

import frappe

from dinext_goals.constants import GOAL, ROLE_MANAGER
from dinext_goals.goals import hierarchy

READ_PTYPES = {"read", "select", "print", "report", "export", "email", "share"}


def is_goal_manager(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	roles = frappe.get_roles(user)
	return ROLE_MANAGER in roles or "System Manager" in roles


def can_edit_goal(goal, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if is_goal_manager(user):
		return True
	if isinstance(goal, str):
		goal = frappe.db.get_value(GOAL, goal, ["name", "goal_owner", "owner"], as_dict=True)
		if not goal:
			return False
	if user in (goal.get("goal_owner"), goal.get("owner")):
		return True
	ancestors = hierarchy.get_ancestors(goal.get("name")) if goal.get("name") else []
	if not ancestors:
		return False
	return bool(frappe.get_all(GOAL, filters={"name": ["in", ancestors], "goal_owner": user}, limit=1))


def goal_has_permission(doc, ptype: str | None = None, user: str | None = None, debug: bool = False):
	if not ptype or ptype in READ_PTYPES or ptype == "create":
		return None
	if doc.get("__islocal") or not doc.get("name") or not frappe.db.exists(GOAL, doc.get("name")):
		return None
	if not can_edit_goal(doc, user):
		return False
	return None


def goal_log_has_permission(doc, ptype: str | None = None, user: str | None = None, debug: bool = False):
	if ptype and ptype not in READ_PTYPES:
		return None
	if not doc.get("goal"):
		return None
	return bool(frappe.has_permission(GOAL, "read", doc=doc.get("goal"), user=user))
