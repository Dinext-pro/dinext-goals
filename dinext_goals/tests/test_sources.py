import json

import frappe

from dinext_goals.constants import GOAL
from dinext_goals.progress import engine, formulas, sources
from dinext_goals.tests.utils import GoalTestCase, activate, make_goal, make_group, new_goal, param


def linked(aggregation, field=None, filters=None, **values):
	return {
		"progress_method": "Auto",
		"metric_source": "Linked Documents",
		"linked_document_type": GOAL,
		"aggregation": aggregation,
		"linked_document_field": field,
		"linked_document_filter": json.dumps(filters or {"subject": ["like", "=param:pattern"]}),
		**values,
	}


class TestLinkedDocuments(GoalTestCase):
	def setUp(self):
		super().setUp()
		for target, goal_type in ((10, "KPI"), (20, "OKR"), (30, "OKR")):
			make_goal(f"SRC {target}", target=target, goal_type=goal_type)
		self.pattern = param("pattern", "Data", "SRC %")

	def test_aggregations(self):
		expected = {"Count": 3, "Sum": 60, "Avg": 20, "Max": 30, "Min": 10, "Latest": 30}
		for aggregation, value in expected.items():
			field = None if aggregation == "Count" else "target"
			goal = make_goal(
				f"Agg {aggregation}", params=[self.pattern], target=1000, **linked(aggregation, field)
			)
			self.assertEqual(goal.current_value, value, aggregation)

	def test_linked_documents_with_a_parameter(self):
		goal = make_goal(
			"By types",
			params=[param("types", "Link List", ["OKR"], link_doctype="Goal Type")],
			target=1000,
			**linked("Sum", "target", {"goal_type": "=param:types", "subject": ["like", "SRC %"]}),
		)
		self.assertEqual(goal.current_value, 50)

	def test_parameter_from_the_parent(self):
		root = make_group("Root", params=[self.pattern])
		goal = make_goal("Child", parents=[root.name], target=1000, **linked("Count"))
		self.assertEqual(goal.current_value, 3)

	def test_invalid_configuration(self):
		cases = (
			{"linked_document_type": None},
			{"linked_document_type": "No Such DocType"},
			{"linked_document_field": "subject"},
			{"linked_document_field": "no_such_field"},
			{"linked_document_filter": "{not json"},
			{"linked_document_field": None},
		)
		for override in cases:
			values = linked("Sum", "target") | override
			with self.assertRaises(frappe.ValidationError, msg=str(override)):
				make_goal("Broken", params=[self.pattern], **values)


class TestRulesAndTargets(GoalTestCase):
	def test_python_rule(self):
		goal = make_goal(
			"Rule",
			params=[param("base", "Float", 4)],
			progress_method="Auto",
			metric_source="Python Rule",
			calculation_rule="params.base * 10 + len([1, 2])",
		)
		self.assertEqual(goal.current_value, 42)

	def test_unsafe_rule(self):
		for expression in (
			"__import__('os').system('true')",
			"().__class__.__mro__",
			"frappe.db.sql('select 1')",
			"open('/etc/passwd')",
		):
			with self.assertRaises(formulas.GoalFormulaError, msg=expression):
				formulas.evaluate(expression, {"params": frappe._dict()}, "Calculation Rule")
		goal = make_goal(
			"Unsafe",
			progress_method="Auto",
			metric_source="Python Rule",
			calculation_rule="__import__('os').getcwd()",
			current_value=7,
		)
		self.assertEqual(goal.current_value, 7)

	def test_invalid_syntax_is_rejected_on_save(self):
		for values in (
			{"progress_method": "Auto", "metric_source": "Python Rule", "calculation_rule": "1 +"},
			{"result_formula": "child(("},
			{"target_source": "Formula", "target_formula": "params."},
		):
			with self.assertRaises(frappe.ValidationError, msg=str(values)):
				make_goal("Syntax", **values)

	def test_target_formula_only_in_draft(self):
		goal = make_goal(
			"Formula target",
			params=[param("plan", "Int", 400, editable=1)],
			target_source="Formula",
			target_formula="params.plan * 2",
		)
		self.assertEqual(goal.target, 800)
		activate(goal.name)
		goal = self.reload(goal.name)
		goal.parameters[0].value_number = 500
		goal.save()
		self.assertEqual(self.reload(goal.name).target, 800)

	def test_provider_source_needs_a_provider(self):
		with self.assertRaises(frappe.ValidationError):
			make_goal("No provider", progress_method="Auto", metric_source="Provider")
		goal = new_goal(
			"Unknown provider",
			progress_method="Auto",
			metric_source="Provider",
			metric_provider="no_such_provider",
		)
		goal.insert()
		self.assertEqual(goal.current_value, 0)

	def test_target_provider(self):
		with self.assertRaises(frappe.ValidationError):
			make_goal("No target provider", target_source="Provider")
		with self.assertRaises(frappe.ValidationError):
			make_goal("Gl has no target", target_source="Provider", target_provider="gl_profit")
		doc = new_goal(
			"Budget target",
			target_source="Provider",
			metric_provider="gl_profit",
			target_provider="project_budget_profit",
		)
		self.assertEqual(sources.target_provider_key(doc), "project_budget_profit")
		doc.target_provider = None
		doc.metric_provider = "project_budget_profit"
		self.assertEqual(sources.target_provider_key(doc), "project_budget_profit")

	def test_missing_provider_parameters_are_reported(self):
		goal = make_goal(
			"Budget",
			progress_method="Auto",
			metric_source="Provider",
			metric_provider="project_budget_profit",
		)
		calculator = engine.Calculator()
		calculator.compute(goal.name)
		self.assertIn("projects", calculator.errors[goal.name])
