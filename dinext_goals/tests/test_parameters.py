import datetime

import frappe

from dinext_goals import api, parameters
from dinext_goals.tests.utils import GoalTestCase, activate, make_goal, make_group, param


class TestGoalParameters(GoalTestCase):
	def test_every_type_reaches_formulas_typed(self):
		goal = make_goal(
			"Typed",
			params=[
				param("i", "Int", 7.6),
				param("f", "Float", 2.5),
				param("c", "Currency", 1000),
				param("p", "Percent", 15),
				param("d", "Data", "text"),
				param("s", "Select", "team", options="user\nteam"),
				param("dt", "Date", "2026-03-01"),
				param("flag", "Check", 1),
				param("link", "Link", "KPI", link_doctype="Goal Type"),
				param("many", "Link List", ["KPI", "OKR", "KPI"], link_doctype="Goal Type"),
			],
		)
		values = parameters.get_effective_params(goal.name)
		self.assertEqual(values.i, 7)
		self.assertIsInstance(values.i, int)
		self.assertEqual(values.f, 2.5)
		self.assertEqual(values.c, 1000.0)
		self.assertAlmostEqual(values.p, 0.15)
		self.assertEqual(values.d, "text")
		self.assertEqual(values.s, "team")
		self.assertEqual(values.dt, datetime.date(2026, 3, 1))
		self.assertIs(values.flag, True)
		self.assertEqual(values.link, "KPI")
		self.assertEqual(values.many, ["KPI", "OKR"])
		displays = {row.code: row.value_display for row in goal.parameters}
		self.assertEqual(displays["p"], "15%")
		self.assertEqual(displays["many"], "KPI, OKR")

	def test_invalid_code(self):
		with self.assertRaises(frappe.ValidationError):
			make_goal("Bad", params=[param("Bad-Code", "Float", 1)])

	def test_duplicate_code(self):
		with self.assertRaises(frappe.ValidationError):
			make_goal("Twice", params=[param("x", "Float", 1), param("x", "Float", 2)])

	def test_select_value_must_be_an_option(self):
		with self.assertRaises(frappe.ValidationError):
			make_goal("Select", params=[param("s", "Select", "other", options="user\nteam")])

	def test_link_needs_doctype(self):
		with self.assertRaises(frappe.ValidationError):
			make_goal("Link", params=[param("link", "Link", "KPI")])

	def test_missing_linked_document(self):
		with self.assertRaises(frappe.ValidationError):
			make_goal("Link", params=[param("link", "Link", "No Such Type", link_doctype="Goal Type")])
		with self.assertRaises(frappe.ValidationError):
			make_goal(
				"List", params=[param("many", "Link List", ["KPI", "No Such Type"], link_doctype="Goal Type")]
			)

	def test_nearest_ancestor_wins(self):
		root = make_group("Root", params=[param("rate", "Float", 1)])
		middle = make_group("Middle", parents=[root.name], params=[param("rate", "Float", 2)])
		leaf = make_goal("Leaf", parents=[middle.name])
		resolved = parameters.resolve_for_name(leaf.name)
		self.assertEqual(parameters.coerce(resolved["rate"].row), 2)
		self.assertEqual(resolved["rate"].source, middle.name)
		self.assertTrue(resolved["rate"].inherited)

	def test_child_override(self):
		root = make_group("Root", params=[param("rate", "Float", 1)])
		leaf = make_goal("Leaf", parents=[root.name], params=[param("rate", "Float", 5)])
		resolved = parameters.resolve_for_name(leaf.name)
		self.assertEqual(parameters.coerce(resolved["rate"].row), 5)
		self.assertFalse(resolved["rate"].inherited)

	def test_not_inherited(self):
		root = make_group("Root", params=[param("secret", "Float", 1, inherit=0)])
		leaf = make_goal("Leaf", parents=[root.name])
		self.assertNotIn("secret", parameters.get_effective_params(leaf.name))
		self.assertEqual(parameters.get_effective_params(root.name).secret, 1)

	def test_conflict_between_two_parents(self):
		first = make_group("First", params=[param("rate", "Float", 1)])
		second = make_group("Second", params=[param("rate", "Float", 2)])
		with self.assertRaises(frappe.ValidationError):
			make_goal("Shared", parents=[first.name, second.name])
		shared = make_goal("Shared", parents=[first.name, second.name], params=[param("rate", "Float", 3)])
		self.assertEqual(parameters.get_effective_params(shared.name).rate, 3)

	def test_equal_values_from_two_parents(self):
		first = make_group("First", params=[param("rate", "Float", 1)])
		second = make_group("Second", params=[param("rate", "Float", 1)])
		shared = make_goal("Shared", parents=[first.name, second.name])
		self.assertEqual(parameters.get_effective_params(shared.name).rate, 1)

	def test_override_with_another_type(self):
		root = make_group("Root", params=[param("rate", "Float", 1)])
		with self.assertRaises(frappe.ValidationError):
			make_goal("Leaf", parents=[root.name], params=[param("rate", "Data", "one")])

	def test_locked_parameter_of_an_active_goal(self):
		goal = make_goal("Leaf", params=[param("rate", "Float", 1)])
		activate(goal.name)
		goal = self.reload(goal.name)
		goal.parameters[0].value_number = 2
		with self.assertRaises(frappe.ValidationError):
			goal.save()
		goal = self.reload(goal.name)
		goal.append("parameters", param("extra", "Float", 1))
		with self.assertRaises(frappe.ValidationError):
			goal.save()

	def test_editable_parameter_of_an_active_goal(self):
		goal = make_goal("Leaf", params=[param("on_date", "Date", "2026-03-01", editable=1)])
		activate(goal.name)
		goal = self.reload(goal.name)
		goal.parameters[0].value_date = "2026-04-01"
		goal.save()
		self.assertEqual(parameters.get_effective_params(goal.name).on_date, datetime.date(2026, 4, 1))

	def test_inherited_parameter_locked_by_active_child(self):
		root = make_group("Root", params=[param("rate", "Float", 1)])
		child = make_goal("Child", parents=[root.name])
		root = self.reload(root.name)
		root.parameters[0].value_number = 2
		root.save()
		activate(child.name)
		root = self.reload(root.name)
		root.parameters[0].value_number = 3
		with self.assertRaises(frappe.ValidationError):
			root.save()

	def test_substitute_params(self):
		params = frappe._dict(cc="Main - D", projects=["P1", "P2"], limit=5)
		self.assertEqual(
			parameters.substitute_params({"cost_center": "=param:cc", "project": "=param:projects"}, params),
			{"cost_center": "Main - D", "project": ["in", ["P1", "P2"]]},
		)
		self.assertEqual(
			parameters.substitute_params(
				{"project": ["!=", "=param:projects"], "qty": [">", "=param:limit"]}, params
			),
			{"project": ["not in", ["P1", "P2"]], "qty": [">", 5]},
		)
		self.assertEqual(
			parameters.substitute_params([["Task", "project", "=", "=param:projects"]], params),
			[["Task", "project", "in", ["P1", "P2"]]],
		)
		with self.assertRaises(frappe.ValidationError):
			parameters.substitute_params({"x": "=param:unknown"}, params)

	def test_effective_parameters_api(self):
		root = make_group("Root", params=[param("cost_center", "Data", "Main - D")])
		leaf = make_goal("Leaf", parents=[root.name], params=[param("own", "Int", 1)])
		rows = {row["code"]: row for row in api.get_effective_parameters(leaf.name)}
		self.assertTrue(rows["cost_center"]["inherited"])
		self.assertEqual(rows["cost_center"]["source"], root.name)
		self.assertEqual(rows["cost_center"]["source_title"], "Root")
		self.assertFalse(rows["own"]["inherited"])

	def test_parameter_change_recalculates_descendants(self):
		root = make_group("Root", params=[param("plan", "Float", 10)])
		leaf = make_goal(
			"Leaf",
			parents=[root.name],
			progress_method="Auto",
			metric_source="Python Rule",
			calculation_rule="params.plan * 2",
			target=100,
		)
		self.assertEqual(self.reload(leaf.name).current_value, 20)
		root = self.reload(root.name)
		root.parameters[0].value_number = 30
		root.save()
		self.assertEqual(self.reload(leaf.name).current_value, 60)
