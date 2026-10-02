import frappe

from dinext_goals.providers import get_provider, get_registry, list_providers
from dinext_goals.providers.energy_points import energy_points
from dinext_goals.providers.gl_profit import gl_profit
from dinext_goals.providers.project_budget import planned_project_profit
from dinext_goals.providers.timesheet_utilization import planned_hours, team_users, utilized_hours
from dinext_goals.tests.utils import OWNER, OWNER_B, GoalTestCase, insert_raw, make_goal, make_group, param

COMPANY = "Dinext"
ROOT_CC = "Dinext - D"
INCOME = "Sales - D"
EXPENSE = "Salary - D"
CASH = "Cash - D"
PROJECT = "_GT-PRJ-1"
OTHER_PROJECT = "_GT-PRJ-2"
APPROVED = "Согласовано"


def cost_center(name, parent, is_group=0):
	return (
		frappe.get_doc(
			{
				"doctype": "Cost Center",
				"cost_center_name": name,
				"company": COMPANY,
				"parent_cost_center": parent,
				"is_group": is_group,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def gl(
	account, *, debit=0, credit=0, cost_center=None, project=None, posting_date="2026-03-15", is_cancelled=0
):
	insert_raw(
		"GL Entry",
		{
			"company": COMPANY,
			"account": account,
			"debit": debit,
			"credit": credit,
			"debit_in_account_currency": debit,
			"credit_in_account_currency": credit,
			"cost_center": cost_center,
			"project": project,
			"posting_date": posting_date,
			"is_cancelled": is_cancelled,
			"voucher_type": "Journal Entry",
			"voucher_no": "_GT-JV",
		},
	)


class TestRegistry(GoalTestCase):
	def test_hook_registers_the_providers(self):
		self.assertEqual(
			set(get_registry()),
			{"gl_profit", "project_budget_profit", "timesheet_utilization", "energy_points"},
		)
		described = {row["key"]: row for row in list_providers()}
		self.assertTrue(described["project_budget_profit"]["supports_target"])
		self.assertFalse(described["gl_profit"]["supports_target"])
		with self.assertRaises(frappe.ValidationError):
			get_provider("no_such_provider")


class TestGLProfit(GoalTestCase):
	def setUp(self):
		super().setUp()
		self.group = cost_center("_GT Group", ROOT_CC, is_group=1)
		self.child = cost_center("_GT Child", self.group)
		self.other = cost_center("_GT Other", ROOT_CC)
		gl(INCOME, credit=1000, cost_center=self.child)
		gl(CASH, debit=1000, cost_center=self.child)
		gl(EXPENSE, debit=300, cost_center=self.group)
		gl(INCOME, credit=50, debit=10, cost_center=self.child)
		gl(INCOME, credit=500, cost_center=self.other)
		gl(INCOME, credit=900, cost_center=self.child, is_cancelled=1)
		gl(INCOME, credit=700, cost_center=self.child, posting_date="2026-04-01")
		gl(INCOME, credit=4000, cost_center=self.other, project=PROJECT)
		gl(EXPENSE, debit=1500, cost_center=ROOT_CC, project=PROJECT)
		gl(INCOME, credit=999, cost_center=self.child, project=OTHER_PROJECT, posting_date="2025-12-31")

	def test_profit_of_a_cost_center_group(self):
		self.assertEqual(gl_profit(date_from="2026-03-01", date_to="2026-03-31", cost_center=self.group), 740)
		self.assertEqual(
			gl_profit(date_from="2026-03-01", date_to="2026-04-30", cost_center=self.child), 1740
		)

	def test_projects_win_over_cost_center(self):
		self.assertEqual(
			gl_profit(
				date_from="2026-03-01", date_to="2026-03-31", cost_center=self.child, projects=[PROJECT]
			),
			2500,
		)

	def test_needs_a_parameter(self):
		with self.assertRaises(frappe.ValidationError):
			gl_profit(date_from="2026-03-01", date_to="2026-03-31")

	def test_goal_with_inherited_cost_center(self):
		root = make_group(
			"Root", params=[param("cost_center", "Link", self.group, link_doctype="Cost Center")]
		)
		goal = make_goal(
			"Profit",
			parents=[root.name],
			metric_type="Currency",
			target=1000,
			progress_method="Auto",
			metric_source="Provider",
			metric_provider="gl_profit",
			exp_start_date="2026-03-01",
			exp_end_date="2026-03-31",
		)
		self.assertEqual(goal.current_value, 740)
		self.assertEqual(goal.achievement_percent, 74)


class TestProjectBudget(GoalTestCase):
	def setUp(self):
		super().setUp()
		insert_raw("Project", {"project_name": PROJECT, "status": "Open", "company": COMPANY}, name=PROJECT)
		for account, monthly in ((INCOME, 300_000), (EXPENSE, 150_000), (CASH, 999)):
			insert_raw(
				"Project Budget",
				{"pb_project": PROJECT, "pb_account": account},
				children={
					"project_budget_amount": [
						{"pba_year": 2026, "pba_month": month, "pba_plan": monthly}
						for month in (8, 9, 10, 11)
					]
				},
			)

	def test_planned_profit(self):
		self.assertEqual(planned_project_profit([PROJECT]), 600_000)
		self.assertEqual(planned_project_profit([OTHER_PROJECT]), 0)
		with self.assertRaises(frappe.ValidationError):
			planned_project_profit([])

	def test_target_from_the_project_budget(self):
		goal = make_goal(
			"Project bonus",
			params=[param("projects", "Link List", [PROJECT], link_doctype="Project")],
			metric_type="Currency",
			target=0,
			target_source="Provider",
			target_provider="project_budget_profit",
			progress_method="Auto",
			metric_source="Provider",
			metric_provider="gl_profit",
		)
		self.assertEqual(goal.target, 600_000)


class TestTimesheetUtilization(GoalTestCase):
	"""2026-03-02..10: 7-9 off, 5 a shortened 7h day, 2 a 3h absence, 6 a full leave, 10 an «Отгул»."""

	def setUp(self):
		super().setUp()
		holidays = insert_raw(
			"Holiday List",
			{"holiday_list_name": "_GT Holidays", "from_date": "2026-01-01", "to_date": "2026-12-31"},
			name="_GT Holidays",
			children={
				"holidays": [
					{"holiday_date": d, "description": "off"}
					for d in ("2026-03-07", "2026-03-08", "2026-03-09")
				]
			},
		)
		hours = insert_raw(
			"Working Hours On Date",
			{"hod_from_date": "2026-01-01", "hod_to_date": "2026-12-31"},
			name="_GT Short Days",
			children={"hod_working_hours_table": [{"wht_date": "2026-03-05", "wht_hours": 7}]},
		)
		template = insert_raw(
			"Timesheet Template",
			{"ttsubject": "_GT Template", "hours_on_date": 8, "tt_working_hours_on_date": hours.name},
			name="_GT Template",
		)
		self.group = cost_center("_GT Team", ROOT_CC, is_group=1)
		self.team_cc = cost_center("_GT Team A", self.group)
		self.other_cc = cost_center("_GT Team B", ROOT_CC)
		self.worker = self._worker(
			OWNER,
			holidays.name,
			template.name,
			utilization=[("2026-01-01", 50), ("2026-03-04", 100)],
			centers=[("2026-01-01", self.team_cc)],
		)
		self._worker(
			OWNER_B,
			holidays.name,
			template.name,
			utilization=[("2026-01-01", 100)],
			centers=[("2026-01-01", self.team_cc), ("2026-02-01", self.other_cc)],
		)
		for start, end, kind, status, from_hours in (
			("2026-03-02", "2026-03-02", "Отпуск", APPROVED, 3),
			("2026-03-03", "2026-03-03", "Отпуск", "На согласовании", 0),
			("2026-03-06", "2026-03-06", "Отпуск", APPROVED, 0),
			("2026-03-10", "2026-03-10", "Отгул", APPROVED, 0),
		):
			insert_raw(
				"Application For Leave",
				{
					"lauser": OWNER,
					"alworker": self.worker,
					"status": status,
					"alfrom_date": start,
					"alto_date": end,
					"alfrom_hours": from_hours,
					"altype_of_leave": kind,
				},
				name=f"_GT {start} {kind} {status}",
			)
		self._position(OWNER, APPROVED, {"2026-03-02": 4, "2026-03-05": 6, "2026-03-11": 5})
		self._position(OWNER, "На согласовании", {"2026-03-04": 10})

	def _worker(self, user, holiday_list, template, *, utilization, centers):
		return insert_raw(
			"Worker",
			{
				"wuser": user,
				"wholiday_list": holiday_list,
				"wtimesheet_template": template,
				"wvalid_from": "2026-01-01",
			},
			children={
				"utilization": [{"util_valid_from": d, "utilization": v} for d, v in utilization],
				"cost_center_table": [{"cct_valid_from": d, "cct_cost_center": c} for d, c in centers],
			},
		).name

	def _position(self, user, status, hours):
		insert_raw(
			"User Timesheet Position",
			{"user": user, "status": status, "workflow_state": status, "custom_data": "_GT"},
			children={"table": [{"date": d, "hours": h, "utilized_hours": h} for d, h in hours.items()]},
		)

	def test_utilization_plan_with_a_shortened_day(self):
		# 2.5 (5h at 50%) + 4 (8h at 50%) + 8 + 7 (shortened) + 0 (leave) + 8 («Отгул» is not an absence)
		self.assertEqual(planned_hours(OWNER, "2026-03-02", "2026-03-10"), 29.5)
		self.assertEqual(planned_hours(OWNER, "2026-03-07", "2026-03-09"), 0)
		self.assertEqual(utilized_hours([OWNER], "2026-03-02", "2026-03-10"), 10)

	def test_team_follows_the_latest_cost_center(self):
		self.assertEqual(team_users(self.group, "2026-03-10"), [OWNER])
		self.assertEqual(sorted(team_users(self.group, "2026-01-15")), sorted([OWNER, OWNER_B]))

	def test_goal_value(self):
		goal = make_goal(
			"Utilization",
			metric_type="Percent",
			progress_method="Auto",
			metric_source="Provider",
			metric_provider="timesheet_utilization",
			exp_start_date="2026-03-02",
			exp_end_date="2026-03-10",
		)
		self.assertAlmostEqual(goal.current_value, 10 / 29.5 * 100)
		team = make_goal(
			"Team utilization",
			owner=OWNER_B,
			params=[
				param("scope", "Select", "team", options="user\nteam"),
				param("cost_center", "Link", self.group, link_doctype="Cost Center"),
			],
			metric_type="Percent",
			progress_method="Auto",
			metric_source="Provider",
			metric_provider="timesheet_utilization",
			exp_start_date="2026-03-02",
			exp_end_date="2026-03-10",
		)
		self.assertAlmostEqual(team.current_value, 10 / 29.5 * 100)


class TestEnergyPoints(GoalTestCase):
	def _log(self, points, creation, **values):
		insert_raw(
			"Energy Point Log",
			{
				"user": OWNER,
				"type": "Auto",
				"points": points,
				"reason": "_GT",
				"creation": creation,
				"modified": creation,
				**values,
			},
		)

	def test_period_includes_the_whole_last_day(self):
		self._log(10, "2026-03-01 00:00:00")
		self._log(20, "2026-03-31 23:30:00")
		self._log(40, "2026-04-01 00:00:01")
		self._log(80, "2026-02-28 23:59:59")
		self._log(160, "2026-03-15 12:00:00", type="Review")
		self._log(320, "2026-03-15 12:00:00", reverted=1)
		self.assertEqual(energy_points(OWNER, "2026-03-01", "2026-03-31"), 30)

	def test_goal_counts_owner_points(self):
		self._log(45, "2026-03-10 10:00:00")
		goal = make_goal(
			"Points",
			params=[param("points_plan", "Int", 90)],
			target_source="Formula",
			target_formula="params.points_plan",
			progress_method="Auto",
			metric_source="Provider",
			metric_provider="energy_points",
			exp_start_date="2026-03-01",
			exp_end_date="2026-03-31",
		)
		self.assertEqual(goal.target, 90)
		self.assertEqual(goal.current_value, 45)
		self.assertEqual(goal.achievement_percent, 50)
