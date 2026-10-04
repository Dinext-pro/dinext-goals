"""Whitelisted endpoints of the goals app."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, get_last_day, getdate, nowdate

from dinext_goals import parameters, templates
from dinext_goals.constants import (
	GOAL,
	GOAL_LOG,
	LOG_SOURCE_MANUAL,
	SETTINGS,
	STATUS_ACTIVE,
	STATUS_CANCELLED,
)
from dinext_goals.goals import hierarchy, lifecycle
from dinext_goals.progress import engine, planning, sources
from dinext_goals.providers import list_providers

MAP_NODE_LIMIT = 600
NODE_FIELDS = [
	"name",
	"subject",
	"goal_code",
	"goal_type",
	"goal_owner",
	"status",
	"rag_status",
	"progress",
	"planned_progress",
	"current_value",
	"target",
	"baseline",
	"unit",
	"metric_type",
	"currency",
	"coefficient",
	"result_value",
	"result_label",
	"is_group",
	"is_overdue",
	"progress_method",
	"metric_source",
	"linked_document_type",
	"linked_document_filter",
	"linked_document_field",
	"aggregation",
	"exp_start_date",
	"exp_end_date",
	"company",
]


def _goal_for(goal: str, ptype: str = "read"):
	doc = frappe.get_doc(GOAL, goal)
	doc.check_permission(ptype)
	return doc


def _loads(value: Any) -> Any:
	if isinstance(value, str):
		return json.loads(value) if value.strip() else None
	return value


@frappe.whitelist(methods=["POST"])
def recalculate(goal: str) -> dict:
	_goal_for(goal, "write")
	return engine.recalculate(goal, source=LOG_SOURCE_MANUAL)


@frappe.whitelist(methods=["POST"])
def set_lifecycle_status(goal: str, action: str) -> dict:
	doc = _goal_for(goal, "write")
	lifecycle.apply_lifecycle_action(doc, action)
	return {"status": doc.status}


@frappe.whitelist()
def get_effective_parameters(goal: str) -> list[dict]:
	_goal_for(goal)
	return parameters.describe(parameters.resolve_for_name(goal))


@frappe.whitelist()
def get_children(goal: str) -> list[dict]:
	_goal_for(goal)
	names = hierarchy.get_child_names(goal)
	if not names:
		return []
	rows = frappe.get_all(
		GOAL,
		filters={"name": ["in", names]},
		fields=[
			"name",
			"subject",
			"goal_code",
			"goal_type",
			"goal_owner",
			"status",
			"progress",
			"planned_progress",
			"rag_status",
			"weight",
			"is_group",
			"coefficient",
			"result_value",
		],
		order_by="subject asc",
	)
	_attach_owner_names(rows)
	return rows


def _attach_owner_names(rows: list) -> None:
	users = list({row.goal_owner for row in rows if row.goal_owner})
	owners = (
		{
			row.name: row
			for row in frappe.get_all(
				"User", filters={"name": ["in", users]}, fields=["name", "full_name", "user_image"]
			)
		}
		if users
		else {}
	)
	for row in rows:
		owner = owners.get(row.goal_owner)
		row.owner_name = (owner.full_name or owner.name) if owner else row.goal_owner
		row.owner_image = owner.user_image if owner else None


@frappe.whitelist()
def get_goal_trend(goal: str) -> dict:
	doc = _goal_for(goal)
	logs = frappe.get_all(
		GOAL_LOG,
		filters={"goal": goal},
		fields=["log_date", "progress", "planned_progress", "current_value", "source", "author"],
		order_by="log_date asc, creation asc",
		limit=2000,
	)
	return {
		"goal": doc.name,
		"subject": doc.subject,
		"is_group": cint(doc.is_group),
		"metric_type": doc.metric_type,
		"unit": doc.unit,
		"currency": doc.currency,
		"start": doc.exp_start_date,
		"end": doc.exp_end_date,
		"baseline": flt(doc.baseline),
		"target": flt(doc.target),
		"today": getdate(nowdate()),
		"progress": flt(doc.progress),
		"current_value": flt(doc.current_value),
		"planned_progress": planning.planned_progress(doc.exp_start_date, doc.exp_end_date, nowdate()),
		"logs": logs,
	}


@frappe.whitelist()
def list_metric_providers() -> list[dict]:
	return list_providers()


@frappe.whitelist()
def get_template_dialog_fields(template: str) -> list[dict]:
	frappe.has_permission("Goal Template", "read", doc=template, throw=True)
	return templates.ask_on_create_fields(template)


@frappe.whitelist(methods=["POST"])
def create_goals_from_template(
	template: str,
	start_date: str,
	goal_owner: str,
	code_prefix: str | None = None,
	parent_goal: str | None = None,
	company: str | None = None,
	values: str | dict | None = None,
	subject_suffix: str | None = None,
) -> list[str]:
	frappe.has_permission("Goal Template", "read", doc=template, throw=True)
	return templates.create_goals(
		template,
		start_date=start_date,
		goal_owner=goal_owner,
		code_prefix=code_prefix,
		parent_goal=parent_goal,
		company=company,
		values=_loads(values) or {},
		subject_suffix=subject_suffix,
	)


@frappe.whitelist(methods=["POST"])
def save_as_template(goal: str, template_name: str) -> str:
	_goal_for(goal)
	return templates.save_as_template(goal, template_name)


def _route_options(filters: dict | list) -> dict:
	if isinstance(filters, dict):
		return filters
	options = {}
	for item in filters or []:
		if isinstance(item, list | tuple) and len(item) >= 3:
			field, op, value = item[-3], item[-2], item[-1]
			options[field] = value if op == "=" else [op, value]
	return options


def _linked_card(row) -> dict | None:
	if (
		row.is_group
		or row.progress_method != "Auto"
		or (row.metric_source or "Linked Documents") != "Linked Documents"
	):
		return None
	if not row.linked_document_type:
		return None
	card = {
		"doctype": row.linked_document_type,
		"aggregation": row.aggregation or "Sum",
		"field": row.linked_document_field,
	}
	try:
		params = parameters.get_effective_params(row.name)
		filters = sources.linked_filters(row, params)
		if not frappe.has_permission(row.linked_document_type, "read"):
			card["restricted"] = 1
			return card
		card["count"] = frappe.db.count(row.linked_document_type, filters)
		card["value"] = sources.linked_documents_value(row, params)
		card["route_options"] = _route_options(filters)
	except frappe.ValidationError as exc:
		frappe.clear_last_message()
		card["error"] = str(exc)
	return card


def _as_list(value: Any) -> list[str]:
	"""A filter value from Desk: a list, its JSON or a single string."""
	if isinstance(value, str):
		text = value.strip()
		value = json.loads(text) if text.startswith("[") else [text]
	if not value:
		return []
	return [str(item) for item in (value if isinstance(value, list | tuple) else [value]) if item]


def _month_start(value: str | None) -> date | None:
	"""``YYYY-MM`` to the first day of the month."""
	if not value:
		return None
	try:
		year, month = (int(part) for part in str(value).split("-")[:2])
		return date(year, month, 1)
	except ValueError:
		frappe.throw(_("Invalid month {0}: expected YYYY-MM").format(value))


def map_period(period_from: str | None, period_to: str | None) -> tuple[date, date] | None:
	"""Months from ``period_from`` to ``period_to`` inclusive; a missing bound leaves that side open."""
	start = _month_start(period_from)
	end = _month_start(period_to)
	if not start and not end:
		return None
	if start and end and end < start:
		start, end = end, start
	return start or date.min, getdate(get_last_day(end)) if end else date.max


def _matches(row, statuses: list[str], period: tuple[date, date] | None, include_cancelled) -> bool:
	if statuses and row.status not in statuses:
		return False
	if not statuses and not cint(include_cancelled) and row.status == STATUS_CANCELLED:
		return False
	if period:
		start, end = row.exp_start_date, row.exp_end_date
		if (start and getdate(start) > period[1]) or (end and getdate(end) < period[0]):
			return False
	return True


@frappe.whitelist()
def get_goal_map(
	root: str | None = None,
	goal_type: str | list | None = None,
	goal_owner: str | list | None = None,
	company: str | None = None,
	project: str | None = None,
	show_linked: int | str = 0,
	include_cancelled: int | str = 0,
	status: str | list | None = STATUS_ACTIVE,
	period_from: str | None = None,
	period_to: str | None = None,
) -> dict:
	"""Goal trees for the map. Statuses (any of the list; empty = all) and the period apply to every card,
	the explicit root included; a card whose parent is filtered out hangs under its nearest drawn ancestor
	or becomes a tree. Types, owners, company and project pick the trees."""
	frappe.has_permission(GOAL, "read", throw=True)
	statuses = _as_list(status)
	period = map_period(period_from, period_to)
	if root:
		_goal_for(root)
		seeds = [root]
	else:
		filters: list = []
		if statuses:
			filters.append(["status", "in", statuses])
		elif not cint(include_cancelled):
			filters.append(["status", "!=", STATUS_CANCELLED])
		if types := _as_list(goal_type):
			filters.append(["goal_type", "in", types])
		if owners := _as_list(goal_owner):
			filters.append(["goal_owner", "in", owners])
		if company:
			filters.append(["company", "=", company])
		if project:
			filters.append([parameters.GOAL_PROJECT, "project", "=", project])
		candidates = list(
			dict.fromkeys(
				row.name
				for row in frappe.get_all(
					GOAL,
					filters=filters,
					fields=["name", "status", "exp_start_date", "exp_end_date"],
					order_by="exp_start_date desc, subject asc",
				)
				if _matches(row, statuses, period, include_cancelled)
			)
		)
		candidate_set = set(candidates)
		seeds = [name for name in candidates if not set(hierarchy.get_ancestors(name)) & candidate_set]

	members: list[str] = []
	for seed in seeds:
		members.append(seed)
		members.extend(hierarchy.get_descendants(seed))
	members = list(dict.fromkeys(members))[:MAP_NODE_LIMIT]
	rows = (
		{row.name: row for row in frappe.get_all(GOAL, filters={"name": ["in", members]}, fields=NODE_FIELDS)}
		if members
		else {}
	)
	_attach_owner_names(list(rows.values()))
	children = hierarchy.get_children_of(members)
	parents = hierarchy.get_parents_of(members)
	show_linked = cint(show_linked)

	def drawn_children(name: str, path: tuple[str, ...]) -> list[dict]:
		result = []
		for child in children.get(name, []):
			row = rows.get(child)
			if not row or child in path:
				continue
			if _matches(row, statuses, period, include_cancelled):
				result.append(build(child, path))
			else:
				result.extend(drawn_children(child, (*path, child)))
		return result

	def build(name: str, path: tuple[str, ...]) -> dict | None:
		row = rows.get(name)
		if not row or name in path:
			return None
		node = {field: row.get(field) for field in NODE_FIELDS if field not in ("linked_document_filter",)}
		node.update(
			{
				"id": "/".join((*path, name)),
				"owner_name": row.owner_name,
				"owner_image": row.owner_image,
				"shared": len(parents.get(name, [])) > 1,
				"children": drawn_children(name, (*path, name)),
			}
		)
		if show_linked:
			node["linked"] = _linked_card(row)
		return node

	trees = []
	for seed in seeds:
		row = rows.get(seed)
		if not row:
			continue
		if _matches(row, statuses, period, include_cancelled):
			trees.append(build(seed, ()))
		else:
			trees.extend(drawn_children(seed, (seed,)))
	return {"trees": trees, "truncated": len(members) >= MAP_NODE_LIMIT}


@frappe.whitelist()
def get_map_roots(txt: str | None = None, status: str | None = None) -> list[dict]:
	frappe.has_permission(GOAL, "read", throw=True)
	names = frappe.get_all(GOAL, filters={"status": ["!=", STATUS_CANCELLED]}, pluck="name")
	parents = hierarchy.get_parents_of(names)
	roots = [name for name in names if not parents[name]]
	if not roots:
		return []
	filters: dict[str, Any] = {"name": ["in", roots]}
	if status:
		filters["status"] = status
	if txt:
		filters["subject"] = ["like", f"%{txt}%"]
	return frappe.get_all(
		GOAL, filters=filters, fields=["name", "subject", "status"], order_by="exp_start_date desc", limit=50
	)


NAVBAR_FIELDS = [
	"name",
	"subject",
	"is_group",
	"metric_type",
	"current_value",
	"target",
	"unit",
	"currency",
	"progress",
	"achievement_percent",
	"rag_status",
	"weight",
	"exp_start_date",
]


@frappe.whitelist()
def get_navbar_goal() -> dict | None:
	"""The user's own Active goal covering today with the fewest ancestor levels."""
	if not cint(frappe.db.get_single_value(SETTINGS, "show_top_goal_in_navbar")):
		return None
	if not frappe.has_permission(GOAL, "read"):
		return None
	today = nowdate()
	candidates = frappe.get_all(
		GOAL,
		filters={"goal_owner": frappe.session.user, "status": STATUS_ACTIVE, "exp_start_date": ["<=", today]},
		or_filters=[["exp_end_date", "is", "not set"], ["exp_end_date", ">=", today]],
		fields=NAVBAR_FIELDS,
	)
	if not candidates:
		return None
	parents = hierarchy.get_parents_of(row.name for row in candidates)

	def rank(row):
		depth = len(hierarchy.ancestor_levels(row.name, parents[row.name]))
		return (depth, -cint(row.is_group), -flt(row.weight), getdate(row.exp_start_date), row.name)

	top = min(candidates, key=rank)
	top.pop("weight")
	top.pop("exp_start_date")
	return top
