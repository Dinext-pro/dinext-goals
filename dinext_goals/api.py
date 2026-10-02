"""Whitelisted endpoints of the goals app."""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from dinext_goals import parameters, templates
from dinext_goals.constants import GOAL, GOAL_LOG, LOG_SOURCE_MANUAL, STATUS_CANCELLED
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
	names = (
		{
			row.name: row.full_name or row.name
			for row in frappe.get_all("User", filters={"name": ["in", users]}, fields=["name", "full_name"])
		}
		if users
		else {}
	)
	for row in rows:
		row.owner_name = names.get(row.goal_owner, row.goal_owner)


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


@frappe.whitelist()
def get_goal_map(
	root: str | None = None,
	goal_type: str | None = None,
	goal_owner: str | None = None,
	company: str | None = None,
	show_linked: int | str = 0,
	include_cancelled: int | str = 0,
) -> dict:
	frappe.has_permission(GOAL, "read", throw=True)
	if root:
		_goal_for(root)
		seeds = [root]
	else:
		filters: dict[str, Any] = {}
		if goal_type:
			filters["goal_type"] = goal_type
		if goal_owner:
			filters["goal_owner"] = goal_owner
		if company:
			filters["company"] = company
		if not cint(include_cancelled):
			filters["status"] = ["!=", STATUS_CANCELLED]
		candidates = frappe.get_all(
			GOAL, filters=filters, pluck="name", order_by="exp_start_date desc, subject asc"
		)
		candidate_set = set(candidates)
		if filters:
			seeds = [name for name in candidates if not set(hierarchy.get_ancestors(name)) & candidate_set]
		else:
			parents = hierarchy.get_parents_of(candidates)
			seeds = [name for name in candidates if not parents[name]]

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

	def build(name: str, path: tuple[str, ...]) -> dict | None:
		row = rows.get(name)
		if not row or name in path:
			return None
		node = {field: row.get(field) for field in NODE_FIELDS if field not in ("linked_document_filter",)}
		node.update(
			{
				"id": "/".join((*path, name)),
				"owner_name": row.owner_name,
				"shared": len(parents.get(name, [])) > 1,
				"children": [],
			}
		)
		for child in children.get(name, []):
			if not cint(include_cancelled) and rows.get(child) and rows[child].status == STATUS_CANCELLED:
				continue
			built = build(child, (*path, name))
			if built:
				node["children"].append(built)
		if show_linked:
			node["linked"] = _linked_card(row)
		return node

	trees = [tree for tree in (build(seed, ()) for seed in seeds) if tree]
	return {"trees": trees, "truncated": len(members) >= MAP_NODE_LIMIT}


@frappe.whitelist()
def get_map_roots(txt: str | None = None) -> list[dict]:
	frappe.has_permission(GOAL, "read", throw=True)
	names = frappe.get_all(GOAL, filters={"status": ["!=", STATUS_CANCELLED]}, pluck="name")
	parents = hierarchy.get_parents_of(names)
	roots = [name for name in names if not parents[name]]
	if not roots:
		return []
	filters: dict[str, Any] = {"name": ["in", roots]}
	if txt:
		filters["subject"] = ["like", f"%{txt}%"]
	return frappe.get_all(
		GOAL, filters=filters, fields=["name", "subject", "status"], order_by="exp_start_date desc", limit=50
	)
