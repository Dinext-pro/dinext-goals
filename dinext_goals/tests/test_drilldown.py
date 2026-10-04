import json
from unittest.mock import patch

import frappe

from dinext_goals import api, templates
from dinext_goals.constants import GOAL, GOAL_TEMPLATE
from dinext_goals.tests.utils import OWNER, START, GoalTestCase, make_goal, make_group

TEMPLATE = "_GT Drilldown"


class TestMetricDrilldown(GoalTestCase):
	def setUp(self):
		super().setUp()
		frappe.local.lang = "en"

	def test_linked_documents_open_the_filtered_list(self):
		goal = make_goal(
			"Tasks",
			progress_method="Auto",
			metric_source="Linked Documents",
			linked_document_type=GOAL,
			aggregation="Count",
			linked_document_filter=json.dumps({"subject": ["like", "SRC%"]}),
		)
		result = api.get_metric_drilldown(goal.name, "actual")
		self.assertEqual(result["kind"], "list")
		self.assertEqual(result["doctype"], GOAL)
		self.assertEqual(result["filters"]["subject"], ["like", "SRC%"])

	def test_manual_values_explain_themselves(self):
		goal = make_goal("Typed")
		actual = api.get_metric_drilldown(goal.name, "actual")
		target = api.get_metric_drilldown(goal.name, "target")
		self.assertEqual(actual["kind"], "message")
		self.assertIn("actual", actual["text"].lower())
		self.assertEqual(target["kind"], "message")
		self.assertIn("target", target["text"].lower())
		self.assertEqual(api.get_metric_drilldown(goal.name, "achievement")["kind"], "message")

	def test_fact_without_a_start_date_is_not_a_list(self):
		goal = make_goal(
			"No start",
			progress_method="Auto",
			metric_source="Linked Documents",
			linked_document_type=GOAL,
			aggregation="Count",
		)
		frappe.db.set_value(GOAL, goal.name, "exp_start_date", None)
		result = api.get_metric_drilldown(goal.name, "actual")
		self.assertEqual(result["kind"], "message")
		self.assertIn("start", result["text"].lower())

	def test_python_rule_without_an_expression_shows_the_rule(self):
		parent = make_group("Tree")
		sales = make_goal("Sales", parents=[parent.name], goal_code="SALES")
		goal = make_goal(
			"Rule",
			parents=[parent.name],
			goal_code="RULE",
			progress_method="Auto",
			metric_source="Python Rule",
			calculation_rule='tree_goal("SALES").current_value',
		)
		result = api.get_metric_drilldown(goal.name, "actual")
		self.assertEqual(result["kind"], "dialog")
		self.assertEqual(result["expression"], goal.calculation_rule)
		self.assertEqual(result["links"], [{"doctype": GOAL, "name": sales.name, "label": sales.subject}])

	def test_drilldown_expression_opens_the_described_list(self):
		goal = make_goal(
			"Described",
			progress_method="Auto",
			metric_source="Python Rule",
			calculation_rule="1",
			calculation_drilldown_rule='documents("Goal", {"status": "Active"})',
			target_source="Formula",
			target_formula="2",
			target_drilldown_formula='documents("Goal", names=["GOAL-MISSING"])',
		)
		actual = api.get_metric_drilldown(goal.name, "actual")
		self.assertEqual(actual["doctype"], GOAL)
		self.assertEqual(actual["filters"], {"status": "Active"})
		target = api.get_metric_drilldown(goal.name, "target")
		self.assertEqual(target["filters"], {"name": ["in", ["GOAL-MISSING"]]})

	def test_bad_drilldown_result_is_a_message(self):
		goal = make_goal(
			"Bad result",
			progress_method="Auto",
			metric_source="Python Rule",
			calculation_rule="1",
			calculation_drilldown_rule="1",
			target_source="Formula",
			target_formula="2",
			target_drilldown_formula='documents("Goal", names=[])',
		)
		self.assertEqual(api.get_metric_drilldown(goal.name, "actual")["kind"], "message")
		self.assertEqual(api.get_metric_drilldown(goal.name, "target")["kind"], "message")
		self.assertIn("no source", api.get_metric_drilldown(goal.name, "target")["text"].lower())

	def test_syntax_error_is_rejected_on_save(self):
		with self.assertRaises(frappe.ValidationError):
			make_goal(
				"Broken",
				progress_method="Auto",
				metric_source="Python Rule",
				calculation_rule="1",
				calculation_drilldown_rule="1 +",
			)
		with self.assertRaises(frappe.ValidationError):
			make_goal(
				"Broken target",
				target_source="Formula",
				target_formula="1",
				target_drilldown_formula="documents(",
			)

	def test_group_opens_its_children(self):
		root = make_group("Root")
		child = make_goal("Child", parents=[root.name])
		opened = api.get_metric_drilldown(root.name, "progress")
		self.assertEqual(opened["doctype"], GOAL)
		self.assertIn(child.name, opened["filters"]["name"][1])
		self.assertEqual(api.get_metric_drilldown(root.name, "planned")["filters"], opened["filters"])
		empty = make_group("Empty")
		self.assertIn("child", api.get_metric_drilldown(empty.name, "planned")["text"].lower())

	def test_boolean_planned_progress_is_the_calendar(self):
		goal = make_goal("Flag", metric_type="Boolean", progress_method="Manual", exp_start_date=START)
		self.assertEqual(api.get_metric_drilldown(goal.name, "progress")["kind"], "message")
		text = api.get_metric_drilldown(goal.name, "planned")["text"].lower()
		self.assertIn("planned progress", text)

	def test_map_card_follows_the_fact_list(self):
		parent = make_group("Map")
		listed = make_goal(
			"Listed",
			parents=[parent.name],
			progress_method="Auto",
			metric_source="Python Rule",
			calculation_rule="1",
			calculation_drilldown_rule='documents("Goal", {"status": "Draft"})',
		)
		bare = make_goal(
			"Bare",
			parents=[parent.name],
			progress_method="Auto",
			metric_source="Python Rule",
			calculation_rule="1",
		)
		manual = make_goal("Typed", parents=[parent.name])
		tree = api.get_goal_map(root=parent.name, show_linked=1, status="")["trees"][0]
		self.assertIsNone(tree["linked"])
		by_name = {child["name"]: child for child in tree["children"]}
		opened = api.get_metric_drilldown(listed.name, "actual")
		card = by_name[listed.name]["linked"]
		self.assertEqual(card["doctype"], opened["doctype"])
		self.assertEqual(card["route_options"], opened["filters"])
		self.assertEqual(
			card["count"],
			len(frappe.get_all(GOAL, filters=opened["filters"], pluck="name", limit_page_length=0)),
		)
		self.assertNotIn("note", card)
		self.assertNotIn("calculation_drilldown_rule", by_name[listed.name])
		self.assertIsNone(by_name[bare.name]["linked"])
		self.assertIsNone(by_name[manual.name]["linked"])

	def test_map_card_stays_closed_without_read_permission(self):
		goal = make_goal(
			"Closed card",
			progress_method="Auto",
			metric_source="Linked Documents",
			linked_document_type=GOAL,
			aggregation="Count",
		)
		with patch("dinext_goals.progress.drilldown.frappe.has_permission", return_value=False):
			card = api.get_goal_map(root=goal.name, show_linked=1, status="")["trees"][0]["linked"]
		self.assertEqual(card["restricted"], 1)
		self.assertEqual(card["doctype"], GOAL)
		self.assertNotIn("route_options", card)

	def test_missing_read_permission_does_not_open_the_list(self):
		goal = make_goal(
			"Hidden source",
			progress_method="Auto",
			metric_source="Linked Documents",
			linked_document_type=GOAL,
			aggregation="Count",
		)
		with patch("dinext_goals.progress.drilldown.frappe.has_permission", return_value=False):
			result = api.get_metric_drilldown(goal.name, "actual")
		self.assertEqual(result["kind"], "message")
		self.assertNotIn("filters", result)

	def test_template_copies_drilldown_expressions(self):
		rule = 'documents("Goal", names=["X"])'
		formula = 'documents("Task", {"status": "Open"})'
		frappe.get_doc(
			{
				"doctype": GOAL_TEMPLATE,
				"template_name": TEMPLATE,
				"goal_type": "KPI",
				"items": [
					{
						"item_key": "A",
						"subject": "Leaf",
						"metric_type": "Numeric",
						"progress_method": "Auto",
						"metric_source": "Python Rule",
						"calculation_rule": "1",
						"calculation_drilldown_rule": rule,
						"target_source": "Formula",
						"target_formula": "2",
						"target_drilldown_formula": formula,
					}
				],
			}
		).insert(ignore_permissions=True)
		names = templates.create_goals(TEMPLATE, start_date="2026-07-01", goal_owner=OWNER)
		goal = frappe.get_doc(GOAL, names[0])
		self.assertEqual(goal.calculation_drilldown_rule, rule)
		self.assertEqual(goal.target_drilldown_formula, formula)
