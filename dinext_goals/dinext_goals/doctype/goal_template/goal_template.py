from frappe.model.document import Document

from dinext_goals import templates


class GoalTemplate(Document):
	def validate(self):
		templates.validate_template(self)
