"""Typed goal parameters: validation, inheritance down the hierarchy and locking."""

from __future__ import annotations

import re
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, formatdate, getdate

from dinext_goals.constants import GOAL, GOAL_PARAMETER, STATUS_DRAFT
from dinext_goals.goals import hierarchy

CODE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
NUMBER_TYPES = ("Int", "Float", "Currency", "Percent")
LINK_TYPES = ("Link", "Link List")
VALUE_FIELDS = ("value_number", "value_data", "value_date", "value_check", "value_link", "value_list")
ROW_FIELDS = (
	"code",
	"label",
	"param_type",
	"link_doctype",
	"select_options",
	*VALUE_FIELDS,
	"inherit",
	"editable_when_active",
	"description",
)
PARAM_REF_PREFIX = "=param:"
PROJECT = "Project"
GOAL_PROJECT = "Goal Project"
PROJECTS_FIELD = "goal_projects"


def value_field(param_type: str) -> str:
	if param_type in NUMBER_TYPES:
		return "value_number"
	return {
		"Data": "value_data",
		"Select": "value_data",
		"Date": "value_date",
		"Check": "value_check",
		"Link": "value_link",
		"Link List": "value_list",
	}.get(param_type, "value_data")


def split_list(text: str | None) -> list[str]:
	return [line.strip() for line in (text or "").replace(",", "\n").splitlines() if line.strip()]


def coerce(row) -> Any:
	"""Python value of a parameter row as seen by formulas and providers."""
	param_type = row.get("param_type")
	if param_type == "Int":
		return cint(row.get("value_number"))
	if param_type in ("Float", "Currency"):
		return flt(row.get("value_number"))
	if param_type == "Percent":
		return flt(row.get("value_number")) / 100.0
	if param_type == "Date":
		return getdate(row.get("value_date")) if row.get("value_date") else None
	if param_type == "Check":
		return bool(cint(row.get("value_check")))
	if param_type == "Link":
		return row.get("value_link") or None
	if param_type == "Link List":
		return split_list(row.get("value_list"))
	return row.get("value_data") or ""


def display(row) -> str:
	param_type = row.get("param_type")
	if param_type == "Percent":
		return f"{flt(row.get('value_number')):g}%"
	if param_type in NUMBER_TYPES:
		return f"{flt(row.get('value_number')):g}"
	if param_type == "Date":
		return formatdate(row.get("value_date")) if row.get("value_date") else ""
	if param_type == "Check":
		return _("Yes") if cint(row.get("value_check")) else _("No")
	if param_type == "Link List":
		return ", ".join(split_list(row.get("value_list")))
	value = coerce(row)
	return "" if value is None else str(value)


def _signature(row) -> tuple:
	return (
		row.get("param_type"),
		row.get("link_doctype") or "",
		repr(coerce(row)),
		cint(row.get("inherit")),
		cint(row.get("editable_when_active")),
	)


def _value_signature(row) -> tuple:
	return (row.get("param_type"), repr(coerce(row)))


def validate_row(row) -> None:
	code = (row.code or "").strip()
	row.code = code
	if not CODE_RE.match(code):
		frappe.throw(
			_(
				"Row {0}: parameter code {1} must start with a letter or underscore and contain only a-z, 0-9 and _"
			).format(row.idx, frappe.bold(code))
		)
	param_type = row.param_type
	if param_type in LINK_TYPES:
		if not row.link_doctype or not frappe.db.exists("DocType", row.link_doctype):
			frappe.throw(_("Row {0}: parameter {1} needs a valid Link DocType").format(row.idx, code))
	else:
		row.link_doctype = None

	keep = value_field(param_type)
	for fieldname in VALUE_FIELDS:
		if fieldname != keep:
			row.set(fieldname, 0 if fieldname == "value_check" else None)

	if param_type == "Int":
		row.value_number = cint(row.value_number)
	if param_type == "Select":
		options = split_list(row.select_options)
		if row.value_data and row.value_data not in options:
			frappe.throw(
				_("Row {0}: value {1} is not one of the options of parameter {2}").format(
					row.idx, row.value_data, code
				)
			)
	if param_type == "Link" and row.value_link and not frappe.db.exists(row.link_doctype, row.value_link):
		frappe.throw(
			_("Row {0}: {1} {2} does not exist").format(row.idx, _(row.link_doctype), row.value_link)
		)
	if param_type == "Link List":
		names = split_list(row.value_list)
		missing = [name for name in names if not frappe.db.exists(row.link_doctype, name)]
		if missing:
			frappe.throw(
				_("Row {0}: {1} {2} does not exist").format(row.idx, _(row.link_doctype), ", ".join(missing))
			)
		row.value_list = "\n".join(dict.fromkeys(names))
	row.value_display = display(row)


def validate_parameters(doc, table: str = "parameters", scope_field: str | None = None) -> None:
	seen: set[tuple] = set()
	for row in doc.get(table) or []:
		validate_row(row)
		key = (row.get(scope_field) if scope_field else None, row.code)
		if key in seen:
			frappe.throw(_("Parameter code {0} is used more than once").format(frappe.bold(row.code)))
		seen.add(key)


def _row_dict(row) -> frappe._dict:
	return frappe._dict({field: row.get(field) for field in ROW_FIELDS})


def _load_inherited(goals: list[str]) -> dict[str, list[frappe._dict]]:
	result: dict[str, list[frappe._dict]] = {goal: [] for goal in goals}
	if not goals:
		return result
	for row in frappe.get_all(
		GOAL_PARAMETER,
		filters={"parent": ["in", goals], "parenttype": GOAL, "parentfield": "parameters", "inherit": 1},
		fields=["parent", *ROW_FIELDS],
		order_by="idx asc",
	):
		result[row.parent].append(row)
	return result


def _goal_titles(goals: list[str]) -> dict[str, str]:
	return {
		row.name: row.subject
		for row in frappe.get_all(GOAL, filters={"name": ["in", goals]}, fields=["name", "subject"])
	}


def resolve_effective(goal: str | None, own_rows, direct_parents) -> dict[str, frappe._dict]:
	"""Own parameters plus inherited ones from the nearest ancestor; equal-distance conflicts raise."""
	result: dict[str, frappe._dict] = {}
	for row in own_rows or []:
		if not row.get("code"):
			continue
		result[row.get("code")] = frappe._dict(row=_row_dict(row), source=goal, inherited=False)

	checked_types: set[str] = set()
	for level in hierarchy.ancestor_levels(goal, direct_parents):
		inherited = _load_inherited(level)
		found: dict[str, list[tuple[str, frappe._dict]]] = {}
		for name in level:
			for row in inherited[name]:
				found.setdefault(row.code, []).append((name, row))
		for code, entries in found.items():
			if code in result:
				current = result[code]
				if not current.inherited and code not in checked_types:
					checked_types.add(code)
					if entries[0][1].param_type != current.row.param_type:
						frappe.throw(
							_("Parameter {0} has type {1} but the inherited parameter has type {2}").format(
								frappe.bold(code), _(current.row.param_type), _(entries[0][1].param_type)
							)
						)
				continue
			if len({_value_signature(row) for _name, row in entries}) > 1:
				titles = _goal_titles([name for name, _row in entries])
				frappe.throw(
					_(
						"Parameter {0} is inherited with different values from {1}. Set the parameter on this goal to resolve the conflict."
					).format(frappe.bold(code), ", ".join(titles.get(name, name) for name, _row in entries))
				)
			name, row = entries[0]
			result[code] = frappe._dict(row=row, source=name, inherited=True)
	return result


def resolve_for_doc(doc) -> dict[str, frappe._dict]:
	return resolve_effective(
		None if doc.is_new() else doc.name, doc.get("parameters"), hierarchy.doc_parent_names(doc)
	)


def resolve_for_name(goal: str) -> dict[str, frappe._dict]:
	own = frappe.get_all(
		GOAL_PARAMETER,
		filters={"parent": goal, "parenttype": GOAL, "parentfield": "parameters"},
		fields=list(ROW_FIELDS),
		order_by="idx asc",
	)
	return resolve_effective(goal, own, hierarchy.get_parent_names(goal))


def to_values(resolved: dict[str, frappe._dict]) -> frappe._dict:
	return frappe._dict({code: coerce(item.row) for code, item in resolved.items()})


def get_effective_params(goal) -> frappe._dict:
	if isinstance(goal, str):
		return to_values(resolve_for_name(goal))
	return to_values(resolve_for_doc(goal))


def describe(resolved: dict[str, frappe._dict]) -> list[dict]:
	sources = [item.source for item in resolved.values() if item.inherited and item.source]
	titles = _goal_titles(sources) if sources else {}
	return [
		{
			"code": code,
			"label": item.row.label or code,
			"param_type": item.row.param_type,
			"value": display(item.row),
			"inherited": item.inherited,
			"source": item.source,
			"source_title": titles.get(item.source) if item.inherited else None,
			"editable_when_active": cint(item.row.editable_when_active),
		}
		for code, item in sorted(resolved.items())
	]


def validate_locks(doc, before) -> None:
	if not before:
		return
	before_rows = {row.code: row for row in before.get("parameters") or []}
	now_rows = {row.code: row for row in doc.get("parameters") or []}

	if before.status != STATUS_DRAFT:
		if set(before_rows) != set(now_rows):
			frappe.throw(_("Parameters cannot be added or removed after the goal leaves Draft"))
		for code, row in now_rows.items():
			old = before_rows[code]
			if _signature(old) != _signature(row) and not cint(old.editable_when_active):
				frappe.throw(
					_("Parameter {0} is locked after the goal leaves Draft").format(frappe.bold(code))
				)

	changed_inherited = [
		code
		for code, old in before_rows.items()
		if cint(old.inherit)
		and not cint(old.editable_when_active)
		and (code not in now_rows or _signature(old) != _signature(now_rows[code]))
	]
	if changed_inherited and not doc.is_new():
		_assert_no_locked_receivers(doc.name, changed_inherited)


def _assert_no_locked_receivers(goal: str, codes: list[str]) -> None:
	descendants = hierarchy.get_descendants(goal)
	if not descendants:
		return
	live = frappe.get_all(
		GOAL,
		filters={"name": ["in", descendants], "status": ["!=", STATUS_DRAFT]},
		fields=["name", "subject"],
	)
	for row in live:
		resolved = resolve_for_name(row.name)
		for code in codes:
			if code in resolved and resolved[code].source == goal:
				frappe.throw(
					_(
						"Parameter {0} cannot be changed: child goal {1} is already out of Draft and uses it"
					).format(frappe.bold(code), frappe.bold(row.subject))
				)


def signature_of(doc) -> tuple:
	return tuple(sorted((row.code, _signature(row)) for row in doc.get("parameters") or []))


def projects_of(resolved: dict[str, frappe._dict]) -> list[str]:
	"""Existing projects named by effective Link / Link List parameters over Project."""
	names: set[str] = set()
	for item in resolved.values():
		row = item.row
		if row.get("link_doctype") != PROJECT or row.get("param_type") not in LINK_TYPES:
			continue
		value = coerce(row)
		names.update(value if isinstance(value, list) else [value] if value else [])
	if not names:
		return []
	return sorted(frappe.get_all(PROJECT, filters={"name": ["in", list(names)]}, pluck="name"))


def set_doc_projects(doc, resolved: dict[str, frappe._dict]) -> None:
	projects = projects_of(resolved)
	if [row.project for row in doc.get(PROJECTS_FIELD) or []] != projects:
		doc.set(PROJECTS_FIELD, [{"project": project} for project in projects])


def sync_goal_projects(goals: list[str]) -> None:
	"""Rewrite the project relation of saved goals in place, without saving them."""
	for goal in goals:
		try:
			projects = projects_of(resolve_for_name(goal))
		except frappe.ValidationError:
			continue
		keys = {"parent": goal, "parenttype": GOAL, "parentfield": PROJECTS_FIELD}
		stored = frappe.get_all(GOAL_PROJECT, filters=keys, pluck="project", order_by="idx asc")
		if stored == projects:
			continue
		frappe.db.delete(GOAL_PROJECT, keys)
		for idx, project in enumerate(projects, start=1):
			row = frappe.get_doc({"doctype": GOAL_PROJECT, **keys, "idx": idx, "project": project})
			row.set_new_name()
			row.db_insert()


def _is_ref(value: Any) -> bool:
	return isinstance(value, str) and value.startswith(PARAM_REF_PREFIX)


def _lookup(value: str, params: dict) -> Any:
	code = value[len(PARAM_REF_PREFIX) :].strip()
	if code not in params:
		frappe.throw(
			_("Parameter {0} used in the filter is not defined for this goal").format(frappe.bold(code))
		)
	result = params[code]
	return [str(item) for item in result] if isinstance(result, list | tuple) else result


def _operator_for(op: str, value: Any) -> str:
	if isinstance(value, list):
		return {"=": "in", "!=": "not in"}.get(op, op)
	return op


def substitute_params(filters: Any, params: dict) -> Any:
	"""Replace ``"=param:<code>"`` values; list values become ``in`` filters."""
	if isinstance(filters, dict):
		out = {}
		for field, value in filters.items():
			if _is_ref(value):
				resolved = _lookup(value, params)
				out[field] = ["in", resolved] if isinstance(resolved, list) else resolved
			elif isinstance(value, list | tuple) and len(value) == 2 and _is_ref(value[1]):
				resolved = _lookup(value[1], params)
				out[field] = [_operator_for(value[0], resolved), resolved]
			else:
				out[field] = value
		return out
	if isinstance(filters, list | tuple):
		out_list = []
		for item in filters:
			if isinstance(item, list | tuple) and len(item) in (3, 4) and _is_ref(item[-1]):
				resolved = _lookup(item[-1], params)
				item = [*item[:-2], _operator_for(item[-2], resolved), resolved]
			out_list.append(item)
		return out_list
	return filters
