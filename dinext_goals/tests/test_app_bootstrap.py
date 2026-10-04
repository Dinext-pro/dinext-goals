import frappe
from frappe.tests.utils import FrappeTestCase

from dinext_goals.constants import GOAL_ROLES, SETTINGS, WORKFLOW_NAME
from dinext_goals.setup.dinext_hub import HUB_ITEMS, REMOVED_TARGETS, register_dinext_hub_items
from dinext_goals.tests.utils import T_MANAGER, T_MONTHLY, T_PROJECT, T_SPECIALIST, shipped_formula

NUMBER_CARDS = (
	"All Goals",
	"My Goals",
	"Goals for Approval",
	"Active Goals",
	"Goals at Risk",
	"Overdue Goals",
	"My Average Progress",
	"My Maximum Progress",
	"My Minimum Progress",
)
CHARTS = ("Goals at Risk by Type", "Goals at Risk by Owner", "Goals by Status", "Average Progress by Type")


class TestAppBootstrap(FrappeTestCase):
	def test_roles_after_installation(self):
		for role in GOAL_ROLES:
			self.assertTrue(frappe.db.exists("Role", role), role)

	def test_goal_types(self):
		for goal_type in ("OKR", "KPI", "Project Goal", "Personal", "Strategic"):
			self.assertTrue(frappe.db.exists("Goal Type", goal_type), goal_type)

	def test_approval_workflow(self):
		workflow = frappe.get_doc("Workflow", WORKFLOW_NAME)
		self.assertTrue(workflow.is_active)
		self.assertEqual(workflow.document_type, "Goal")
		self.assertEqual(
			{s.state for s in workflow.states}, {"Draft", "Parent Approval", "Finance Approval", "Approved"}
		)
		if not frappe.get_meta("Workflow Transition").has_field("custom_parallel_approval_policy"):
			return
		policies = {(t.state, t.action): t.custom_parallel_approval_policy for t in workflow.transitions}
		self.assertEqual(policies[("Parent Approval", "Approve")], "All")
		self.assertEqual(policies[("Finance Approval", "Approve")], "Any")
		for transition in workflow.transitions:
			if transition.action == "Reject":
				self.assertTrue(transition.custom_comment_is_required)

	def test_hooks(self):
		self.assertIn("dinext_goals.tasks.daily", frappe.get_hooks("scheduler_events")["daily"])
		self.assertIn(
			"dinext_goals.goals.permissions.goal_has_permission", frappe.get_hooks("has_permission")["Goal"]
		)
		self.assertIn(
			"dinext_goals.goals.permissions.goal_query_conditions",
			frappe.get_hooks("permission_query_conditions")["Goal"],
		)
		self.assertIn(
			"dinext_goals.goals.permissions.goal_log_query_conditions",
			frappe.get_hooks("permission_query_conditions")["Goal Log"],
		)
		excluded = {}
		for entry in frappe.get_hooks("workflow_approval_fingerprint_excluded_fields"):
			for doctype, fields in entry.items():
				excluded.setdefault(doctype, set()).update(fields)
		for field in ("progress", "current_value", "result_value", "approver_users", "status"):
			self.assertIn(field, excluded["Goal"])

	def test_goal_template_fixtures(self):
		expected = {
			T_MANAGER: ({"MGR", "PROFIT", "KPERS"}, {"cost_center", "profit_share", "gate_goal_code"}),
			T_SPECIALIST: (
				{"SPEC", "UTIL", "POINTS", "KPERS"},
				{"grade", "bonus_base", "k_prem", "points_plan"},
			),
			T_MONTHLY: ({"MONTH"}, {"k_prem"}),
			T_PROJECT: ({"PROJECT"}, {"projects", "project_bonus_share"}),
		}
		fixture_filter = next(
			f
			for f in frappe.get_hooks("fixtures", app_name="dinext_goals")
			if isinstance(f, dict) and f["doctype"] == "Goal Template"
		)
		self.assertEqual(set(fixture_filter["filters"][0][2]), set(expected))
		for name, (items, asked) in expected.items():
			template = frappe.get_doc("Goal Template", name)
			self.assertEqual({row.item_key for row in template.items}, items, name)
			self.assertEqual(
				{row.code for row in template.template_parameters if row.ask_on_create}, asked, name
			)
			root = next(row for row in template.items if not row.parent_key)
			self.assertEqual(root.result_formula, shipped_formula(name), name)

	def test_goal_template_fixtures_are_generic(self):
		path = frappe.get_app_path("dinext_goals", "fixtures", "goal_template.json")
		with open(path, encoding="utf-8") as fixture:
			text = fixture.read()
		for word in ("ИТК", "ITK", "KPI_v6", "Квартальный", "Ежемесячная"):
			self.assertNotIn(word, text)

	def test_settings_defaults(self):
		self.assertEqual(frappe.db.get_single_value(SETTINGS, "red_threshold"), 25)
		self.assertEqual(frappe.db.get_single_value(SETTINGS, "yellow_threshold"), 10)

	def test_workspace_and_widgets(self):
		workspace = frappe.get_doc("Workspace", "Цели")
		self.assertEqual({row.number_card_name for row in workspace.number_cards}, set(NUMBER_CARDS))
		self.assertEqual({row.chart_name for row in workspace.charts}, set(CHARTS))
		self.assertTrue(
			{"Goal", "Goal Template", "Goal Campaign", "goal-map"}
			<= {row.link_to for row in workspace.shortcuts}
		)
		self.assertTrue(frappe.db.exists("Page", "goal-map"))
		my_goals = frappe.get_doc("Number Card", "My Goals")
		self.assertIn("frappe.session.user", my_goals.dynamic_filters_json)

	def test_hub_items(self):
		if not frappe.db.exists("Dinext Workspace Settings", "Dinext"):
			self.skipTest("dinext_common hub settings are not installed")
		register_dinext_hub_items()
		settings = frappe.get_doc("Dinext Workspace Settings", "Dinext")
		workspace = [
			row for row in settings.items if row.element_type == "Workspace" and row.target == "Цели"
		]
		self.assertTrue(workspace)
		self.assertTrue(all(row.section == "My Work" for row in workspace))
		self.assertEqual(
			{(item["element_type"], item["target"]) for item in HUB_ITEMS}, {("Workspace", "Цели")}
		)
		ours = {
			(row.element_type, row.target)
			for row in settings.items
			if not row.source_app or row.source_app == "dinext_goals"
		}
		for key in REMOVED_TARGETS:
			self.assertNotIn(key, ours)
