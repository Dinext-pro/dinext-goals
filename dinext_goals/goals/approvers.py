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
	WORKFLOW_NAME,
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


def retire_previous_draft_assignment(doc, previous_owner: str | None) -> None:
	"""Let normal reconciliation assign submission to the new draft owner."""
	if (
		doc.workflow_state != STATE_DRAFT
		or not previous_owner
		or not frappe.conf.get("enable_parallel_workflow_approval")
	):
		return

	from dinext_common.workflow_approval import engine
	from dinext_common.workflow_approval.scenarios import service

	context = service.get_context(doc)
	if context["workflow"] != WORKFLOW_NAME:
		return

	rounds = frappe.get_all(
		"Workflow Task",
		filters={
			"reference_doctype": GOAL,
			"reference_name": doc.name,
			"source_created_at": doc.creation,
			"workflow": WORKFLOW_NAME,
			"workflow_process": context["process_id"],
			"workflow_state": STATE_DRAFT,
			"approver": previous_owner,
			"status": "Working",
			"round_status": "Open",
		},
		pluck="approval_round_id",
		distinct=True,
	)
	for round_id in rounds:
		engine._cancel_round(round_id, _("Goal owner changed"))


def refresh_parent_approval_candidates(goals: list[str]) -> None:
	"""Keep the candidate list current while preserving existing round history."""
	if not goals:
		return

	names = frappe.get_all(
		GOAL, filters={"name": ("in", goals), "workflow_state": STATE_PARENT_APPROVAL}, pluck="name",
	)
	for name in sorted(names):
		doc = frappe.get_doc(GOAL, name, for_update=True)
		if doc.workflow_state != STATE_PARENT_APPROVAL:
			continue
		previous = doc.approver_users
		set_approver_users(doc)
		if doc.approver_users != previous:
			frappe.db.set_value(GOAL, name, "approver_users", doc.approver_users, update_modified=False)


def finance_approvers(doc) -> list[str]:
	creator = doc.owner or frappe.session.user
	return sorted(user for user in users_with_role(ROLE_FINANCE) if user != creator)


def validate_submission(doc, before) -> None:
	"""Explain a missing approver before the engine rejects the transition."""
	if doc.workflow_state != STATE_PARENT_APPROVAL:
		return
	if before and before.workflow_state not in (None, "", STATE_DRAFT):
		return
	_validate_submission_recipients(doc, bool((doc.approver_users or "").strip()))


def validate_submission_vote(doc, next_state: str) -> None:
	if next_state != STATE_PARENT_APPROVAL or doc.workflow_state not in (None, "", STATE_DRAFT):
		return
	from dinext_common.workflow_approval.engine import WorkflowDomainRollbackError

	_validate_submission_recipients(doc, bool(compute_approver_users(doc)), WorkflowDomainRollbackError)


def _validate_submission_recipients(
	doc, has_parent_approvers: bool, error: type[frappe.ValidationError] = frappe.ValidationError,
) -> None:
	if not has_parent_approvers:
		frappe.throw(
			_(
				"Nobody can approve this goal: no owner of a parent goal holds the Goal Approver role, and no other user has both Goal Manager and Goal Approver roles."
			),
			exc=error,
			title=_("No approvers"),
		)
	if not finance_approvers(doc):
		frappe.throw(
			_("Nobody can approve this goal at the finance step: assign the Goal Finance Approver role."),
			exc=error,
			title=_("No approvers"),
		)
