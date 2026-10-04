"""Approvers of the first approval step: owners of ancestor goals who hold Goal Approver."""

from __future__ import annotations

from collections.abc import Iterable

import frappe
from frappe import _

from dinext_goals.constants import (
	GOAL,
	ROLE_APPROVER,
	ROLE_FINANCE,
	ROLE_MANAGER,
	STATE_DRAFT,
	STATE_PARENT_APPROVAL,
)
from dinext_goals.goals import hierarchy

EXCLUDED_USERS = ("Administrator", "Guest")


def users_with_role(role: str) -> set[str]:
	users = frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent")
	if not users:
		return set()
	enabled = frappe.get_all(
		"User",
		filters={"name": ["in", list(set(users))], "enabled": 1, "user_type": "System User"},
		pluck="name",
	)
	return {user for user in enabled if user not in EXCLUDED_USERS}


def _with_role(users: Iterable[str], role: str) -> set[str]:
	return set(users) & users_with_role(role)


def compute_approver_users(doc) -> list[str]:
	creator = doc.owner or frappe.session.user
	ancestors = hierarchy.doc_ancestors(doc)
	owners: set[str] = set()
	if ancestors:
		owners = set(frappe.get_all(GOAL, filters={"name": ["in", ancestors]}, pluck="goal_owner"))
	approvers = {user for user in _with_role(owners, ROLE_APPROVER) if user != creator}
	if not approvers:
		approvers = {
			user for user in users_with_role(ROLE_MANAGER) & users_with_role(ROLE_APPROVER) if user != creator
		}
	return sorted(approvers)


def set_approver_users(doc) -> None:
	doc.approver_users = "\n".join(compute_approver_users(doc))


def finance_approvers(doc) -> list[str]:
	creator = doc.owner or frappe.session.user
	return sorted(user for user in users_with_role(ROLE_FINANCE) if user != creator)


def validate_submission(doc, before) -> None:
	"""Explain a missing approver before the engine rejects the transition."""
	if doc.workflow_state != STATE_PARENT_APPROVAL:
		return
	if before and before.workflow_state not in (None, "", STATE_DRAFT):
		return
	if not (doc.approver_users or "").strip():
		frappe.throw(
			_(
				"Nobody can approve this goal: no owner of a parent goal holds the Goal Approver role, and no other user has both Goal Manager and Goal Approver roles."
			),
			title=_("No approvers"),
		)
	if not finance_approvers(doc):
		frappe.throw(
			_("Nobody can approve this goal at the finance step: assign the Goal Finance Approver role."),
			title=_("No approvers"),
		)
