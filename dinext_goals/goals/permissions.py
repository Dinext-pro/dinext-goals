"""Row-level read and write rules for goals."""

from __future__ import annotations

import frappe

from dinext_goals.constants import GOAL, ROLE_APPROVER, ROLE_FINANCE, ROLE_MANAGER
from dinext_goals.goals import hierarchy

READ_PTYPES = {"read", "select", "print", "report", "export", "email", "share"}
_CACHE_ATTR = "dinext_goals_visible_goals"


def is_goal_manager(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	roles = frappe.get_roles(user)
	return ROLE_MANAGER in roles or "System Manager" in roles


def sees_all_goals(user: str | None = None) -> bool:
	"""Managers and both approver roles read every goal; a parent approver must not go blind."""
	user = user or frappe.session.user
	if is_goal_manager(user):
		return True
	roles = set(frappe.get_roles(user))
	return ROLE_APPROVER in roles or ROLE_FINANCE in roles


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
	return bool(
		frappe.get_all(
			GOAL,
			filters={"name": ["in", ancestors], "goal_owner": user},
			limit=1,
			ignore_permissions=True,
		)
	)


def can_read_goal(goal, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if sees_all_goals(user):
		return True
	if isinstance(goal, str):
		goal = frappe.db.get_value(GOAL, goal, ["name", "goal_owner", "owner"], as_dict=True)
		if not goal:
			return False
	if user in (goal.get("goal_owner"), goal.get("owner")):
		return True
	name = goal.get("name")
	if not name:
		return False
	ancestors = hierarchy.get_ancestors(name)
	if not ancestors:
		return False
	return bool(
		frappe.get_all(
			GOAL,
			filters={"name": ["in", ancestors], "goal_owner": user},
			limit=1,
			ignore_permissions=True,
		)
	)


def goal_has_permission(doc, ptype: str | None = None, user: str | None = None, debug: bool = False):
	if not ptype or ptype == "create":
		return None
	if doc.get("__islocal") or not doc.get("name") or not frappe.db.exists(GOAL, doc.get("name")):
		return None
	if not can_read_goal(doc, user):
		return False
	if ptype in READ_PTYPES:
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


def visible_goal_names(user: str | None = None) -> list[str] | None:
	"""Names a pure Goal Owner may read: owned goals, their full subtree, and documents they created.

	``None`` means every goal. The workspace asks for many cards in one request, so the set is cached
	on the request. Fetches ignore permissions: this function is what the permission hook calls.
	"""
	user = user or frappe.session.user
	if sees_all_goals(user):
		return None
	cache = getattr(frappe.local, _CACHE_ATTR, None)
	if cache is None:
		cache = {}
		setattr(frappe.local, _CACHE_ATTR, cache)
	if user in cache:
		return cache[user]

	owned = frappe.get_all(GOAL, filters={"goal_owner": user}, pluck="name", ignore_permissions=True)
	created = frappe.get_all(GOAL, filters={"owner": user}, pluck="name", ignore_permissions=True)
	visible: list[str] = []
	seen: set[str] = set()
	frontier: list[str] = []
	for name in owned:
		if name not in seen:
			seen.add(name)
			visible.append(name)
			frontier.append(name)
	while frontier:
		children = hierarchy.get_children_of(frontier)
		frontier = []
		for name in children:
			for child in children[name]:
				if child not in seen:
					seen.add(child)
					visible.append(child)
					frontier.append(child)
	# Created documents are visible on their own. Their descendants follow the rule above.
	for name in created:
		if name not in seen:
			seen.add(name)
			visible.append(name)
	cache[user] = visible
	return visible


def _names_in(column: str, names: list[str]) -> str:
	if not names:
		return "1=0"
	quoted = ", ".join(frappe.db.escape(name) for name in names)
	return f"{column} in ({quoted})"


def goal_query_conditions(user: str | None = None) -> str | None:
	names = visible_goal_names(user)
	if names is None:
		return None
	return _names_in("`tabGoal`.`name`", names)


def goal_log_query_conditions(user: str | None = None) -> str | None:
	names = visible_goal_names(user)
	if names is None:
		return None
	return _names_in("`tabGoal Log`.`goal`", names)
