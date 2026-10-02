"""Register this app's default Dinext Hub cards."""

from __future__ import annotations

import frappe

APP_NAME = "dinext_goals"
SECTION = "Goals"

HUB_ITEMS = (
	{
		"section": SECTION,
		"element_type": "Workspace",
		"target": "Цели",
		"label": "Goals",
		"description": "Goal dashboard: counts, my progress and goals at risk.",
		"icon": "target",
	},
	{
		"section": SECTION,
		"element_type": "DocType",
		"target": "Goal",
		"label": "Goal",
		"description": "Goals with hierarchy, metrics, progress and approval.",
		"icon": "milestone",
	},
	{
		"section": SECTION,
		"element_type": "Page",
		"target": "goal-map",
		"label": "Goal Map",
		"description": "Interactive goal tree with plan, actual and RAG status.",
		"icon": "organization",
	},
	{
		"section": SECTION,
		"element_type": "DocType",
		"target": "Goal Template",
		"label": "Goal Template",
		"description": "Reusable goal trees for recurring goal sets.",
		"icon": "file",
	},
)


def register_dinext_hub_items() -> None:
	if "dinext_common" not in frappe.get_installed_apps():
		return
	try:
		from dinext_common.setup.hub_catalog import register_hub_items
	except ImportError:
		return
	register_hub_items(HUB_ITEMS, source_app=APP_NAME)
