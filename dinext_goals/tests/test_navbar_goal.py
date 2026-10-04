import frappe
from frappe.utils import add_days, nowdate

from dinext_goals.api import get_navbar_goal
from dinext_goals.constants import GOAL, SETTINGS
from dinext_goals.tests.utils import (
	MANAGER,
	OWNER,
	OWNER_B,
	GoalTestCase,
	activate,
	as_user,
	make_goal,
	make_group,
)


def current(subject, **values):
	values.setdefault("exp_start_date", add_days(nowdate(), -10))
	values.setdefault("exp_end_date", add_days(nowdate(), 20))
	maker = make_group if values.pop("group", False) else make_goal
	goal = maker(subject, **values)
	activate(goal.name)
	return goal


class TestNavbarGoal(GoalTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.set_single_value(SETTINGS, "show_top_goal_in_navbar", 1)

	def navbar_goal(self, user=OWNER):
		with as_user(user):
			return get_navbar_goal()

	def test_disabled_setting(self):
		current("Own goal", owner=OWNER)
		frappe.db.set_single_value(SETTINGS, "show_top_goal_in_navbar", 0)
		self.assertIsNone(self.navbar_goal())

	def test_the_shallowest_own_goal_wins(self):
		company = current("Company", owner=MANAGER, group=True)
		team = current("Team", owner=OWNER, parents=[company.name], group=True)
		current("Personal", owner=OWNER, parents=[team.name])
		goal = self.navbar_goal()
		self.assertEqual(goal["name"], team.name)
		self.assertEqual(goal["is_group"], 1)
		self.assertEqual(self.navbar_goal(MANAGER)["name"], company.name)
		self.assertIsNone(self.navbar_goal(OWNER_B))

	def test_only_active_goals_covering_today(self):
		draft = make_goal("Draft", owner=OWNER)
		self.assertEqual(frappe.db.get_value(GOAL, draft.name, "status"), "Draft")
		closed = current("Closed", owner=OWNER)
		frappe.db.set_value(GOAL, closed.name, "status", "Closed")
		current("Finished", owner=OWNER, exp_start_date="2025-01-01", exp_end_date=add_days(nowdate(), -1))
		current(
			"Future", owner=OWNER, exp_start_date=add_days(nowdate(), 1), exp_end_date=add_days(nowdate(), 30)
		)
		self.assertIsNone(self.navbar_goal())

	def test_leaf_value_and_unit(self):
		goal = current(
			"Revenue",
			owner=OWNER,
			metric_type="Currency",
			currency="RUB",
			unit="",
			target=1000,
			current_value=250,
		)
		result = self.navbar_goal()
		self.assertEqual(result["name"], goal.name)
		self.assertEqual(result["metric_type"], "Currency")
		self.assertEqual(result["currency"], "RUB")
		self.assertEqual((result["current_value"], result["target"]), (250, 1000))
		self.assertIn(result["rag_status"], ("Green", "Yellow", "Red"))
		self.assertNotIn("weight", result)

	def test_tie_prefers_a_group(self):
		current("Leaf", owner=OWNER, weight=5)
		group = current("Group", owner=OWNER, group=True)
		self.assertEqual(self.navbar_goal()["name"], group.name)
