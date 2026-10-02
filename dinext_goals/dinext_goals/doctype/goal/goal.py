from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from dinext_goals import parameters
from dinext_goals.constants import GOAL_LOG, LOG_SOURCE_AUTO, LOG_SOURCE_MANUAL
from dinext_goals.goals import approvers, hierarchy, lifecycle
from dinext_goals.progress import engine, sources


class Goal(Document):
	def validate(self):
		before = self.get_doc_before_save()
		lifecycle.validate_owner_role(self)
		self.validate_dates()
		self.validate_metric()
		hierarchy.validate_parents(self)
		hierarchy.validate_goal_code(self)
		parameters.validate_parameters(self)
		parameters.resolve_for_doc(self)
		lifecycle.sync_status(self, before)
		lifecycle.validate_draft_lock(self, before)
		parameters.validate_locks(self, before)
		sources.validate_source_config(self)
		self.flags.manual_input_changed = self.manual_input_changed(before)
		errors = engine.compute_in_memory(self)
		if errors:
			frappe.msgprint(
				"<br>".join(errors.values()), title=_("Progress was not recalculated"), indicator="orange"
			)
		approvers.set_approver_users(self)
		approvers.validate_submission(self, before)

	def validate_dates(self):
		if (
			self.exp_start_date
			and self.exp_end_date
			and getdate(self.exp_end_date) < getdate(self.exp_start_date)
		):
			frappe.throw(_("Expected End Date cannot be before Expected Start Date"))

	def validate_metric(self):
		if flt(self.weight) < 0:
			frappe.throw(_("Weight cannot be negative"))
		if not self.is_group and not self.metric_type:
			frappe.throw(_("Metric Type is required for a non-group goal"))

	def manual_input_changed(self, before) -> bool:
		if self.progress_method != "Manual":
			return False
		field = "progress" if self.is_group else "current_value"
		if not before:
			return bool(flt(self.get(field)))
		return engine.differs(field, before.get(field), self.get(field))

	def on_update(self):
		before = self.get_doc_before_save()
		if before is None or any(
			engine.differs(field, before.get(field), self.get(field)) for field in engine.LOGGED_FIELDS
		):
			source = LOG_SOURCE_MANUAL if self.flags.manual_input_changed else LOG_SOURCE_AUTO
			engine.write_log(self.name, self, source)
		if self.flags.skip_related_recalculation:
			return
		include_descendants = before is not None and parameters.signature_of(
			before
		) != parameters.signature_of(self)
		engine.recalculate_related(self, include_descendants=include_descendants)
		if before is not None:
			removed = set(hierarchy.doc_parent_names(before)) - set(hierarchy.doc_parent_names(self))
			for parent in sorted(removed):
				engine.recalculate(parent)

	def on_trash(self):
		self.flags.former_parents = hierarchy.doc_parent_names(self)
		for log in frappe.get_all(GOAL_LOG, filters={"goal": self.name}, pluck="name"):
			frappe.delete_doc(GOAL_LOG, log, ignore_permissions=True, force=True)

	def after_delete(self):
		for parent in self.flags.former_parents or []:
			if frappe.db.exists("Goal", parent):
				engine.recalculate(parent)
