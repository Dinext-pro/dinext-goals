"""Register this app's default Dinext Hub cards."""

from __future__ import annotations

import frappe

APP_NAME = "dinext_goals"
SECTION = "My Work"
WORKSPACE_TARGET = "Goals"
# The first release stored the workspace under a Russian name. Migrate drops that document and hub row.
PREVIOUS_WORKSPACE = "Цели"
# register_hub_items keeps an existing row's section and never drops cards, so these are removed here.
REMOVED_TARGETS = (
	("DocType", "Goal"),
	("Page", "goal-map"),
	("DocType", "Goal Template"),
	("Workspace", PREVIOUS_WORKSPACE),
)

HUB_ITEMS = (
	{
		"section": SECTION,
		"element_type": "Workspace",
		"target": WORKSPACE_TARGET,
		"label": "Goals",
		"description": "Goal dashboard: counts, my progress and goals at risk.",
		"icon": "target",
	},
)


def register_dinext_hub_items() -> None:
	if "dinext_common" not in frappe.get_installed_apps():
		return
	try:
		from dinext_common.setup.hub_catalog import register_hub_items, relocate_hub_item_section
	except ImportError:
		return
	register_hub_items(HUB_ITEMS, source_app=APP_NAME)
	relocate_hub_item_section(element_type="Workspace", target=WORKSPACE_TARGET, section=SECTION)
	if not frappe.db.exists("Dinext Workspace Settings", "Dinext"):
		return
	settings = frappe.get_doc("Dinext Workspace Settings", "Dinext")
	removed = [
		row
		for row in settings.items
		if (row.element_type, row.target) in REMOVED_TARGETS
		and (not row.source_app or row.source_app == APP_NAME)
	]
	if not removed:
		return
	for row in removed:
		settings.remove(row)
	settings.save(ignore_permissions=True)
	frappe.clear_cache(doctype="Dinext Workspace Settings")
