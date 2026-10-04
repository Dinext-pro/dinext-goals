"""Goal recalculation: descendants first, then the goal, then its ancestors."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, nowdate

from dinext_goals import parameters
from dinext_goals.constants import (
	GOAL,
	GOAL_LOG,
	LIVE_STATUSES,
	LOG_SOURCE_AUTO,
	SETTINGS,
	STATUS_CANCELLED,
	STATUS_CLOSED,
	STATUS_DRAFT,
)
from dinext_goals.goals import hierarchy
from dinext_goals.progress import formulas, metrics, planning, rollup, scale, sources

FROZEN_STATUSES = (STATUS_CLOSED, STATUS_CANCELLED)
FLOAT_FIELDS = (
	"target",
	"current_value",
	"progress",
	"achievement_percent",
	"planned_progress",
	"deviation",
	"coefficient",
	"result_value",
)
STORED_FIELDS = (*FLOAT_FIELDS, "rag_status", "is_overdue")
LOGGED_FIELDS = ("progress", "current_value", "result_value")
NEW_KEY = "__new__"


def thresholds() -> tuple[float, float]:
	yellow = frappe.db.get_single_value(SETTINGS, "yellow_threshold")
	red = frappe.db.get_single_value(SETTINGS, "red_threshold")
	return (flt(yellow) if yellow not in (None, "") else 10.0, flt(red) if red not in (None, "") else 25.0)


def differs(fieldname: str, old: Any, new: Any) -> bool:
	if fieldname in FLOAT_FIELDS:
		return abs(flt(old) - flt(new)) > 1e-6
	if fieldname == "is_overdue":
		return cint(old) != cint(new)
	return (old or "") != (new or "")


def stored_values(doc) -> frappe._dict:
	return frappe._dict({field: doc.get(field) for field in STORED_FIELDS})


def write_log(goal: str, values, source: str, comment: str | None = None) -> None:
	frappe.get_doc(
		{
			"doctype": GOAL_LOG,
			"goal": goal,
			"log_date": now_datetime(),
			"author": frappe.session.user,
			"source": source,
			"progress": flt(values.get("progress")),
			"planned_progress": flt(values.get("planned_progress")),
			"current_value": flt(values.get("current_value")),
			"achievement_percent": flt(values.get("achievement_percent")),
			"coefficient": flt(values.get("coefficient")),
			"result_value": flt(values.get("result_value")),
			"comment": comment,
		}
	).insert(ignore_permissions=True)


def _matches_code(goal_code: str | None, code: str) -> bool:
	return bool(goal_code) and (goal_code == code or goal_code.endswith("-" + code))


def _pick_by_code(rows: list, code: str, scope: str):
	exact = [row for row in rows if row.goal_code == code]
	if len(exact) == 1:
		return exact[0]
	matches = exact or [row for row in rows if _matches_code(row.goal_code, code)]
	if not matches:
		raise formulas.GoalFormulaError(_("{0}: no goal with code {1}").format(scope, code))
	if len(matches) > 1:
		raise formulas.GoalFormulaError(_("{0}: several goals match code {1}").format(scope, code))
	return matches[0]


class Calculator:
	def __init__(self, on_date=None, source: str = LOG_SOURCE_AUTO):
		self.on_date = getdate(on_date or nowdate())
		self.source = source
		self.yellow, self.red = thresholds()
		self.docs: dict[str, Any] = {}
		self.values: dict[str, frappe._dict] = {}
		self.params: dict[str, frappe._dict] = {}
		self.computing: set[str] = set()
		self.errors: dict[str, str] = {}
		self.changed: list[str] = []
		self._tree_rows: dict[tuple, list] = {}

	def load(self, name: str):
		if name not in self.docs:
			self.docs[name] = frappe.get_doc(GOAL, name)
		return self.docs[name]

	def params_of(self, key: str, doc) -> frappe._dict:
		if key not in self.params:
			self.params[key] = parameters.get_effective_params(doc)
		return self.params[key]

	def view(self, name: str) -> frappe._dict:
		"""Values of another goal: computed in this run when possible, otherwise stored."""
		if name not in self.values:
			doc = self.load(name)
			if doc.status in FROZEN_STATUSES or name in self.computing:
				return self._make_view(name, doc, stored_values(doc))
			self.compute(name)
		return self._make_view(name, self.load(name), self.values[name])

	def _make_view(self, key: str, doc, values) -> frappe._dict:
		return frappe._dict(
			name=doc.name,
			subject=doc.subject,
			goal_code=doc.goal_code,
			status=doc.status,
			weight=flt(doc.weight),
			baseline=flt(doc.baseline),
			target=flt(values.get("target")),
			value=flt(values.get("current_value")),
			current_value=flt(values.get("current_value")),
			progress=flt(values.get("progress")),
			achievement=flt(values.get("achievement_percent")),
			coefficient=flt(values.get("coefficient")),
			result=flt(values.get("result_value")),
			planned_progress=flt(values.get("planned_progress")),
			params=self.params_of(key, doc),
		)

	def _child(self, doc, code: str) -> frappe._dict:
		names = [] if doc.is_new() else hierarchy.get_child_names(doc.name)
		rows = (
			frappe.get_all(GOAL, filters={"name": ["in", names]}, fields=["name", "goal_code"])
			if names
			else []
		)
		return self.view(_pick_by_code(rows, code, _("child()")).name)

	def _tree_goal(self, doc, code: str) -> frappe._dict:
		parents = tuple(hierarchy.doc_parent_names(doc))
		key = (None if doc.is_new() else doc.name, parents)
		if key not in self._tree_rows:
			members = hierarchy.get_tree_members(key[0], parents)
			self._tree_rows[key] = (
				frappe.get_all(GOAL, filters={"name": ["in", members]}, fields=["name", "goal_code"])
				if members
				else []
			)
		row = _pick_by_code(self._tree_rows[key], code, _("tree_goal()"))
		if row.name == doc.name:
			raise formulas.GoalFormulaError(_("tree_goal(): a goal cannot reference itself"))
		return self.view(row.name)

	def stored_context(self, doc) -> dict:
		"""Formula context that reads stored values and does not recalculate."""
		key = doc.name
		date_from, date_to = planning.calculation_period(doc.exp_start_date, doc.exp_end_date, self.on_date)
		return {
			"params": self.params_of(key, doc),
			"child": lambda code: self._stored_match(doc, code, tree=False),
			"tree_goal": lambda code: self._stored_match(doc, code, tree=True),
			"date_from": date_from,
			"date_to": date_to,
			"today": self.on_date,
			"goal": self._make_view(key, doc, stored_values(doc)),
		}

	def _stored_match(self, doc, code: str, *, tree: bool) -> frappe._dict:
		if tree:
			parents = tuple(hierarchy.doc_parent_names(doc))
			members = hierarchy.get_tree_members(None if doc.is_new() else doc.name, parents)
			scope = _("tree_goal()")
		else:
			members = [] if doc.is_new() else hierarchy.get_child_names(doc.name)
			scope = _("child()")
		rows = (
			frappe.get_list(
				GOAL, filters={"name": ["in", members]}, fields=["name", "goal_code"], limit_page_length=0
			)
			if members
			else []
		)
		row = _pick_by_code(rows, code, scope)
		if tree and row.name == doc.name:
			raise formulas.GoalFormulaError(_("tree_goal(): a goal cannot reference itself"))
		loaded = self.load(row.name)
		return self._make_view(row.name, loaded, stored_values(loaded))

	def _context(self, doc, key: str, params, date_from, date_to, values=None) -> dict:
		context = {
			"params": params,
			"child": lambda code: self._child(doc, code),
			"tree_goal": lambda code: self._tree_goal(doc, code),
			"date_from": date_from,
			"date_to": date_to,
			"today": self.on_date,
		}
		if values is not None:
			context["goal"] = self._make_view(key, doc, values)
		else:
			context["goal"] = self._make_view(key, doc, stored_values(doc))
		return context

	def _calculate(self, key: str, doc) -> frappe._dict:
		params = self.params_of(key, doc)
		date_from, date_to = planning.calculation_period(doc.exp_start_date, doc.exp_end_date, self.on_date)
		values = stored_values(doc)

		if doc.is_group:
			achievement = None
			if doc.progress_method == "Auto" and not doc.is_new():
				children = [
					{
						"progress": c.progress,
						"achievement": c.achievement,
						"weight": c.weight,
						"status": c.status,
					}
					for c in (self.view(name) for name in hierarchy.get_child_names(doc.name))
				]
				rolled = rollup.weighted(children, "progress")
				if rolled is not None:
					values.progress = rolled
					achievement = rollup.weighted(children, "achievement")
			values.progress = metrics.clamp_progress(values.progress)
			values.achievement_percent = flt(values.progress) if achievement is None else achievement
		else:
			context = self._context(doc, key, params, date_from, date_to)
			if doc.status == STATUS_DRAFT and doc.target_source == "Provider":
				values.target = sources.provider_target(doc, params)
			elif (
				doc.status == STATUS_DRAFT
				and doc.target_source == "Formula"
				and (doc.target_formula or "").strip()
			):
				values.target = flt(formulas.evaluate(doc.target_formula, context, "Target Formula"))
			if doc.progress_method == "Auto" and date_from:
				values.current_value = sources.actual_value(doc, params, date_from, date_to, context)
			values.achievement_percent = metrics.achievement(
				doc.metric_type, doc.baseline, values.target, values.current_value
			)
			values.progress = metrics.clamp_progress(values.achievement_percent)

		values.planned_progress = planning.planned_progress(
			doc.exp_start_date, doc.exp_end_date, self.on_date
		)
		values.deviation = round(flt(values.progress) - flt(values.planned_progress), 2)
		overdue = planning.is_overdue(doc.status, doc.exp_end_date, values.progress, self.on_date)
		values.is_overdue = 1 if overdue else 0
		values.rag_status = planning.rag(values.deviation, overdue, self.yellow, self.red)
		coefficient = scale.coefficient(doc.get("scale"), values.achievement_percent)
		values.coefficient = flt(coefficient) if coefficient is not None else 0.0
		if (doc.result_formula or "").strip():
			context = self._context(doc, key, params, date_from, date_to, values)
			values.result_value = flt(formulas.evaluate(doc.result_formula, context, "Result Formula"))
		else:
			values.result_value = 0.0
		return values

	def compute(self, name: str | None, doc=None) -> frappe._dict:
		key = name or NEW_KEY
		if doc is not None:
			self.docs[key] = doc
		doc = self.load(key)
		if doc.status in FROZEN_STATUSES:
			self.values[key] = stored_values(doc)
			return self.values[key]
		self.computing.add(key)
		message_count = len(frappe.local.message_log or [])
		try:
			self.values[key] = self._calculate(key, doc)
		except (frappe.ValidationError, formulas.GoalFormulaError) as exc:
			del frappe.local.message_log[message_count:]
			self.errors[key] = str(exc) or type(exc).__name__
			self.values[key] = stored_values(doc)
		except Exception as exc:
			del frappe.local.message_log[message_count:]
			frappe.log_error(title=f"Goal recalculation failed: {key}")
			self.errors[key] = f"{type(exc).__name__}: {exc}"
			self.values[key] = stored_values(doc)
		finally:
			self.computing.discard(key)
		return self.values[key]

	def apply_to_doc(self, doc) -> None:
		values = self.values[NEW_KEY if doc.is_new() else doc.name]
		for field in STORED_FIELDS:
			doc.set(field, values.get(field))
		doc.last_calculated_on = now_datetime()

	def persist(self, name: str) -> bool:
		doc = self.load(name)
		if doc.status in FROZEN_STATUSES or name not in self.values or name in self.errors:
			return False
		values = self.values[name]
		changes = {
			field: values.get(field)
			for field in STORED_FIELDS
			if differs(field, doc.get(field), values.get(field))
		}
		changes["last_calculated_on"] = now_datetime()
		frappe.db.set_value(GOAL, name, changes, update_modified=False)
		logged = any(field in changes for field in LOGGED_FIELDS)
		for field, value in changes.items():
			doc.set(field, value)
		if logged:
			write_log(name, values, self.source)
			self.changed.append(name)
		return logged

	def run(self, names: list[str]) -> dict:
		for name in names:
			if name not in self.values:
				self.compute(name)
			self.persist(name)
		return self.summary(names)

	def summary(self, names: list[str]) -> dict:
		return {
			"recalculated": len(names),
			"changed": len(self.changed),
			"errors": [{"goal": name, "message": message} for name, message in self.errors.items()],
		}


def recalculation_order(
	goal: str, *, include_descendants: bool = True, include_self: bool = True
) -> list[str]:
	lower = hierarchy.get_descendants(goal) if include_descendants else []
	if include_self:
		lower.append(goal)
	ordered = hierarchy.topological_order(lower) if lower else []
	return ordered + hierarchy.topological_order(hierarchy.get_ancestors(goal))


def recalculate(goal: str, *, on_date=None, source: str = LOG_SOURCE_AUTO) -> dict:
	calculator = Calculator(on_date, source)
	return calculator.run(recalculation_order(goal))


def compute_in_memory(doc, on_date=None) -> dict[str, str]:
	"""Recompute the goal's own values before saving; returns errors instead of raising."""
	calculator = Calculator(on_date)
	calculator.compute(None if doc.is_new() else doc.name, doc)
	calculator.apply_to_doc(doc)
	return calculator.errors


def recalculate_related(doc, *, include_descendants: bool) -> dict:
	"""After a goal is saved: refresh descendants (when their inputs changed) and all ancestors."""
	calculator = Calculator()
	calculator.docs[doc.name] = doc
	names = recalculation_order(doc.name, include_descendants=include_descendants)
	if not include_descendants:
		calculator.values[doc.name] = stored_values(doc)
		names = [name for name in names if name != doc.name]
	return calculator.run(names)


def recalculate_active(on_date=None) -> dict:
	names = frappe.get_all(GOAL, filters={"status": ["in", list(LIVE_STATUSES)]}, pluck="name")
	calculator = Calculator(on_date)
	return calculator.run(hierarchy.topological_order(names))
