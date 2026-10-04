from datetime import date

import frappe

from dinext_goals import campaigns, templates
from dinext_goals.constants import GOAL, GOAL_CAMPAIGN, GOAL_TEMPLATE
from dinext_goals.tests.test_providers import ROOT_CC, cost_center
from dinext_goals.tests.utils import (
	MANAGER,
	OWNER,
	OWNER_B,
	PLAIN,
	GoalTestCase,
	as_user,
	insert_raw,
	make_group,
	param,
)

COMPANY = "Dinext"
TEMPLATE = "_GT Team Bonus"


def make_template(name=TEMPLATE, **values):
	return frappe.get_doc(
		{
			"doctype": GOAL_TEMPLATE,
			"template_name": name,
			"goal_type": "KPI",
			"default_duration_days": 92,
			"items": [
				{"item_key": "ROOT", "subject": "Team bonus", "goal_code": "BONUS", "is_group": 1},
				{
					"item_key": "SALES",
					"parent_key": "ROOT",
					"subject": "Sales",
					"goal_code": "SALES",
					"metric_type": "Numeric",
					"target": 100,
					"progress_method": "Manual",
				},
				{
					"item_key": "REVIEW",
					"parent_key": "ROOT",
					"subject": "Review",
					"goal_code": "REVIEW",
					"metric_type": "Boolean",
					"progress_method": "Manual",
					"start_offset_days": 80,
					"duration_days": 30,
				},
			],
			"template_parameters": [
				param("grade", "Int") | {"ask_on_create": 1, "label": "Grade"},
				param("share", "Percent", 10) | {"ask_on_create": 1, "label": "Share"},
			],
			**values,
		}
	).insert(ignore_permissions=True)


def make_campaign(rows, **values):
	doc = frappe.get_doc(
		{
			"doctype": GOAL_CAMPAIGN,
			"period_type": "Quarter",
			"period_start": "2027-01-01",
			"company": COMPANY,
			"items": rows,
			**values,
		}
	)
	return doc.insert(ignore_permissions=True)


def goals_of(template):
	return frappe.get_all(GOAL, filters={"goal_template": template}, pluck="name")


class TestPeriods(GoalTestCase):
	def test_bounds_of_each_period_type(self):
		self.assertEqual(
			campaigns.period_bounds("Month", "2027-02-15"), (date(2027, 2, 1), date(2027, 2, 28))
		)
		self.assertEqual(
			campaigns.period_bounds("Quarter", "2027-05-20"), (date(2027, 4, 1), date(2027, 6, 30))
		)
		self.assertEqual(
			campaigns.period_bounds("Half-Year", "2027-08-01"), (date(2027, 7, 1), date(2027, 12, 31))
		)
		self.assertEqual(
			campaigns.period_bounds("Year", "2027-08-01"), (date(2027, 1, 1), date(2027, 12, 31))
		)
		self.assertEqual(
			campaigns.period_bounds("Custom", "2027-03-05", "2027-03-20"),
			(date(2027, 3, 5), date(2027, 3, 20)),
		)
		with self.assertRaises(frappe.ValidationError):
			campaigns.period_bounds("Custom", "2027-03-05", "2027-03-01")

	def test_next_period(self):
		self.assertEqual(
			campaigns.next_period("Quarter", "2026-10-01"), (date(2027, 1, 1), date(2027, 3, 31))
		)
		self.assertEqual(campaigns.next_period("Month", "2027-01-01"), (date(2027, 2, 1), date(2027, 2, 28)))
		self.assertEqual(
			campaigns.next_period("Custom", "2027-03-05", "2027-03-20"), (date(2027, 3, 21), date(2027, 4, 5))
		)
		self.assertEqual(campaigns.default_start("Quarter", "2026-10-03"), date(2027, 1, 1))
		self.assertEqual(campaigns.default_start("Year", "2026-10-03"), date(2027, 1, 1))
		self.assertEqual(campaigns.default_start("Month", "2026-12-15"), date(2027, 1, 1))

	def test_codes_and_labels(self):
		self.assertEqual(campaigns.period_code("Quarter", "2027-04-01", "2027-06-30"), "2027Q2")
		self.assertEqual(campaigns.period_code("Half-Year", "2027-07-01", "2027-12-31"), "2027H2")
		self.assertEqual(campaigns.period_code("Month", "2027-11-01", "2027-11-30"), "2027-11")
		self.assertEqual(campaigns.period_label("Year", "2027-01-01", "2027-12-31"), "2027")
		self.assertIn("2027", campaigns.period_label("Quarter", "2027-04-01", "2027-06-30"))


class TestCampaignValidation(GoalTestCase):
	def setUp(self):
		super().setUp()
		make_template()

	def test_period_rows_and_summary(self):
		doc = make_campaign(
			[
				{"goal_owner": MANAGER, "template": TEMPLATE, "parameter_values": {"grade": 3, "share": 15}},
				{"goal_owner": OWNER, "template": TEMPLATE, "parent_row": "R1"},
			],
			period_start="2027-02-15",
		)
		self.assertEqual((doc.period_start, doc.period_end), (date(2027, 1, 1), date(2027, 3, 31)))
		self.assertTrue(doc.title)
		self.assertIn(doc.period_label, doc.title)
		self.assertEqual([row.row_key for row in doc.items], ["R1", "R2"])
		self.assertEqual(doc.items[0].parameter_summary, "Grade: 3; Share: 15%")
		self.assertEqual(doc.status, "Draft")

	def test_parent_rows_must_exist_and_not_cycle(self):
		with self.assertRaises(frappe.ValidationError):
			make_campaign([{"goal_owner": OWNER, "template": TEMPLATE, "parent_row": "R9"}])
		with self.assertRaises(frappe.ValidationError):
			make_campaign(
				[
					{"goal_owner": MANAGER, "template": TEMPLATE, "row_key": "R1", "parent_row": "R2"},
					{"goal_owner": OWNER, "template": TEMPLATE, "row_key": "R2", "parent_row": "R1"},
				]
			)


class TestCampaignTeam(GoalTestCase):
	def test_cost_center_team(self):
		group = cost_center("_GT Campaign Team", ROOT_CC, is_group=1)
		child = cost_center("_GT Campaign Team A", group)
		for user in (OWNER, OWNER_B):
			insert_raw(
				"Worker",
				{"wuser": user, "wvalid_from": "2026-01-01"},
				children={"cost_center_table": [{"cct_valid_from": "2026-01-01", "cct_cost_center": child}]},
			)
		team = campaigns.get_team("Cost Center", group, "2027-01-01")
		self.assertEqual(sorted(row["user"] for row in team), sorted([OWNER, OWNER_B]))
		self.assertTrue(all(row["full_name"] for row in team))

	def test_department_team(self):
		parent = frappe.get_doc(
			{
				"doctype": "Department",
				"department_name": "_GT Campaign Dept",
				"company": COMPANY,
				"is_group": 1,
				"parent_department": "All Departments",
			}
		).insert(ignore_permissions=True)
		child = frappe.get_doc(
			{
				"doctype": "Department",
				"department_name": "_GT Campaign Sub",
				"company": COMPANY,
				"parent_department": parent.name,
			}
		).insert(ignore_permissions=True)
		for index, (user, department, status) in enumerate(
			((OWNER, child.name, "Active"), (OWNER_B, parent.name, "Left"), (MANAGER, parent.name, "Active"))
		):
			insert_raw(
				"Employee",
				{
					"first_name": user,
					"employee_name": user,
					"user_id": user,
					"department": department,
					"status": status,
					"company": COMPANY,
				},
				name=f"_GT-CMP-EMP-{index}",
			)
		team = campaigns.get_team("Department", parent.name)
		self.assertEqual(sorted(row["user"] for row in team), sorted([OWNER, MANAGER]))

	def test_needs_write_access(self):
		with as_user(PLAIN), self.assertRaises(frappe.PermissionError):
			campaigns.get_team("Department", "All Departments")


class TestCampaignCreation(GoalTestCase):
	def setUp(self):
		super().setUp()
		make_template()
		self.parent = make_group(
			"Company goals", owner=MANAGER, exp_start_date="2027-01-01", exp_end_date="2027-12-31"
		)

	def _campaign(self, **values):
		return make_campaign(
			[
				{"goal_owner": MANAGER, "template": TEMPLATE, "parameter_values": {"grade": 5}},
				{
					"goal_owner": OWNER,
					"template": TEMPLATE,
					"parent_row": "R1",
					"parameter_values": {"grade": 2},
				},
			],
			default_parent_goal=self.parent.name,
			**values,
		)

	def test_create_for_the_team(self):
		doc = self._campaign()
		summary = campaigns.create(doc.name)
		self.assertEqual(summary, {"rows": 2, "goals": 6, "skipped": 0, "errors": 0})
		doc.reload()
		self.assertEqual(doc.status, "Created")
		lead, member = doc.items
		self.assertEqual((lead.status, member.status), ("Created", "Created"))
		self.assertEqual((lead.created_count, member.created_count), (3, 3))

		root = frappe.get_doc(GOAL, lead.root_goal)
		self.assertEqual((str(root.exp_start_date), str(root.exp_end_date)), ("2027-01-01", "2027-03-31"))
		self.assertEqual([row.parent_goal for row in root.parents], [self.parent.name])
		self.assertEqual(root.goal_code, "2027Q1-GOALS-TEST-MANAGER-BONUS")
		self.assertIn(doc.period_label, root.subject)
		self.assertEqual({row.code: row.value_number for row in root.parameters}, {"grade": 5, "share": 10})

		member_root = frappe.get_doc(GOAL, member.root_goal)
		self.assertEqual([row.parent_goal for row in member_root.parents], [lead.root_goal])
		self.assertEqual(member_root.goal_owner, OWNER)
		review = frappe.get_value(
			GOAL,
			{"goal_code": "2027Q1-GOALS-TEST-OWNER-REVIEW"},
			["exp_start_date", "exp_end_date"],
			as_dict=True,
		)
		self.assertEqual(
			(str(review.exp_start_date), str(review.exp_end_date)), ("2027-03-22", "2027-03-31"), "clamped"
		)

		self.assertEqual(campaigns.create(doc.name), {"rows": 0, "goals": 0, "skipped": 0, "errors": 0})
		self.assertEqual(len(goals_of(TEMPLATE)), 6)

	def test_duplicates_are_skipped_unless_allowed(self):
		campaigns.create(self._campaign().name)
		again = self._campaign()
		preview = campaigns.preview(again.name)
		self.assertTrue(all(row["existing"] for row in preview))
		self.assertEqual(campaigns.create(again.name)["skipped"], 1)
		again.reload()
		self.assertEqual([row.status for row in again.items], ["Skipped", "Error"])
		self.assertEqual(len(goals_of(TEMPLATE)), 6)

		allowed = self._campaign(allow_duplicates=1, code_prefix_pattern="DUP-{user}")
		self.assertEqual(campaigns.create(allowed.name)["rows"], 2)

	def test_failed_row_does_not_stop_the_others(self):
		make_template("_GT Inactive", is_active=0)
		doc = make_campaign(
			[
				{"goal_owner": MANAGER, "template": "_GT Inactive"},
				{"goal_owner": OWNER, "template": TEMPLATE},
				{"goal_owner": OWNER_B, "template": TEMPLATE, "parent_row": "R1"},
			]
		)
		warnings = {row["row_key"]: row["warnings"] for row in campaigns.preview(doc.name)}
		self.assertTrue(any("_GT Inactive" in text for text in warnings["R1"]))
		summary = campaigns.create(doc.name)
		self.assertEqual((summary["rows"], summary["errors"]), (1, 2))
		doc.reload()
		self.assertEqual([row.status for row in doc.items], ["Error", "Created", "Error"])
		self.assertFalse(goals_of("_GT Inactive"))
		self.assertEqual(doc.status, "Partially Created")

	def test_preview_warns_about_missing_provider_parameters(self):
		template = make_template("_GT Budget Bonus")
		template.items[1].update(
			{
				"progress_method": "Auto",
				"metric_source": "Provider",
				"metric_provider": "project_budget_profit",
			}
		)
		template.save(ignore_permissions=True)
		doc = make_campaign([{"goal_owner": OWNER, "template": "_GT Budget Bonus"}])
		warnings = campaigns.preview(doc.name)[0]["warnings"]
		self.assertTrue(any("projects" in text for text in warnings), warnings)

	def test_copy_to_next_period(self):
		doc = self._campaign()
		campaigns.create(doc.name)
		doc.reload()
		copy = frappe.get_doc(GOAL_CAMPAIGN, campaigns.copy_to_next_period(doc.name))
		self.assertEqual((copy.period_start, copy.period_end), (date(2027, 4, 1), date(2027, 6, 30)))
		self.assertEqual(copy.status, "Draft")
		self.assertNotEqual(copy.period_label, doc.period_label)
		self.assertIn(copy.period_label, copy.title)
		self.assertEqual([row.status for row in copy.items], ["Pending", "Pending"])
		self.assertEqual([row.root_goal for row in copy.items], [None, None])
		self.assertEqual([row.parent_row or None for row in copy.items], [None, "R1"])

	def test_owner_cannot_create(self):
		doc = self._campaign()
		with as_user(OWNER), self.assertRaises(frappe.PermissionError):
			campaigns.create(doc.name)


class TestTemplateEndDate(GoalTestCase):
	def test_items_follow_the_period_end(self):
		make_template()
		names = templates.create_goals(
			TEMPLATE, start_date="2027-02-01", end_date="2027-04-30", goal_owner=MANAGER, code_prefix="M"
		)
		dates = {
			row.goal_code: (str(row.exp_start_date), str(row.exp_end_date))
			for row in frappe.get_all(
				GOAL, filters={"name": ["in", names]}, fields=["goal_code", "exp_start_date", "exp_end_date"]
			)
		}
		self.assertEqual(dates["M-BONUS"], ("2027-02-01", "2027-04-30"))
		self.assertEqual(dates["M-SALES"], ("2027-02-01", "2027-04-30"))
		self.assertEqual(dates["M-REVIEW"], ("2027-04-22", "2027-04-30"))
		with self.assertRaises(frappe.ValidationError):
			templates.create_goals(
				TEMPLATE, start_date="2027-02-01", end_date="2027-03-31", goal_owner=MANAGER, code_prefix="N"
			)
