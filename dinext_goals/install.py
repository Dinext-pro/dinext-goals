"""Install / migrate hooks for Dinext Goals."""

import frappe

from dinext_goals.constants import GOAL_ROLES, SETTINGS
from dinext_goals.setup.dinext_hub import register_dinext_hub_items

SETTINGS_DEFAULTS = {"yellow_threshold": 10, "red_threshold": 25, "enable_daily_recalculation": 1}
WIDGET_DOCTYPE = "Number Card"


def ensure_settings_defaults() -> None:
	"""Single DocType defaults are not stored until the first save; seed them once."""
	if frappe.db.get_single_value(SETTINGS, "red_threshold"):
		return
	for field, value in SETTINGS_DEFAULTS.items():
		frappe.db.set_single_value(SETTINGS, field, value)


def ensure_number_card_read() -> None:
	"""Let goal roles load the workspace number cards.

	Standard Number Card permissions give Desk User read. Once any Custom DocPerm exists
	for Number Card (other Dinext apps ship some as fixtures), Frappe ignores the standard
	rows, so goal roles need their own read rows. Without custom rows nothing is added:
	a single custom row would replace the standard ones for every other role.
	Which cards a user sees is still limited by the Number Card permission query.
	"""
	existing = frappe.get_all(
		"Custom DocPerm", filters={"parent": WIDGET_DOCTYPE, "permlevel": 0}, fields=["role", "read"]
	)
	if not existing:
		return
	readers = {row.role for row in existing if row.read}
	added = False
	for role in GOAL_ROLES:
		if role in readers or not frappe.db.exists("Role", role):
			continue
		frappe.get_doc(
			{"doctype": "Custom DocPerm", "parent": WIDGET_DOCTYPE, "role": role, "permlevel": 0, "read": 1}
		).insert(ignore_permissions=True)
		added = True
	if added:
		frappe.clear_cache(doctype=WIDGET_DOCTYPE)


def after_install() -> None:
	ensure_settings_defaults()
	ensure_number_card_read()
	register_dinext_hub_items()


def after_migrate() -> None:
	ensure_settings_defaults()
	ensure_number_card_read()
	register_dinext_hub_items()
