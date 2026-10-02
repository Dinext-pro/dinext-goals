import frappe
from frappe.utils import cint

from dinext_goals.constants import SETTINGS
from dinext_goals.progress import engine


def daily():
	enabled = frappe.db.get_single_value(SETTINGS, "enable_daily_recalculation")
	if enabled is not None and not cint(enabled):
		return None
	summary = engine.recalculate_active()
	frappe.logger("dinext_goals").info(
		f"Daily goal recalculation: {summary['recalculated']} goals, {summary['changed']} changed, {len(summary['errors'])} errors"
	)
	return summary
