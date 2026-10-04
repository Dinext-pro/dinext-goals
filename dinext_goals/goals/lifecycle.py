"""Business status of a goal: derived from the approval state, then driven by lifecycle actions."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from dinext_goals.constants import (
	DRAFT_ONLY_FIELDS,
	LIFECYCLE_ACTIONS,
	LIVE_STATUSES,
	STATE_APPROVED,
	STATE_DRAFT,
	STATE_TO_STATUS,
	STATUS_ACTIVE,
	STATUS_DRAFT,
	STATUS_FOR_APPROVAL,
)
from dinext_goals.goals import hierarchy

NUMERIC_LOCKED = {"baseline", "target", "weight", "is_group"}


def sync_status(doc, before) -> None:
	previous = before.status if before else None
	if doc.flags.lifecycle_status:
		doc.status = doc.flags.lifecycle_status
		return
	state = doc.workflow_state or STATE_DRAFT
	if state != STATE_APPROVED:
		doc.status = STATE_TO_STATUS.get(state, STATUS_DRAFT)
		return
	if previous in (None, STATUS_DRAFT, STATUS_FOR_APPROVAL):
		doc.status = STATUS_ACTIVE
	else:
		doc.status = previous


def _same(fieldname: str, old, new) -> bool:
	if fieldname in NUMERIC_LOCKED:
		return flt(old) == flt(new)
	if fieldname in ("exp_start_date", "exp_end_date"):
		return (getdate(old) if old else None) == (getdate(new) if new else None)
	return (old or "") == (new or "")


def validate_draft_lock(doc, before) -> None:
	if not before or before.status == STATUS_DRAFT:
		return
	changed = [f for f in DRAFT_ONLY_FIELDS if not _same(f, before.get(f), doc.get(f))]
	if hierarchy.doc_parent_names(before) != hierarchy.doc_parent_names(doc):
		changed.append("parents")
	if changed:
		labels = ", ".join(_(doc.meta.get_label(f)) for f in changed)
		frappe.throw(_("These fields can be changed only in Draft: {0}").format(labels))


def validate_lifecycle_action(doc, action: str) -> str:
	if action not in LIFECYCLE_ACTIONS:
		frappe.throw(_("Unknown action {0}").format(action))
	allowed_from, target = LIFECYCLE_ACTIONS[action]
	if doc.status not in allowed_from:
		frappe.throw(_("Action is not available for a goal in status {0}").format(frappe.bold(_(doc.status))))
	return target


def apply_lifecycle_action(doc, action: str) -> None:
	target = validate_lifecycle_action(doc, action)
	doc.flags.lifecycle_status = target
	if target not in LIVE_STATUSES:
		doc.is_overdue = 0
	doc.save()


def validate_owner_role(doc) -> None:
	from dinext_goals.constants import ROLE_OWNER

	if not doc.goal_owner:
		return
	if not cint(frappe.db.get_value("User", doc.goal_owner, "enabled")):
		frappe.throw(_("Goal owner {0} is disabled").format(doc.goal_owner))
	if ROLE_OWNER not in frappe.get_roles(doc.goal_owner):
		frappe.throw(_("Goal owner {0} must have the Goal Owner role").format(frappe.bold(doc.goal_owner)))
