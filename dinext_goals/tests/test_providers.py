import frappe

from dinext_goals.providers import get_provider, get_registry, list_providers
from dinext_goals.providers.energy_points import energy_points
from dinext_goals.providers.gl_profit import gl_profit
from dinext_goals.providers.project_budget import planned_project_profit
from dinext_goals.providers.timesheet_utilization import (
	APPROVED_TIMESHEET_STATUS,
	team_users,
	timesheet_totals,
	timesheet_utilization,
)
from dinext_goals.tests.utils import OWNER, OWNER_B, GoalTestCase, insert_raw, make_goal, make_group, param

COMPANY = "Dinext"
ROOT_CC = "Dinext - D"
INCOME = "Sales - D"
EXPENSE = "Salary - D"
CASH = "Cash - D"
PROJECT = "_GT-PRJ-1"
OTHER_PROJECT = "_GT-PRJ-2"


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
	account,
	*,
	debit=0,
	credit=0,
	cost_center=None,
	project=None,
	posting_date="2026-03-15",
	is_cancelled=0,
	company=COMPANY,
	**values,
):
	insert_raw(
		"GL Entry",
		{
			"company": company,
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
			"is_opening": "No",
			**values,
		},
	)


def journal(cost_center, amount, posting_date):
	doc = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"company": COMPANY,
			"posting_date": posting_date,
			"user_remark": "_GT",
			"accounts": [
				{"account": CASH, "debit_in_account_currency": amount, "cost_center": cost_center},
				{"account": INCOME, "credit_in_account_currency": amount, "cost_center": cost_center},
			],
		}
	)
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc


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

	def test_providers_describe_their_logic(self):
		for row in list_providers():
			self.assertTrue(row["description"], row["key"])
			self.assertTrue(row["details"], row["key"])
			self.assertTrue(all(isinstance(line, str) and line for line in row["details"]), row["key"])


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

	def test_closing_opening_and_other_books_are_excluded(self):
		gl(
			INCOME,
			debit=740,
			cost_center=self.child,
			voucher_type="Period Closing Voucher",
			voucher_no="_GT-PCV",
		)
		gl(INCOME, credit=10_000, cost_center=self.child, is_opening="Yes")
		book = insert_raw("Finance Book", {"finance_book_name": "_GT Book"}, name="_GT Book")
		gl(INCOME, credit=20_000, cost_center=self.child, finance_book=book.name)
		self.assertEqual(gl_profit(date_from="2026-03-01", date_to="2026-03-31", cost_center=self.group), 740)
		self.assertEqual(
			gl_profit(date_from="2026-03-01", date_to="2026-03-31", cost_center=self.group, company=COMPANY),
			740,
		)

	def test_different_currencies_need_a_company(self):
		other = frappe.get_all(
			"Company",
			filters={
				"name": ["!=", COMPANY],
				"default_currency": ["!=", frappe.db.get_value("Company", COMPANY, "default_currency")],
			},
			pluck="name",
			limit=1,
		)
		if not other:
			self.skipTest("no company with another currency")
		gl(INCOME, credit=100, cost_center=self.child, company=other[0])
		with self.assertRaises(frappe.ValidationError):
			gl_profit(date_from="2026-03-01", date_to="2026-03-31", cost_center=self.group)
		self.assertEqual(
			gl_profit(date_from="2026-03-01", date_to="2026-03-31", cost_center=self.group, company=COMPANY),
			740,
		)

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


class TestGLProfitDocuments(GoalTestCase):
	"""Submitted Journal Entries: cancellation and reversal through ERPNext itself."""

	def setUp(self):
		super().setUp()
		self.center = cost_center("_GT Ledger", ROOT_CC)

	def profit(self, date_from="2026-03-01", date_to="2026-03-31"):
		return gl_profit(date_from=date_from, date_to=date_to, cost_center=self.center, company=COMPANY)

	def test_cancelled_journal_entry(self):
		journal(self.center, 100, "2026-03-10")
		journal(self.center, 50, "2026-03-11").cancel()
		self.assertEqual(self.profit(), 100)

	def test_reversal_nets_by_posting_date(self):
		from erpnext.accounts.doctype.journal_entry.journal_entry import make_reverse_journal_entry

		journal(self.center, 100, "2026-03-10")
		for source_date, reversal_date in (("2026-03-12", "2026-03-20"), ("2026-03-25", "2026-04-05")):
			source = journal(self.center, 30, source_date)
			reversal = make_reverse_journal_entry(source.name)
			reversal.posting_date = reversal_date
			reversal.insert(ignore_permissions=True)
			reversal.submit()
		self.assertEqual(self.profit(), 130)
		self.assertEqual(self.profit("2026-04-01", "2026-04-30"), -30)
		self.assertEqual(self.profit("2026-03-01", "2026-04-30"), 100)


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
						for month in (6, 7, 8, 9, 10)
					]
					+ [{"pba_year": 2025, "pba_month": 7, "pba_plan": monthly}]
				},
			)

	def test_planned_profit(self):
		self.assertEqual(planned_project_profit([PROJECT]), 900_000)
		self.assertEqual(planned_project_profit([OTHER_PROJECT]), 0)
		with self.assertRaises(frappe.ValidationError):
			planned_project_profit([])

	def test_months_overlapping_the_period(self):
		self.assertEqual(planned_project_profit([PROJECT], "2026-07-01", "2026-09-30"), 450_000)
		self.assertEqual(planned_project_profit([PROJECT], "2026-07-31", "2026-08-01"), 300_000)
		self.assertEqual(planned_project_profit([PROJECT], "2025-12-01", "2026-06-15"), 150_000)
		self.assertEqual(planned_project_profit([PROJECT], "2026-11-01", "2026-12-31"), 0)
		self.assertEqual(planned_project_profit([PROJECT], "2026-08-01", "2026-07-01"), 0)

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
			exp_start_date="2026-07-01",
			exp_end_date="2026-09-30",
		)
		self.assertEqual(goal.target, 450_000)


class TestTimesheetUtilization(GoalTestCase):
	"""Values come from the stored totals of User Timesheet; the provider does not plan hours."""

	def setUp(self):
		super().setUp()
		self.group = cost_center("_GT Team", ROOT_CC, is_group=1)
		self.team_cc = cost_center("_GT Team A", self.group)
		self.other_cc = cost_center("_GT Team B", ROOT_CC)
		self._worker(OWNER, centers=[("2026-01-01", self.team_cc)])
		self._worker(OWNER_B, centers=[("2026-01-01", self.team_cc), ("2026-02-01", self.other_cc)])
		for user, start, end, status, utilized, plan in (
			(OWNER, "2026-03-02", "2026-03-08", APPROVED_TIMESHEET_STATUS, 10, 40),
			(OWNER, "2026-03-30", "2026-03-31", APPROVED_TIMESHEET_STATUS, 30, 20),
			(OWNER, "2026-03-09", "2026-03-15", "На согласовании", 40, 40),
			(OWNER, "2026-04-01", "2026-04-05", APPROVED_TIMESHEET_STATUS, 1, 100),
			(OWNER, "2026-02-23", "2026-03-01", APPROVED_TIMESHEET_STATUS, 1, 100),
			(OWNER_B, "2026-03-02", "2026-03-08", APPROVED_TIMESHEET_STATUS, 40, 40),
		):
			insert_raw(
				"User Timesheet",
				{
					"timesheet_from": user,
					"ts_valid_from": start,
					"ts_valid_for": end,
					"ut_status": status,
					"total_hours_utilized": utilized,
					"utilization_hours_plan": plan,
				},
				name=f"_GT {user} {start} {end}",
			)

	def _worker(self, user, *, centers):
		return insert_raw(
			"Worker",
			{"wuser": user, "wvalid_from": "2026-01-01"},
			children={"cost_center_table": [{"cct_valid_from": d, "cct_cost_center": c} for d, c in centers]},
		).name

	def test_ratio_of_sums_over_approved_timesheets(self):
		self.assertEqual(timesheet_totals([OWNER], "2026-03-01", "2026-03-31"), (40, 60))
		self.assertAlmostEqual(timesheet_utilization([OWNER], "2026-03-01", "2026-03-31"), 40 / 60 * 100)
		self.assertEqual(timesheet_utilization([OWNER], "2026-05-01", "2026-05-31"), 0)
		self.assertEqual(timesheet_utilization([], "2026-03-01", "2026-03-31"), 0)

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
			exp_start_date="2026-03-01",
			exp_end_date="2026-03-31",
		)
		self.assertAlmostEqual(goal.current_value, 40 / 60 * 100)
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
			exp_start_date="2026-03-01",
			exp_end_date="2026-03-31",
		)
		self.assertAlmostEqual(team.current_value, 40 / 60 * 100)


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
