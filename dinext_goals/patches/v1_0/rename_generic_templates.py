import frappe

from dinext_goals.constants import GOAL, GOAL_TEMPLATE

RENAMED = {
	"Квартальный бонус менеджера": "Бонус руководителя подразделения",
	"Квартальный бонус специалиста": "Бонус сотрудника",
	"Ежемесячная премия": "Премия за утилизацию",
}


def execute():
	# The fixture sync after the patches reloads the template content under the new names.
	for old, new in RENAMED.items():
		if not frappe.db.exists(GOAL_TEMPLATE, old):
			continue
		if frappe.db.exists(GOAL_TEMPLATE, new):
			frappe.db.set_value(GOAL, {"goal_template": old}, "goal_template", new, update_modified=False)
			frappe.delete_doc(GOAL_TEMPLATE, old, ignore_permissions=True, force=True)
		else:
			frappe.rename_doc(GOAL_TEMPLATE, old, new, force=True, show_alert=False)
			frappe.db.set_value(GOAL_TEMPLATE, new, "template_name", new, update_modified=False)
