import datetime

import frappe
from frappe.tests.utils import FrappeTestCase

from dinext_goals.constants import GOAL, GOAL_LOG
from dinext_goals.demo.motivation_itk import MANAGER_RESULT, MONTHLY_RESULT, PROJECT_RESULT, SPECIALIST_RESULT
from dinext_goals.progress import engine, metrics, planning, rollup, scale
from dinext_goals.tests.utils import GoalTestCase, make_goal, make_group, param

MANAGER_KPERS_SCALE = ((0, 0.5), (50, 0.8), (90, 1), (110, 1.2))
POINTS_SCALE = ((0, 0), (50, 0.5), (80, 1), (120.0001, 1.2))


def steps(pairs):
	return [{"threshold_percent": t, "coefficient": c} for t, c in pairs]


class TestProgressArithmetic(FrappeTestCase):
	def test_increase_goal_over_plan(self):
		self.assertEqual(metrics.achievement("Numeric", 0, 100, 120), 120)
		self.assertEqual(metrics.clamp_progress(120), 100)

	def test_decrease_goal(self):
		self.assertEqual(metrics.achievement("Numeric", 100, 50, 75), 50)
		self.assertEqual(metrics.achievement("Numeric", 100, 50, 40), 120)

	def test_boolean_and_zero_span(self):
		self.assertEqual(metrics.achievement("Boolean", 0, 1, 1), 100)
		self.assertEqual(metrics.achievement("Boolean", 0, 1, 0), 0)
		self.assertEqual(metrics.achievement("Numeric", 5, 5, 5), 100)
		self.assertEqual(metrics.achievement("Numeric", 5, 5, 4), 0)

	def test_linear_plan(self):
		self.assertEqual(planning.planned_progress("2026-01-01", "2026-01-11", "2026-01-01"), 0)
		self.assertEqual(planning.planned_progress("2026-01-01", "2026-01-11", "2026-01-06"), 50)
		self.assertEqual(planning.planned_progress("2026-01-01", "2026-01-11", "2026-02-01"), 100)
		self.assertEqual(planning.planned_progress(None, "2026-01-11", "2026-01-06"), 0)
		self.assertEqual(planning.planned_value(100, 50, 50), 75)

	def test_rag_and_overdue(self):
		self.assertEqual(planning.rag(-5, False, 10, 25), "Green")
		self.assertEqual(planning.rag(40, False, 10, 25), "Green")
		self.assertEqual(planning.rag(-10.01, False, 10, 25), "Yellow")
		self.assertEqual(planning.rag(-25.01, False, 10, 25), "Red")
		self.assertEqual(planning.rag(50, True, 10, 25), "Red")
		self.assertTrue(planning.is_overdue("Active", "2026-01-31", 99, "2026-02-01"))
		self.assertFalse(planning.is_overdue("Active", "2026-01-31", 100, "2026-02-01"))
		self.assertFalse(planning.is_overdue("Closed", "2026-01-31", 10, "2026-02-01"))
		self.assertFalse(planning.is_overdue("Draft", "2026-01-31", 10, "2026-02-01"))

	def test_calculation_period(self):
		d = datetime.date
		self.assertEqual(
			planning.calculation_period("2026-07-01", "2026-09-30", "2026-08-15"),
			(d(2026, 7, 1), d(2026, 8, 15)),
		)
		self.assertEqual(
			planning.calculation_period("2026-07-01", "2026-09-30", "2026-10-02"),
			(d(2026, 7, 1), d(2026, 9, 30)),
		)
		self.assertEqual(
			planning.calculation_period("2026-07-01", "2026-09-30", "2026-06-01"),
			(d(2026, 7, 1), d(2026, 7, 1)),
		)
		self.assertEqual(planning.calculation_period(None, None, "2026-06-01"), (None, None))

	def test_weighted_roll_up(self):
		children = [
			{"progress": 90, "weight": 2, "status": "Active"},
			{"progress": 30, "weight": 1, "status": "Active"},
			{"progress": 0, "weight": 5, "status": "Cancelled"},
			{"progress": 0, "weight": 0, "status": "Active"},
		]
		self.assertEqual(rollup.weighted_progress(children), 70)
		self.assertIsNone(rollup.weighted_progress([{"progress": 50, "weight": 0, "status": "Active"}]))
		children = [
			{"achievement": 120, "weight": 0.5, "status": "Active"},
			{"achievement": 60, "weight": 0.5, "status": "Active"},
			{"achievement": 0, "weight": 1, "status": "Cancelled"},
		]
		self.assertEqual(rollup.weighted(children, "achievement"), 90)

	def test_scale_boundary(self):
		rows = steps(MANAGER_KPERS_SCALE)
		for achievement, expected in (
			(-1, 0),
			(0, 0.5),
			(49.99, 0.5),
			(50, 0.8),
			(89.99, 0.8),
			(90, 1),
			(109.99, 1),
			(110, 1.2),
			(500, 1.2),
		):
			self.assertEqual(scale.coefficient(rows, achievement), expected, achievement)
		points = steps(POINTS_SCALE)
		self.assertEqual(scale.coefficient(points, 120), 1)
		self.assertEqual(scale.coefficient(points, 120.01), 1.2)
		self.assertIsNone(scale.coefficient([], 50))

	def test_scale_spec(self):
		rows = scale.parse_spec("0:0.5; 50:0.8,90:1\n110:1.2")
		self.assertEqual(
			[(r["threshold_percent"], r["coefficient"]) for r in rows], list(MANAGER_KPERS_SCALE)
		)
		self.assertEqual(scale.to_spec([frappe._dict(r) for r in rows]), "0:0.5\n50:0.8\n90:1\n110:1.2")
		for bad in ("50", "a:b"):
			with self.assertRaises(frappe.ValidationError):
				scale.parse_spec(bad)


class TestRecalculation(GoalTestCase):
	def test_weighted_roll_up_on_save(self):
		group = make_group("Group")
		make_goal("Heavy", parents=[group.name], weight=2, current_value=90)
		make_goal("Light", parents=[group.name], weight=1, current_value=30)
		self.assertEqual(self.reload(group.name).progress, 70)

	def test_group_achievement_is_weighted(self):
		group = make_group("Group")
		make_goal("Over", parents=[group.name], weight=1, current_value=120)
		make_goal("Under", parents=[group.name], weight=1, current_value=60)
		cancelled = make_goal("Dropped", parents=[group.name], weight=1, current_value=0)
		frappe.db.set_value(GOAL, cancelled.name, "status", "Cancelled")
		engine.recalculate(group.name)
		group = self.reload(group.name)
		self.assertEqual(group.achievement_percent, 90)
		self.assertEqual(group.progress, 80)

	def test_manual_group_achievement_equals_progress(self):
		group = make_group("Manual", progress_method="Manual", progress=40)
		make_goal("Over", parents=[group.name], current_value=150)
		group = self.reload(group.name)
		self.assertEqual(group.progress, 40)
		self.assertEqual(group.achievement_percent, 40)

	def test_deviation_sign(self):
		ahead = make_goal("Ahead", exp_start_date="2026-01-01", exp_end_date="2026-01-11", current_value=70)
		behind = make_goal("Behind", exp_start_date="2026-01-01", exp_end_date="2026-01-11", current_value=20)
		for goal in (ahead, behind):
			engine.recalculate(goal.name, on_date="2026-01-06")
		ahead, behind = self.reload(ahead.name), self.reload(behind.name)
		self.assertEqual((ahead.deviation, ahead.rag_status), (20, "Green"))
		self.assertEqual((behind.deviation, behind.rag_status), (-30, "Red"))

	def test_recalculate_from_a_leaf(self):
		root = make_group("Root")
		middle = make_group("Middle", parents=[root.name])
		leaf = make_goal("Leaf", parents=[middle.name], current_value=10)
		frappe.db.set_value(GOAL, leaf.name, "current_value", 80)
		summary = engine.recalculate(leaf.name)
		self.assertEqual(summary["errors"], [])
		self.assertEqual(self.reload(leaf.name).progress, 80)
		self.assertEqual(self.reload(middle.name).progress, 80)
		self.assertEqual(self.reload(root.name).progress, 80)

	def test_calculated_change_is_logged(self):
		root = make_group("Root", params=[param("plan", "Float", 10)])
		leaf = make_goal(
			"Leaf",
			parents=[root.name],
			progress_method="Auto",
			metric_source="Python Rule",
			calculation_rule="params.plan",
		)
		frappe.db.set_value("Goal Parameter", {"parent": root.name, "code": "plan"}, "value_number", 40)
		before = frappe.db.count(GOAL_LOG, {"goal": leaf.name, "source": "Auto"})
		engine.recalculate(root.name)
		self.assertEqual(frappe.db.count(GOAL_LOG, {"goal": leaf.name, "source": "Auto"}), before + 1)
		engine.recalculate(root.name)
		self.assertEqual(
			frappe.db.count(GOAL_LOG, {"goal": leaf.name, "source": "Auto"}), before + 1, "no change, no log"
		)

	def test_overdue_goal(self):
		goal = make_goal("Late", exp_start_date="2025-01-01", exp_end_date="2025-06-30", current_value=40)
		frappe.db.set_value(GOAL, goal.name, "status", "Active")
		engine.recalculate(goal.name, on_date="2025-07-01")
		goal = self.reload(goal.name)
		self.assertEqual(goal.is_overdue, 1)
		self.assertEqual(goal.rag_status, "Red")
		self.assertEqual(goal.planned_progress, 100)
		self.assertEqual(goal.deviation, -60)

	def test_rag_follows_settings(self):
		goal = make_goal("Half", exp_start_date="2026-01-01", exp_end_date="2026-01-11", current_value=35)
		engine.recalculate(goal.name, on_date="2026-01-06")
		self.assertEqual(self.reload(goal.name).rag_status, "Yellow")
		frappe.db.set_single_value("Goals Settings", "yellow_threshold", 20)
		engine.recalculate(goal.name, on_date="2026-01-06")
		self.assertEqual(self.reload(goal.name).rag_status, "Green")

	def test_result_from_children(self):
		group = make_group(
			"Group",
			params=[param("share", "Percent", 10)],
			result_formula='params.share * child("A").value + child("B").coefficient',
		)
		make_goal("A", parents=[group.name], goal_code="A", current_value=500)
		make_goal("B", parents=[group.name], goal_code="B", current_value=95, scale=MANAGER_KPERS_SCALE)
		self.assertAlmostEqual(self.reload(group.name).result_value, 51)

	def test_broken_formula_keeps_values_and_reports(self):
		group = make_group("Group", result_formula='child("MISSING").value')
		make_goal("A", parents=[group.name], goal_code="A", current_value=10)
		summary = engine.recalculate(group.name)
		self.assertEqual([row["goal"] for row in summary["errors"]], [group.name])
		self.assertIn("MISSING", summary["errors"][0]["message"])


class TestMotivationFormulas(GoalTestCase):
	"""The result formulas of the shipped templates, on hand-entered values."""

	def _manager_tree(self, company_value, profit_value, kpers_value, gate="ORG-PROFIT"):
		params = [param("profit_share", "Percent", 5)]
		if gate:
			params.append(param("gate_goal_code", "Data", gate))
		root = make_group("Company", params=params)
		make_goal(
			"Company profit",
			parents=[root.name],
			goal_code="ROOT-ORG-PROFIT",
			target=2_500_000,
			current_value=company_value,
		)
		cfo = make_group("Department", parents=[root.name], goal_code="ROOT-DEP")
		mgr = make_group(
			"Manager bonus", parents=[cfo.name], goal_code="ROOT-DEP-MGR", result_formula=MANAGER_RESULT
		)
		make_goal(
			"Profit",
			parents=[mgr.name],
			goal_code="ROOT-DEP-PROFIT",
			target=1_000_000,
			current_value=profit_value,
			scale=((0, 0), (50, 1)),
		)
		make_goal(
			"Team utilization",
			parents=[mgr.name],
			goal_code="ROOT-DEP-KPERS",
			current_value=kpers_value,
			scale=MANAGER_KPERS_SCALE,
		)
		return self.reload(mgr.name).result_value

	def test_manager_bonus(self):
		self.assertAlmostEqual(self._manager_tree(1_756_000, 1_356_000, 113.18), 0.05 * 1_356_000 * 1 * 1.2)

	def test_manager_bonus_when_company_below_half(self):
		self.assertAlmostEqual(self._manager_tree(1_000_000, 850_000, 95), 0.05 * 850_000 * 1 * 1)
		self.assertEqual(self._manager_tree(1_000_000, 790_000, 95), 0)

	def test_manager_bonus_without_company_profit(self):
		self.assertEqual(self._manager_tree(-10, 1_356_000, 113.18), 0)

	def test_manager_bonus_without_gate(self):
		self.assertAlmostEqual(self._manager_tree(-10, 790_000, 95, gate=None), 0.05 * 790_000 * 1 * 1)

	def test_specialist_bonus(self):
		spec = make_group(
			"Specialist", params=[param("bonus_base", "Percent", 15)], result_formula=SPECIALIST_RESULT
		)
		make_goal(
			"Util",
			parents=[spec.name],
			goal_code="UTIL",
			current_value=85.52,
			scale=((0, 0), (50, 0.3), (90, 1)),
		)
		make_goal(
			"Points",
			parents=[spec.name],
			goal_code="POINTS",
			target=600,
			current_value=435,
			scale=POINTS_SCALE,
		)
		make_goal(
			"Personal",
			parents=[spec.name],
			goal_code="KPERS",
			current_value=80,
			scale=((50, 0.5), (80, 0.8), (100, 1), (120, 1.2)),
		)
		expected = round(0.3 * 85.52 / 100 * 0.15 * 0.8 * 0.5 * 100, 2)
		self.assertAlmostEqual(self.reload(spec.name).result_value, expected)

	def test_monthly_bonus(self):
		month = make_goal(
			"Month",
			params=[param("k_prem", "Percent", 20)],
			metric_type="Percent",
			current_value=40.18,
			result_formula=MONTHLY_RESULT,
		)
		self.assertAlmostEqual(month.result_value, round(0.2 * 0.4018 * 100, 2))
		capped = make_goal(
			"Capped",
			params=[param("k_prem", "Percent", 20)],
			metric_type="Percent",
			current_value=130,
			result_formula=MONTHLY_RESULT,
		)
		self.assertAlmostEqual(capped.result_value, 20)

	def test_project_bonus(self):
		project = make_goal(
			"Project",
			params=[param("project_bonus_share", "Percent", 30)],
			metric_type="Currency",
			target=966_000,
			current_value=1_220_000,
			result_formula=PROJECT_RESULT,
		)
		self.assertAlmostEqual(project.result_value, 0.3 * (1_220_000 - 966_000))
		short = make_goal(
			"Short",
			params=[param("project_bonus_share", "Percent", 30)],
			metric_type="Currency",
			target=966_000,
			current_value=500_000,
			result_formula=PROJECT_RESULT,
		)
		self.assertEqual(short.result_value, 0)
