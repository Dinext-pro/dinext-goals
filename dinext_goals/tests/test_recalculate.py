import json

import frappe

from dinext_goals import api, tasks
from dinext_goals.constants import GOAL, GOAL_LOG, SETTINGS
from dinext_goals.tests.utils import (
	OUTSIDER,
	OWNER,
	GoalTestCase,
	activate,
	as_user,
	make_goal,
	make_group,
	make_project,
	param,
)


class TestRecalculateApi(GoalTestCase):
	def test_recalculate_from_the_form(self):
		group = make_group("Group")
		leaf = make_goal("Leaf", parents=[group.name], current_value=10)
		frappe.db.set_value(GOAL, leaf.name, "current_value", 60)
		with as_user(OWNER):
			summary = api.recalculate(leaf.name)
		self.assertEqual(summary["errors"], [])
		self.assertGreaterEqual(summary["changed"], 2)
		self.assertEqual(frappe.db.get_value(GOAL, group.name, "progress"), 60)
		self.assertEqual(
			frappe.get_all(
				GOAL_LOG, filters={"goal": leaf.name}, pluck="source", order_by="creation desc", limit=1
			),
			["Manual"],
		)

	def test_daily_job(self):
		self.assertIn("dinext_goals.tasks.daily", frappe.get_hooks("scheduler_events")["daily"])
		active = make_goal("Active", current_value=10)
		draft = make_goal("Draft", current_value=10)
		activate(active.name)
		for name in (active.name, draft.name):
			frappe.db.set_value(GOAL, name, "current_value", 70)
		summary = tasks.daily()
		self.assertGreaterEqual(summary["recalculated"], 1)
		self.assertEqual(frappe.db.get_value(GOAL, active.name, "progress"), 70)
		self.assertEqual(
			frappe.db.get_value(GOAL, draft.name, "progress"), 10, "only Active and On Hold goals"
		)
		frappe.db.set_single_value(SETTINGS, "enable_daily_recalculation", 0)
		self.assertIsNone(tasks.daily())

	def test_goal_with_history(self):
		goal = make_goal("History", current_value=10)
		for value in (20, 30):
			goal.reload()
			goal.current_value = value
			goal.save()
		trend = api.get_goal_trend(goal.name)
		self.assertEqual([log.current_value for log in trend["logs"]], [10, 20, 30])
		self.assertEqual((trend["baseline"], trend["target"]), (0, 100))
		self.assertEqual(str(trend["start"]), "2026-01-01")

	def test_children(self):
		group = make_group("Group")
		make_goal("B child", parents=[group.name], current_value=5)
		make_goal("A child", parents=[group.name], current_value=7)
		rows = api.get_children(group.name)
		self.assertEqual([row.subject for row in rows], ["A child", "B child"])
		self.assertEqual(rows[0].owner_name, "Goals Owner")


class TestGoalMap(GoalTestCase):
	def setUp(self):
		super().setUp()
		self.root = make_group("Map root")
		self.middle = make_group("Map middle", parents=[self.root.name])
		self.other = make_group("Map other", parents=[self.root.name])
		self.leaf = make_goal(
			"Map leaf",
			parents=[self.middle.name, self.other.name],
			progress_method="Auto",
			metric_source="Linked Documents",
			linked_document_type=GOAL,
			aggregation="Count",
			linked_document_filter=json.dumps({"subject": ["like", "Map %"]}),
		)

	def test_open_the_map_for_a_root_goal(self):
		data = api.get_goal_map(root=self.root.name, status="")
		self.assertEqual(len(data["trees"]), 1)
		tree = data["trees"][0]
		self.assertEqual(tree["name"], self.root.name)
		self.assertEqual({child["name"] for child in tree["children"]}, {self.middle.name, self.other.name})
		leaves = [grandchild for child in tree["children"] for grandchild in child["children"]]
		self.assertEqual([leaf["name"] for leaf in leaves], [self.leaf.name, self.leaf.name])
		self.assertTrue(all(leaf["shared"] for leaf in leaves))
		self.assertEqual(len({leaf["id"] for leaf in leaves}), 2)
		self.assertIn(tree["rag_status"], ("Green", "Yellow", "Red"))
		self.assertNotIn("linked", tree)

	def test_linked_documents_card(self):
		data = api.get_goal_map(root=self.root.name, show_linked=1, status="")
		leaf = data["trees"][0]["children"][0]["children"][0]
		self.assertEqual(leaf["linked"]["doctype"], GOAL)
		self.assertEqual(leaf["linked"]["count"], 4)
		self.assertEqual(leaf["linked"]["route_options"], {"subject": ["like", "Map %"]})
		self.assertIsNone(data["trees"][0]["linked"])

	def test_cancelled_goals_are_hidden(self):
		frappe.db.set_value(GOAL, self.other.name, "status", "Cancelled")
		tree = api.get_goal_map(root=self.root.name, status="")["trees"][0]
		self.assertEqual([child["name"] for child in tree["children"]], [self.middle.name, self.leaf.name])
		roots = [row.name for row in api.get_map_roots("Map")]
		self.assertIn(self.root.name, roots)
		self.assertNotIn(self.middle.name, roots)

	def test_map_follows_read_permission(self):
		with as_user(OUTSIDER):
			self.assertEqual(
				api.get_goal_map(root=self.root.name, status="")["trees"][0]["name"], self.root.name
			)

	def test_default_status_filter(self):
		for goal in (self.root, self.middle):
			activate(goal.name)
		tree = api.get_goal_map(root=self.root.name)["trees"][0]
		self.assertEqual([child["name"] for child in tree["children"]], [self.middle.name])
		self.assertEqual(tree["children"][0]["children"], [])
		self.assertEqual(tree["owner_name"], "Goals Owner")
		self.assertIn("owner_image", tree)
		drawn = set()
		for root in api.get_goal_map()["trees"]:
			drawn |= set(map_names(root))
		self.assertIn(self.root.name, drawn)
		self.assertFalse({self.other.name, self.leaf.name} & drawn)
		roots = [row.name for row in api.get_map_roots("Map", status="Draft")]
		self.assertNotIn(self.root.name, roots)

	def test_filtered_out_parent_lifts_the_children(self):
		for goal in (self.root, self.leaf):
			activate(goal.name)
		tree = api.get_goal_map(root=self.root.name)["trees"][0]
		self.assertEqual([child["name"] for child in tree["children"]], [self.leaf.name, self.leaf.name])
		self.assertEqual(len({child["id"] for child in tree["children"]}), 2)

	def test_filtered_out_root(self):
		activate(self.middle.name)
		trees = api.get_goal_map(root=self.root.name)["trees"]
		self.assertEqual([tree["name"] for tree in trees], [self.middle.name])
		self.assertEqual(trees[0]["children"], [])
		self.assertEqual(api.get_goal_map(root=self.root.name, status="Closed")["trees"], [])

	def test_period_filter(self):
		q3 = make_goal(
			"Map Q3", parents=[self.root.name], exp_start_date="2026-07-01", exp_end_date="2026-09-30"
		)
		q4 = make_goal(
			"Map Q4", parents=[self.root.name], exp_start_date="2026-10-01", exp_end_date="2026-12-31"
		)

		def drawn(**filters):
			names = set()
			for tree in api.get_goal_map(root=self.root.name, status="", **filters)["trees"]:
				names |= set(map_names(tree))
			return names

		names = drawn(period_from="2026-08", period_to="2026-09")
		self.assertIn(q3.name, names)
		self.assertNotIn(q4.name, names)
		self.assertTrue({q3.name, q4.name} <= drawn(period_from="2026-01", period_to="2026-12"))
		self.assertEqual(drawn(period_from="2026-09", period_to="2026-08"), names, "bounds are swapped")
		names = drawn(period_from="2026-10")
		self.assertIn(q4.name, names)
		self.assertNotIn(q3.name, names)
		names = drawn(period_to="2026-09")
		self.assertIn(q3.name, names)
		self.assertNotIn(q4.name, names)
		self.assertEqual(drawn(period_to="2025-12"), set())

	def test_several_statuses(self):
		activate(self.middle.name)
		frappe.db.set_value(GOAL, self.other.name, "status", "On Hold")
		names = set(map_names(api.get_goal_map(root=self.root.name, status=["Draft", "Active"])["trees"][0]))
		self.assertEqual(names, {self.root.name, self.middle.name, self.leaf.name})
		names = set(map_names(api.get_goal_map(root=self.root.name, status='["On Hold"]')["trees"][0]))
		self.assertEqual(names, {self.other.name})

	def test_several_types_and_owners(self):
		frappe.db.set_value(GOAL, self.other.name, "goal_type", "OKR")
		frappe.db.set_value(GOAL, self.other.name, "goal_owner", OUTSIDER)

		def seeds(**filters):
			names = set()
			for tree in api.get_goal_map(status="", **filters)["trees"]:
				names |= set(map_names(tree))
			return names & {self.root.name, self.middle.name, self.other.name, self.leaf.name}

		self.assertEqual(seeds(goal_type=["OKR"]), {self.other.name, self.leaf.name})
		self.assertEqual(
			seeds(goal_type=["OKR", "KPI"]),
			{self.root.name, self.middle.name, self.other.name, self.leaf.name},
		)
		self.assertEqual(seeds(goal_owner=[OUTSIDER]), {self.other.name, self.leaf.name})
		self.assertEqual(seeds(goal_owner=json.dumps([OUTSIDER, OWNER])), seeds())

	def test_project_filter(self):
		project = make_project("_GT-MAP-PRJ")
		group = make_group(
			"Map project group", params=[param("projects", "Link List", [project], link_doctype="Project")]
		)
		child = make_goal("Map project child", parents=[group.name])
		names = set()
		for tree in api.get_goal_map(status="", project=project)["trees"]:
			names |= set(map_names(tree))
		self.assertEqual(names, {group.name, child.name})


def map_names(node: dict):
	yield node["name"]
	for child in node["children"]:
		yield from map_names(child)
