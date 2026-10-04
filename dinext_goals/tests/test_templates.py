import frappe

from dinext_goals import api, parameters, templates
from dinext_goals.constants import GOAL, GOAL_TEMPLATE
from dinext_goals.goals import hierarchy
from dinext_goals.tests.utils import (
	DIRECTOR,
	MANAGER,
	OUTSIDER,
	OWNER,
	OWNER_B,
	GoalTestCase,
	as_user,
	make_group,
	param,
)

TEMPLATE = "_GT Quarter Bonus"


def template_doc(name=TEMPLATE, items=None, template_parameters=None, **values):
	return frappe.get_doc(
		{
			"doctype": GOAL_TEMPLATE,
			"template_name": name,
			"goal_type": "KPI",
			"default_duration_days": 92,
			"items": items
			if items is not None
			else [
				{
					"item_key": "ROOT",
					"subject": "Bonus",
					"goal_code": "ROOT",
					"is_group": 1,
					"result_formula": 'child("A").value',
				},
				{
					"item_key": "A",
					"parent_key": "ROOT",
					"subject": "Sales",
					"goal_code": "A",
					"metric_type": "Numeric",
					"target": 100,
					"progress_method": "Manual",
					"owner_source": "Parent Goal Owner",
					"scale_spec": "0:0\n50:1",
					"weight": 2,
				},
				{
					"item_key": "B",
					"parent_key": "ROOT",
					"subject": "Review",
					"goal_code": "B",
					"metric_type": "Boolean",
					"progress_method": "Manual",
					"owner_source": "User",
					"fixed_owner": OWNER_B,
					"start_offset_days": 30,
					"duration_days": 10,
				},
			],
			"template_parameters": template_parameters
			if template_parameters is not None
			else [
				param("types", "Link List", link_doctype="Goal Type") | {"ask_on_create": 1},
				param("rate", "Float") | {"ask_on_create": 1},
				param("level", "Int", 3) | {"item_key": "A"},
			],
			**values,
		}
	)


class TestGoalTemplates(GoalTestCase):
	def test_validation(self):
		bad_items = (
			[
				{"item_key": "X", "subject": "X", "is_group": 1},
				{"item_key": "X", "subject": "Again", "is_group": 1},
			],
			[{"item_key": "X", "subject": "X", "parent_key": "MISSING", "metric_type": "Numeric"}],
			[
				{"item_key": "X", "subject": "X", "parent_key": "Y", "is_group": 1},
				{"item_key": "Y", "subject": "Y", "parent_key": "X", "is_group": 1},
			],
			[
				{"item_key": "X", "subject": "X", "metric_type": "Numeric"},
				{"item_key": "Y", "subject": "Y", "parent_key": "X", "metric_type": "Numeric"},
			],
			[{"item_key": "X", "subject": "X"}],
			[{"item_key": "X", "subject": "X", "metric_type": "Numeric", "scale_spec": "fifty"}],
			[{"item_key": "X", "subject": "X", "metric_type": "Numeric", "result_formula": "1 +"}],
		)
		for items in bad_items:
			with self.assertRaises(frappe.ValidationError, msg=str(items)):
				template_doc(items=items, template_parameters=[]).insert()
		with self.assertRaises(frappe.ValidationError):
			template_doc(template_parameters=[param("x", "Float", 1) | {"item_key": "NOPE"}]).insert()

	def test_ask_on_create_fields(self):
		template_doc().insert()
		fields = {row["code"]: row for row in api.get_template_dialog_fields(TEMPLATE)}
		self.assertEqual(set(fields), {"types", "rate"})
		self.assertEqual(fields["types"]["param_type"], "Link List")
		self.assertEqual(fields["types"]["link_doctype"], "Goal Type")

	def test_create_goals_from_a_template(self):
		template_doc().insert()
		parent = make_group("Department", owner=DIRECTOR, params=[param("rate", "Float", 7)])
		names = api.create_goals_from_template(
			TEMPLATE,
			start_date="2026-07-01",
			goal_owner=OWNER,
			code_prefix="T1",
			parent_goal=parent.name,
			values={"types": ["KPI", "OKR"], "rate": None},
		)
		goals = {frappe.db.get_value(GOAL, name, "goal_code"): frappe.get_doc(GOAL, name) for name in names}
		self.assertEqual(set(goals), {"T1-ROOT", "T1-A", "T1-B"})
		root, a, b = goals["T1-ROOT"], goals["T1-A"], goals["T1-B"]
		self.assertEqual(hierarchy.get_parent_names(root.name), [parent.name])
		self.assertEqual(hierarchy.get_parent_names(a.name), [root.name])
		self.assertEqual(
			(root.goal_owner, a.goal_owner, b.goal_owner),
			(OWNER, DIRECTOR, OWNER_B),
			"A takes the owner of the selected parent goal",
		)
		self.assertEqual((str(root.exp_start_date), str(root.exp_end_date)), ("2026-07-01", "2026-09-30"))
		self.assertEqual((str(b.exp_start_date), str(b.exp_end_date)), ("2026-07-31", "2026-08-09"))
		self.assertEqual(root.goal_template, TEMPLATE)
		self.assertEqual(a.weight, 2)
		self.assertEqual([(s.threshold_percent, s.coefficient) for s in a.scale], [(0, 0), (50, 1)])
		self.assertEqual(
			{row.code for row in root.parameters}, {"types"}, "an unanswered question is skipped"
		)
		self.assertEqual({row.code for row in a.parameters}, {"level"})
		params = parameters.get_effective_params(a.name)
		self.assertEqual(params.types, ["KPI", "OKR"])
		self.assertEqual(params.rate, 7, "the value inherited from the parent goal applies")
		self.assertEqual(params.level, 3)

	def test_inactive_template(self):
		template_doc(is_active=0).insert()
		with self.assertRaises(frappe.ValidationError):
			templates.create_goals(TEMPLATE, start_date="2026-07-01", goal_owner=OWNER)

	def test_permissions(self):
		template_doc().insert()
		parent = make_group("Department", owner=DIRECTOR)
		with as_user(OUTSIDER):
			with self.assertRaises(frappe.PermissionError):
				templates.create_goals(
					TEMPLATE, start_date="2026-07-01", goal_owner=OUTSIDER, parent_goal=parent.name
				)
			names = templates.create_goals(
				TEMPLATE, start_date="2026-07-01", goal_owner=OUTSIDER, code_prefix="OWN"
			)
			self.assertEqual(len(names), 3)
			with self.assertRaises(frappe.PermissionError):
				templates.save_as_template(names[0], "_GT Copy")

	def test_save_a_subtree_as_a_template(self):
		template_doc().insert()
		names = templates.create_goals(
			TEMPLATE, start_date="2026-07-01", goal_owner=OWNER, code_prefix="T9", values={"types": ["KPI"]}
		)
		root = next(name for name in names if frappe.db.get_value(GOAL, name, "is_group"))
		with as_user(MANAGER):
			copy = api.save_as_template(root, "_GT Copy")
		doc = frappe.get_doc(GOAL_TEMPLATE, copy)
		items = {item.goal_code: item for item in doc.items}
		self.assertEqual(set(items), {"ROOT", "A", "B"})
		self.assertEqual(items["A"].parent_key, items["ROOT"].item_key)
		self.assertEqual(items["A"].scale_spec, "0:0\n50:1")
		self.assertEqual((items["B"].owner_source, items["B"].fixed_owner), ("User", OWNER_B))
		self.assertEqual((items["B"].start_offset_days, items["B"].duration_days), (30, 10))
		self.assertEqual(doc.default_duration_days, 92)
		self.assertEqual(
			{(row.item_key, row.code) for row in doc.template_parameters},
			{(items["ROOT"].item_key, "types"), (items["A"].item_key, "level")},
		)
		with as_user(MANAGER):
			with self.assertRaises(frappe.ValidationError):
				api.save_as_template(root, "_GT Copy")
