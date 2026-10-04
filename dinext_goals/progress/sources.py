"""Actual value sources: linked documents, metric providers and Python rules."""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt

from dinext_goals.parameters import substitute_params
from dinext_goals.progress import formulas
from dinext_goals.providers import get_provider, missing_params

NUMERIC_FIELDTYPES = ("Int", "Float", "Currency", "Percent", "Duration")
AGGREGATE_FUNCTIONS = {"Sum": "sum", "Avg": "avg", "Max": "max", "Min": "min"}
STANDARD_NUMERIC_FIELDS = ("idx", "docstatus")


def parse_filters(text: str | None) -> dict | list:
	if not (text or "").strip():
		return {}
	try:
		value = json.loads(text)
	except ValueError as exc:
		frappe.throw(_("Linked document filter is not valid JSON: {0}").format(exc))
	if not isinstance(value, dict | list):
		frappe.throw(_("Linked document filter must be a JSON object or list"))
	return value


def validate_linked_config(
	doctype: str | None, fieldname: str | None, aggregation: str | None, filters: str | None
):
	if not doctype:
		frappe.throw(_("Linked Document Type is required for the Linked Documents source"))
	if not frappe.db.exists("DocType", doctype):
		frappe.throw(_("DocType {0} does not exist").format(doctype))
	parse_filters(filters)
	if (aggregation or "Sum") == "Count":
		return
	if not fieldname:
		frappe.throw(_("Linked Document Field is required for aggregation {0}").format(_(aggregation)))
	if fieldname in STANDARD_NUMERIC_FIELDS:
		return
	field = frappe.get_meta(doctype).get_field(fieldname)
	if not field:
		frappe.throw(_("Field {0} does not exist in {1}").format(fieldname, _(doctype)))
	if field.fieldtype not in NUMERIC_FIELDTYPES:
		frappe.throw(_("Field {0} of {1} must be numeric").format(fieldname, _(doctype)))


def linked_filters(goal, params) -> dict | list:
	return substitute_params(parse_filters(goal.linked_document_filter), params)


def linked_documents_value(goal, params) -> float:
	validate_linked_config(
		goal.linked_document_type, goal.linked_document_field, goal.aggregation, goal.linked_document_filter
	)
	doctype = goal.linked_document_type
	filters = linked_filters(goal, params)
	aggregation = goal.aggregation or "Sum"
	if aggregation == "Count":
		return flt(frappe.db.count(doctype, filters))
	field = goal.linked_document_field
	if aggregation == "Latest":
		rows = frappe.get_all(doctype, filters=filters, fields=[field], order_by="creation desc", limit=1)
		return flt(rows[0].get(field)) if rows else 0.0
	function = AGGREGATE_FUNCTIONS[aggregation]
	rows = frappe.get_all(doctype, filters=filters, fields=[f"{function}(`{field}`) as value"])
	return flt(rows[0].value) if rows else 0.0


def provider_value(goal, params, date_from, date_to) -> float:
	provider = get_provider(goal.metric_provider)
	missing = missing_params(provider, params)
	if missing:
		frappe.throw(
			_("Metric provider {0} needs parameters: {1}").format(_(provider.label), ", ".join(missing))
		)
	return flt(provider.get_value(goal, params, date_from, date_to))


def target_provider_key(goal) -> str | None:
	return goal.get("target_provider") or goal.get("metric_provider")


def provider_target(goal, params) -> float:
	provider = get_provider(target_provider_key(goal))
	if not provider.supports_target:
		frappe.throw(_("Metric provider {0} does not provide a target").format(_(provider.label)))
	missing = missing_params(provider, params)
	if missing:
		frappe.throw(
			_("Metric provider {0} needs parameters: {1}").format(_(provider.label), ", ".join(missing))
		)
	return flt(provider.get_target(goal, params))


def actual_value(goal, params, date_from, date_to, context: dict[str, Any]) -> float:
	source = goal.metric_source or "Linked Documents"
	if source == "Provider":
		return provider_value(goal, params, date_from, date_to)
	if source == "Python Rule":
		if not (goal.calculation_rule or "").strip():
			frappe.throw(_("Calculation Rule is empty"))
		return flt(formulas.evaluate(goal.calculation_rule, context, "Calculation Rule"))
	return linked_documents_value(goal, params)


def validate_source_config(doc) -> None:
	formulas.check_syntax(doc.result_formula, "Result Formula")
	if doc.is_group:
		return
	if doc.progress_method == "Auto":
		source = doc.metric_source or "Linked Documents"
		if source == "Linked Documents":
			validate_linked_config(
				doc.linked_document_type,
				doc.linked_document_field,
				doc.aggregation,
				doc.linked_document_filter,
			)
		elif source == "Provider":
			if not doc.metric_provider:
				frappe.throw(_("Metric Provider is required for the Provider source"))
		elif source == "Python Rule":
			formulas.check_syntax(doc.calculation_rule, "Calculation Rule")
			formulas.check_syntax(doc.get("calculation_drilldown_rule"), "Calculation Drill-down Rule")
	if doc.target_source == "Provider":
		key = target_provider_key(doc)
		if not key:
			frappe.throw(_("Target Provider is required for the Provider target source"))
		provider = get_provider(key, check_available=False)
		if not provider.supports_target:
			frappe.throw(_("Metric provider {0} does not provide a target").format(_(provider.label)))
	if doc.target_source == "Formula":
		formulas.check_syntax(doc.target_formula, "Target Formula")
		formulas.check_syntax(doc.get("target_drilldown_formula"), "Target Drill-down Formula")
