import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class GoalsSettings(Document):
	def validate(self):
		if flt(self.yellow_threshold) < 0 or flt(self.red_threshold) < 0:
			frappe.throw(_("RAG thresholds cannot be negative"))
		if flt(self.yellow_threshold) >= flt(self.red_threshold):
			frappe.throw(_("Yellow threshold must be lower than the red threshold"))
