from frappe.model.document import Document

from dinext_goals import campaigns


class GoalCampaign(Document):
	def validate(self):
		campaigns.validate_campaign(self)
