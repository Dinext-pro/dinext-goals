import frappe
from frappe.desk.notifications import get_open_count

from dinext_goals.constants import GOAL
from dinext_goals.tests.utils import GoalTestCase, make_goal, make_group, make_project, param

FIRST = "_GT-GOALS-PRJ-1"
SECOND = "_GT-GOALS-PRJ-2"
THIRD = "_GT-GOALS-PRJ-3"


def projects(name: str) -> list[str]:
	return [row.project for row in frappe.get_doc(GOAL, name).goal_projects]


class TestProjectGoals(GoalTestCase):
	def setUp(self):
		super().setUp()
		for project in (FIRST, SECOND, THIRD):
			make_project(project)
		self.group = make_group(
			"Project group", params=[param("projects", "Link List", [FIRST, SECOND], link_doctype="Project")]
		)
		self.child = make_goal("Project child", parents=[self.group.name])

	def test_own_and_inherited_projects(self):
		self.assertEqual(projects(self.group.name), [FIRST, SECOND])
		self.assertEqual(projects(self.child.name), [FIRST, SECOND])
		own = make_goal(
			"Own project",
			parents=[self.group.name],
			params=[param("project", "Link", THIRD, link_doctype="Project", inherit=0)],
		)
		self.assertEqual(projects(own.name), [FIRST, SECOND, THIRD])
		other = make_goal(
			"Not a project",
			params=[
				param("projects", "Link List", [FIRST], link_doctype="Project", inherit=0),
				param("users", "Link List", ["Administrator"], link_doctype="User"),
			],
		)
		self.assertEqual(projects(other.name), [FIRST])
		other = make_goal(
			"No projects", params=[param("users", "Link List", ["Administrator"], link_doctype="User")]
		)
		self.assertEqual(projects(other.name), [])

	def test_ancestor_parameter_change_updates_descendants(self):
		group = frappe.get_doc(GOAL, self.group.name)
		group.parameters[0].value_list = THIRD
		group.save()
		self.assertEqual(projects(self.child.name), [THIRD])
		self.assertEqual(frappe.get_all(GOAL, filters={"project": FIRST}, pluck="name"), [])

	def test_parent_change_updates_descendants(self):
		middle = make_group("Middle", parents=[self.group.name])
		leaf = make_goal("Leaf", parents=[middle.name])
		self.assertEqual(projects(leaf.name), [FIRST, SECOND])
		middle = frappe.get_doc(GOAL, middle.name)
		middle.parents = []
		middle.save()
		self.assertEqual(projects(middle.name), [])
		self.assertEqual(projects(leaf.name), [])

	def test_project_connections(self):
		data = frappe.get_meta("Project").get_dashboard_data()
		self.assertIn(GOAL, [item for group in data.transactions for item in group["items"]])
		self.assertEqual(data.non_standard_fieldnames[GOAL], "project")
		counts = get_open_count("Project", FIRST, [GOAL])["count"]["external_links_found"]
		self.assertEqual(counts[0]["count"], 2)
		self.assertEqual(
			sorted(frappe.get_all(GOAL, filters={"project": SECOND}, pluck="name")),
			sorted([self.group.name, self.child.name]),
		)
