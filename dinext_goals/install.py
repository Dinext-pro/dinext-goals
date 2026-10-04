"""Install / migrate hooks for Dinext Goals."""

import frappe

from dinext_goals.constants import SETTINGS
from dinext_goals.setup.dinext_hub import register_dinext_hub_items

SETTINGS_DEFAULTS = {"yellow_threshold": 10, "red_threshold": 25, "enable_daily_recalculation": 1}


def ensure_settings_defaults() -> None:
	"""Single DocType defaults are not stored until the first save; seed them once."""
	if frappe.db.get_single_value(SETTINGS, "red_threshold"):
		return
	for field, value in SETTINGS_DEFAULTS.items():
		frappe.db.set_single_value(SETTINGS, field, value)


def after_install() -> None:
	ensure_settings_defaults()
	register_dinext_hub_items()


def after_migrate() -> None:
	ensure_settings_defaults()
	register_dinext_hub_items()
