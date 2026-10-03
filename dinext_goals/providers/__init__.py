"""Metric provider registry (hook ``dinext_goals_metric_providers``).

A provider exposes ``label``, ``description``, ``details`` (lines describing the calculation), ``params`` (list of dicts with code, param_type,
required), ``is_available()``, ``get_value(goal, params, date_from, date_to)`` and optionally
``get_target(goal, params)``. ``goal`` is the Goal document, ``params`` its effective parameters.
"""

from __future__ import annotations

import frappe
from frappe import _

HOOK = "dinext_goals_metric_providers"


class ProviderUnavailableError(frappe.ValidationError):
	pass


class MetricProvider:
	key = ""
	label = ""
	description = ""
	details: tuple[str, ...] = ()
	params: tuple[dict, ...] = ()
	supports_target = False

	def is_available(self) -> bool:
		return True

	def get_value(self, goal, params, date_from, date_to) -> float:
		raise NotImplementedError

	def get_target(self, goal, params) -> float:
		raise NotImplementedError

	def describe(self) -> dict:
		return {
			"key": self.key,
			"label": _(self.label),
			"description": _(self.description),
			"details": [_(line) for line in self.details],
			"params": list(self.params),
			"supports_target": self.supports_target,
			"available": self.is_available(),
		}


def get_registry() -> dict[str, str]:
	registry: dict[str, str] = {}
	hooks = frappe.get_hooks(HOOK) or {}
	if isinstance(hooks, dict):
		for key, paths in hooks.items():
			registry[key] = paths[-1] if isinstance(paths, list | tuple) else paths
	return registry


def get_provider(key: str, *, check_available: bool = True) -> MetricProvider:
	path = get_registry().get(key or "")
	if not path:
		frappe.throw(_("Metric provider {0} is not registered").format(frappe.bold(key or "")))
	provider = frappe.get_attr(path)
	if isinstance(provider, type):
		provider = provider()
	if check_available and not provider.is_available():
		raise ProviderUnavailableError(
			_("Metric provider {0} is unavailable on this site").format(_(provider.label))
		)
	return provider


def list_providers() -> list[dict]:
	result = []
	for _key, path in sorted(get_registry().items()):
		provider = frappe.get_attr(path)
		if isinstance(provider, type):
			provider = provider()
		result.append(provider.describe())
	return result


def missing_params(provider: MetricProvider, params: dict) -> list[str]:
	return [
		p["code"] for p in provider.params if p.get("required") and params.get(p["code"]) in (None, "", [])
	]


def as_list(value) -> list[str]:
	if not value:
		return []
	if isinstance(value, list | tuple | set):
		return [str(item) for item in value if item]
	return [str(value)]


def cost_center_with_descendants(cost_center: str) -> list[str]:
	bounds = frappe.db.get_value("Cost Center", cost_center, ["lft", "rgt"], as_dict=True)
	if not bounds:
		frappe.throw(_("Cost Center {0} does not exist").format(cost_center))
	return frappe.get_all(
		"Cost Center", filters={"lft": [">=", bounds.lft], "rgt": ["<=", bounds.rgt]}, pluck="name"
	)
