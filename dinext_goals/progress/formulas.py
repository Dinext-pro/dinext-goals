"""Sandboxed goal formulas (``frappe.safe_eval``)."""

from __future__ import annotations

import ast
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate


class GoalFormulaError(frappe.ValidationError):
	pass


SAFE_GLOBALS = {
	"min": min,
	"max": max,
	"abs": abs,
	"sum": sum,
	"len": len,
	"bool": bool,
	"str": str,
	"flt": flt,
	"cint": cint,
	"getdate": getdate,
}


def check_syntax(expression: str | None, label: str) -> None:
	if not (expression or "").strip():
		return
	try:
		ast.parse(expression.strip(), mode="eval")
	except SyntaxError as exc:
		frappe.throw(_("{0}: invalid expression ({1})").format(_(label), exc.msg), GoalFormulaError)


def evaluate(expression: str, context: dict[str, Any], label: str) -> Any:
	try:
		return frappe.safe_eval(expression.strip(), dict(SAFE_GLOBALS), context)
	except GoalFormulaError:
		raise
	except frappe.ValidationError as exc:
		raise GoalFormulaError(_("{0}: {1}").format(_(label), exc)) from exc
	except Exception as exc:
		raise GoalFormulaError(_("{0}: {1}").format(_(label), f"{type(exc).__name__}: {exc}")) from exc
