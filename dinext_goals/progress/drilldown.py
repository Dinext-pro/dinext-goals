"""Source documents behind a goal's actual value and target."""

from __future__ import annotations

import ast
from datetime import date, datetime
from typing import Any

import frappe
from frappe import _
from frappe.utils import getdate

from dinext_goals.constants import GOAL
from dinext_goals.goals import hierarchy
from dinext_goals.progress import engine, formulas, planning, sources
from dinext_goals.providers import ProviderUnavailableError, get_provider, missing_params

NAME_LIMIT = 2000


class DocumentList:
	def __init__(self, doctype: str, filters=None, names: list[str] | None = None):
		self.doctype = doctype
		self.filters = filters
		self.names = names


def documents(doctype, filters=None, names=None) -> DocumentList:
	"""Build a drill-down list. The function does not query the database."""
	if not isinstance(doctype, str) or not doctype.strip():
		raise formulas.GoalFormulaError(_("DocType is required"))
	if filters is not None and names is not None:
		raise formulas.GoalFormulaError(_("The document list needs filters or names, not both"))
	if filters is None and names is None:
		raise formulas.GoalFormulaError(_("The document list needs filters or names"))
	if names is not None:
		if isinstance(names, str):
			names = [names]
		if not isinstance(names, list | tuple):
			raise formulas.GoalFormulaError(_("Document names must be a list"))
		names = [str(name) for name in names if name]
	elif not isinstance(filters, dict | list):
		raise formulas.GoalFormulaError(_("Document filters must be a dictionary or a list"))
	return DocumentList(doctype.strip(), filters=filters, names=names)


def evaluate_document_list(expression: str, context: dict[str, Any]) -> DocumentList:
	local = dict(context)
	local["documents"] = documents
	result = formulas.evaluate(expression, local, _("Drill-down expression"))
	if isinstance(result, dict):
		result = documents(
			result.get("doctype") or "",
			filters=result.get("filters"),
			names=result.get("names") if "names" in result else None,
		)
	if not isinstance(result, DocumentList):
		raise formulas.GoalFormulaError(_("The drill-down expression must return a document list"))
	return result


def get_metric_drilldown(doc, tile: str) -> dict:
	if doc.is_group and tile in ("progress", "planned"):
		return _children(doc)
	if doc.is_group:
		return _message(_("This tile has no source documents"))
	if doc.metric_type == "Boolean":
		if tile == "progress":
			return _fact(doc)
		if tile == "planned":
			return _message(_("Planned progress is the share of the planned period that has passed"))
		return _message(_("This tile has no source documents"))
	if tile == "actual":
		return _fact(doc)
	if tile == "target":
		return _plan(doc)
	return _message(_("This tile has no source documents"))


def _fact(doc) -> dict:
	if doc.progress_method != "Auto":
		return _message(_("The actual value was entered on the goal"))
	date_from, date_to = planning.calculation_period(doc.exp_start_date, doc.exp_end_date, getdate())
	if not date_from:
		return _message(
			_("The goal has no planned start, so the actual value does not come from source documents")
		)
	source = doc.metric_source or "Linked Documents"
	if source == "Linked Documents":
		return _linked(doc)
	if source == "Provider":
		return _provider(doc, date_from, date_to, side="value")
	if source == "Python Rule":
		expression = (doc.calculation_drilldown_rule or "").strip()
		if expression:
			return _from_expression(doc, expression)
		return _dialog(doc, doc.calculation_rule, _("Calculation Rule"))
	return _message(_("This tile has no source documents"))


def _plan(doc) -> dict:
	source = doc.target_source or "Manual"
	if source == "Manual":
		return _message(_("The target was entered on the goal"))
	if source == "Provider":
		date_from, date_to = planning.calculation_period(doc.exp_start_date, doc.exp_end_date, getdate())
		return _provider(doc, date_from, date_to, side="target")
	if source == "Formula":
		expression = (doc.target_drilldown_formula or "").strip()
		if expression:
			return _from_expression(doc, expression)
		return _dialog(doc, doc.target_formula, _("Target Formula"))
	return _message(_("This tile has no source documents"))


def _linked(doc) -> dict:
	try:
		params = engine.Calculator().params_of(doc.name, doc)
		filters = sources.linked_filters(doc, params)
	except frappe.ValidationError as exc:
		return _caught(exc)
	return _open(doc.linked_document_type, filters)


def _provider(doc, date_from, date_to, *, side: str) -> dict:
	try:
		key = sources.target_provider_key(doc) if side == "target" else doc.metric_provider
		provider = get_provider(key)
		params = engine.Calculator().params_of(doc.name, doc)
		missing = missing_params(provider, params)
		if missing:
			frappe.throw(
				_("Metric provider {0} needs parameters: {1}").format(_(provider.label), ", ".join(missing))
			)
		described = provider.source_documents(doc, params, date_from, date_to, side=side)
	except (frappe.ValidationError, ProviderUnavailableError) as exc:
		return _caught(exc)
	if described.get("empty"):
		return _message(_("No source documents"))
	return _open(described.get("doctype"), described.get("filters") or {}, note=described.get("note"))


def _from_expression(doc, expression: str) -> dict:
	calculator = engine.Calculator()
	calculator.docs[doc.name] = doc
	try:
		described = evaluate_document_list(expression, calculator.stored_context(doc))
	except formulas.GoalFormulaError as exc:
		return _caught(exc)
	if described.names is not None:
		if not described.names:
			return _message(_("No source documents"))
		if len(described.names) > NAME_LIMIT:
			return _message(_("The document list is too long to open"))
		return _open(described.doctype, {"name": ["in", described.names]})
	return _open(described.doctype, described.filters or {})


def _children(doc) -> dict:
	names = hierarchy.get_child_names(doc.name)
	if names:
		names = frappe.get_list(GOAL, filters={"name": ["in", names]}, pluck="name", limit_page_length=0)
	if not names:
		return _message(_("No child goals"))
	if len(names) > NAME_LIMIT:
		return _message(_("The document list is too long to open"))
	return _open(GOAL, {"name": ["in", names]})


def _dialog(doc, expression: str | None, title: str) -> dict:
	return {
		"kind": "dialog",
		"title": title,
		"expression": expression or "",
		"links": _expression_links(doc, expression or ""),
	}


def _expression_links(doc, expression: str) -> list[dict]:
	try:
		tree = ast.parse(expression.strip() or "None", mode="eval")
	except SyntaxError:
		return []
	links = []
	for node in ast.walk(tree):
		if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
			continue
		if node.func.id not in ("child", "tree_goal") or not node.args:
			continue
		argument = node.args[0]
		if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
			continue
		links.append(_goal_link(doc, node.func.id, argument.value))
	return links


def _goal_link(doc, kind: str, code: str) -> dict:
	if kind == "child":
		members = [] if doc.is_new() else hierarchy.get_child_names(doc.name)
		scope = _("child()")
	else:
		members = hierarchy.get_tree_members(
			None if doc.is_new() else doc.name, hierarchy.doc_parent_names(doc)
		)
		scope = _("tree_goal()")
	rows = (
		frappe.get_list(
			GOAL,
			filters={"name": ["in", members]},
			fields=["name", "goal_code", "subject"],
			limit_page_length=0,
		)
		if members
		else []
	)
	try:
		row = engine._pick_by_code(rows, code, scope)
	except formulas.GoalFormulaError as exc:
		return {"code": code, "error": str(exc)}
	if kind == "tree_goal" and row.name == doc.name:
		return {"code": code, "error": _("tree_goal(): a goal cannot reference itself")}
	return {"doctype": GOAL, "name": row.name, "label": row.subject or row.name}


def _open(doctype: str | None, filters, note: str | None = None) -> dict:
	if not doctype or not frappe.db.exists("DocType", doctype):
		return _message(_("DocType {0} does not exist").format(doctype or ""))
	if not frappe.has_permission(doctype, "read"):
		denied = _message(_("You are not allowed to read {0}").format(_(doctype)))
		denied["restricted"] = 1
		denied["doctype"] = doctype
		return denied
	payload = {"kind": "list", "doctype": doctype, "filters": _plain(as_route_options(filters))}
	if note:
		payload["note"] = note
	return payload


def as_route_options(filters: dict | list) -> dict:
	if isinstance(filters, dict):
		return filters
	options = {}
	for item in filters or []:
		if isinstance(item, list | tuple) and len(item) >= 3:
			field, op, value = item[-3], item[-2], item[-1]
			options[field] = value if op == "=" else [op, value]
	return options


def _plain(value):
	if isinstance(value, datetime):
		return str(value)
	if isinstance(value, date):
		return str(value)
	if isinstance(value, list | tuple):
		return [_plain(item) for item in value]
	if isinstance(value, dict):
		return {key: _plain(item) for key, item in value.items()}
	return value


def _message(text: str) -> dict:
	return {"kind": "message", "text": text}


def _caught(exc: Exception) -> dict:
	if frappe.local.message_log:
		frappe.clear_last_message()
	return _message(str(exc))
