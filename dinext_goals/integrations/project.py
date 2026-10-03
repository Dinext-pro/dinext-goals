"""Goals in the Project form: Connections group backed by the ``Goal Project`` relation."""

from frappe import _

from dinext_goals.constants import GOAL


def get_dashboard_data(data):
	# Goal has no ``project`` column: Frappe resolves the filter to the ``Goal Project`` child table.
	data.setdefault("non_standard_fieldnames", {})[GOAL] = "project"
	data.setdefault("transactions", []).append({"label": _("Goals"), "items": [GOAL]})
	return data
