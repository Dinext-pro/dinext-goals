"""Goal templates: validation, creating a goal tree and saving a subtree as a template."""

from __future__ import annotations

import os
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate

from dinext_goals import parameters
from dinext_goals.constants import GOAL, GOAL_TEMPLATE
from dinext_goals.goals import hierarchy
from dinext_goals.goals.permissions import can_edit_goal, is_goal_manager
from dinext_goals.progress import engine, formulas, scale
from dinext_goals.providers import get_provider

COPIED_FIELDS = (
	"is_group",
	"weight",
	"priority",
	"progress_method",
	"metric_type",
	"unit",
	"currency",
	"baseline",
	"target",
	"target_source",
	"target_provider",
	"target_formula",
	"target_drilldown_formula",
	"metric_source",
	"metric_provider",
	"linked_document_type",
	"linked_document_filter",
	"linked_document_field",
	"aggregation",
	"calculation_rule",
	"calculation_drilldown_rule",
	"result_label",
	"result_formula",
	"description",
)


def ordered_items(doc) -> list:
	"""Items parents-first; raises on unknown parents and cycles."""
	by_key = {}
	for item in doc.get("items") or []:
		key = (item.item_key or "").strip()
		if not key:
			frappe.throw(_("Row {0}: Item Key is required").format(item.idx))
		if key in by_key:
			frappe.throw(_("Item Key {0} is used more than once").format(frappe.bold(key)))
		item.item_key = key
		item.parent_key = (item.parent_key or "").strip() or None
		by_key[key] = item
	ordered, placed = [], set()
	pending = list(by_key.values())
	while pending:
		progress = False
		for item in list(pending):
			if item.parent_key and item.parent_key not in by_key:
				frappe.throw(
					_("Item {0}: parent key {1} does not exist").format(item.item_key, item.parent_key)
				)
			if not item.parent_key or item.parent_key in placed:
				ordered.append(item)
				placed.add(item.item_key)
				pending.remove(item)
				progress = True
		if not progress:
			frappe.throw(_("Template items form a cycle: {0}").format(", ".join(i.item_key for i in pending)))
	return ordered


def root_keys(doc) -> list[str]:
	return [item.item_key for item in doc.get("items") or [] if not item.parent_key]


def validate_template(doc) -> None:
	items = ordered_items(doc)
	if not items:
		frappe.throw(_("Add at least one goal to the template"))
	by_key = {item.item_key: item for item in items}
	for item in items:
		if item.parent_key and not cint(by_key[item.parent_key].is_group):
			frappe.throw(
				_("Item {0}: parent item {1} must be a group").format(item.item_key, item.parent_key)
			)
		if not cint(item.is_group) and not item.metric_type:
			frappe.throw(_("Item {0}: Metric Type is required for a non-group goal").format(item.item_key))
		scale.parse_spec(item.scale_spec)
		if item.target_source == "Provider" and item.target_provider:
			get_provider(item.target_provider, check_available=False)
		for fieldname, label in (
			("target_formula", "Target Formula"),
			("target_drilldown_formula", "Target Drill-down Formula"),
			("calculation_rule", "Calculation Rule"),
			("calculation_drilldown_rule", "Calculation Drill-down Rule"),
			("result_formula", "Result Formula"),
		):
			formulas.check_syntax(item.get(fieldname), label)
	for row in doc.get("template_parameters") or []:
		row.item_key = (row.item_key or "").strip() or None
		if row.item_key and row.item_key not in by_key:
			frappe.throw(_("Parameter {0}: item key {1} does not exist").format(row.code, row.item_key))
	parameters.validate_parameters(doc, table="template_parameters", scope_field="item_key")


def ask_on_create_fields(template: str) -> list[dict]:
	doc = frappe.get_doc(GOAL_TEMPLATE, template)
	fields, seen = [], set()
	for row in doc.get("template_parameters") or []:
		if not cint(row.ask_on_create) or row.code in seen:
			continue
		seen.add(row.code)
		fields.append(
			{
				"code": row.code,
				"label": row.label or row.code,
				"param_type": row.param_type,
				"link_doctype": row.link_doctype,
				"select_options": row.select_options,
				"default": parameters.coerce(row)
				if row.get(parameters.value_field(row.param_type))
				else None,
				"description": row.description,
			}
		)
	return fields


def _apply_value(row: dict, value: Any) -> None:
	param_type = row["param_type"]
	field = parameters.value_field(param_type)
	if param_type == "Link List":
		if isinstance(value, str):
			value = parameters.split_list(value)
		row[field] = "\n".join(str(item) for item in value or [])
	elif param_type == "Check":
		row[field] = cint(value)
	elif param_type in parameters.NUMBER_TYPES:
		row[field] = flt(value)
	else:
		row[field] = value or None


def _is_blank(answer: Any) -> bool:
	return answer is None or answer == "" or answer == []


def _parameter_rows(doc, item, is_root: bool, values: dict) -> list[dict]:
	rows = []
	for param in doc.get("template_parameters") or []:
		if param.item_key != item.item_key and not (is_root and not param.item_key):
			continue
		row = {field: param.get(field) for field in parameters.ROW_FIELDS}
		if cint(param.ask_on_create):
			answer = values.get(param.code)
			if not _is_blank(answer):
				_apply_value(row, answer)
			elif not row.get(parameters.value_field(row["param_type"])):
				# Unanswered and no template default (a stored 0 means none, as in the dialog):
				# a row here would shadow the value inherited from the parent goal.
				continue
		rows.append(row)
	return rows


def _owner_for(item, goal_owner: str, parent_owner: str | None) -> str:
	if item.owner_source == "User" and item.fixed_owner:
		return item.fixed_owner
	if item.owner_source == "Parent Goal Owner" and parent_owner:
		return parent_owner
	return goal_owner


def _code(prefix: str | None, suffix: str | None) -> str | None:
	if not suffix:
		return None
	return f"{prefix}-{suffix}" if prefix else suffix


def create_goals(
	template: str,
	*,
	start_date,
	goal_owner: str,
	code_prefix: str | None = None,
	parent_goal: str | None = None,
	company: str | None = None,
	values: dict | None = None,
	subject_suffix: str | None = None,
	end_date=None,
) -> list[str]:
	"""Create the template tree; with ``end_date`` (a period end) items without their own duration
	span up to it and the other items end no later than it."""
	doc = frappe.get_doc(GOAL_TEMPLATE, template)
	if not cint(doc.is_active):
		frappe.throw(_("Template {0} is not active").format(template))
	frappe.has_permission(GOAL, "create", throw=True)
	parent_owner = None
	if parent_goal:
		if not can_edit_goal(parent_goal):
			frappe.throw(_("You cannot add goals under {0}").format(parent_goal), frappe.PermissionError)
		parent_owner = frappe.db.get_value(GOAL, parent_goal, "goal_owner")
	values = values or {}
	start_date = getdate(start_date)
	end_date = getdate(end_date) if end_date else None
	if end_date and end_date < start_date:
		frappe.throw(_("The end date {0} is before the start date {1}").format(end_date, start_date))
	created: dict[str, str] = {}
	for item in ordered_items(doc):
		is_root = not item.parent_key
		goal_start = add_days(start_date, cint(item.start_offset_days))
		duration = cint(item.duration_days) or cint(doc.default_duration_days) or 90
		goal_end = add_days(goal_start, duration - 1)
		if end_date:
			goal_end = min(goal_end, end_date) if cint(item.duration_days) else end_date
			if getdate(goal_start) > end_date:
				frappe.throw(
					_("Item {0} of template {1} starts after the period end {2}").format(
						item.item_key, doc.name, end_date
					)
				)
		goal = frappe.new_doc(GOAL)
		goal.update({field: item.get(field) for field in COPIED_FIELDS})
		goal.update(
			{
				"subject": f"{item.subject} {subject_suffix}".strip() if subject_suffix else item.subject,
				"goal_code": _code(code_prefix, item.goal_code),
				"goal_type": item.goal_type or doc.goal_type,
				"goal_owner": _owner_for(item, goal_owner, parent_owner),
				"company": company,
				"exp_start_date": goal_start,
				"exp_end_date": goal_end,
				"goal_template": doc.name,
			}
		)
		parent = created.get(item.parent_key) if item.parent_key else parent_goal
		if parent:
			goal.append("parents", {"parent_goal": parent})
		for row in scale.parse_spec(item.scale_spec):
			goal.append("scale", row)
		for row in _parameter_rows(doc, item, is_root, values):
			goal.append("parameters", row)
		goal.flags.skip_related_recalculation = True
		goal.insert()
		created[item.item_key] = goal.name

	roots = [created[key] for key in root_keys(doc)]
	for root in roots:
		engine.recalculate(root)
	return list(created.values())


def _strip_common_prefix(codes: list[str]) -> tuple[str, list[str]]:
	present = [code for code in codes if code]
	if len(present) < 2:
		return "", codes
	prefix = os.path.commonprefix(present)
	cut = prefix.rfind("-")
	if cut <= 0:
		return "", codes
	prefix = prefix[: cut + 1]
	return prefix, [code[len(prefix) :] if code and code.startswith(prefix) else code for code in codes]


def save_as_template(goal: str, template_name: str) -> str:
	if not is_goal_manager():
		frappe.throw(_("Only a Goal Manager can save goals as a template"), frappe.PermissionError)
	if frappe.db.exists(GOAL_TEMPLATE, template_name):
		frappe.throw(_("Template {0} already exists").format(template_name))
	root = frappe.get_doc(GOAL, goal)
	names = [goal, *hierarchy.get_descendants(goal)]
	docs = {name: (root if name == goal else frappe.get_doc(GOAL, name)) for name in names}
	keys = {name: f"G{index + 1}" for index, name in enumerate(names)}
	_prefix, suffixes = _strip_common_prefix([docs[name].goal_code for name in names])

	template = frappe.new_doc(GOAL_TEMPLATE)
	template.template_name = template_name
	template.goal_type = root.goal_type
	template.default_duration_days = date_diff(root.exp_end_date, root.exp_start_date) + 1
	template.description = _("Created from goal {0}").format(root.name)
	for name, suffix in zip(names, suffixes, strict=True):
		doc = docs[name]
		parent_key = None
		if name != goal:
			parent_key = next(keys[p] for p in hierarchy.doc_parent_names(doc) if p in keys)
		item = {field: doc.get(field) for field in COPIED_FIELDS}
		item.update(
			{
				"item_key": keys[name],
				"parent_key": parent_key,
				"subject": doc.subject,
				"goal_code": suffix,
				"goal_type": doc.goal_type,
				"owner_source": "Goal Owner" if doc.goal_owner == root.goal_owner else "User",
				"fixed_owner": None if doc.goal_owner == root.goal_owner else doc.goal_owner,
				"start_offset_days": max(0, date_diff(doc.exp_start_date, root.exp_start_date)),
				"duration_days": date_diff(doc.exp_end_date, doc.exp_start_date) + 1,
				"scale_spec": scale.to_spec(doc.get("scale")),
			}
		)
		template.append("items", item)
		for row in doc.get("parameters") or []:
			param = {field: row.get(field) for field in parameters.ROW_FIELDS}
			param["item_key"] = keys[name]
			template.append("template_parameters", param)
	template.insert()
	return template.name
