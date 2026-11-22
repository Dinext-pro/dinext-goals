"""Workflow defaults for the documents owned by this application."""


def email_profiles():
	return {
		"Goal": {"workflow": "Goal Approval", "approval_states": ('Parent Approval', 'Finance Approval'), "before_configure": _configure_rejection, "after_save": _rebuild_open_rounds},
	}


def _configure_rejection(workflow):
	if not any(row.state == "Rejected" for row in workflow.states):
		workflow.append("states", {"state": "Rejected", "doc_status": "0", "is_optional_state": 1,
			"update_field": "status", "update_value": "Rejected", "allow_edit": "All"})
	for transition in workflow.transitions:
		if transition.action == "Reject":
			transition.next_state = "Rejected"
	if not any(row.state == "Rejected" and row.next_state == "Draft" for row in workflow.transitions):
		workflow.append("transitions", {"state": "Rejected", "action": "Edit", "next_state": "Draft",
			"allowed": "All", "allow_self_approval": 1, "send_email_to_creator": 1,
			"condition": "doc.owner == frappe.session.user", "custom_parallel_approval_policy": "Any"})


def _rebuild_open_rounds(workflow):
	import frappe
	from dinext_common.workflow_approval import engine
	rows = frappe.get_all("Workflow Task", filters={"workflow": workflow.name, "round_status": "Open"},
		fields=["reference_name", "approval_round_id"], distinct=True)
	for row in rows:
		source = frappe.get_doc(workflow.document_type, row.reference_name)
		engine.reconcile_source(source)
		if frappe.db.get_value("Workflow Task", {"approval_round_id": row.approval_round_id}, "round_status") == "Conflicted":
			engine.rebuild_configuration_conflict(source, row.approval_round_id, frappe._("Workflow email settings migration"))
