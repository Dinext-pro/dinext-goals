import frappe

from dinext_goals import api
from dinext_goals.constants import GOAL, GOAL_LOG
from dinext_goals.tests.utils import (
	DIRECTOR,
	FINANCE,
	MANAGER,
	OUTSIDER,
	OWNER,
	OWNER_B,
	PLAIN,
	GoalTestCase,
	as_user,
	make_goal,
	make_group,
	new_goal,
)


def can(user, ptype, doctype, name=None):
	return bool(frappe.has_permission(doctype, ptype, doc=name, user=user))


class TestGoalPermissions(GoalTestCase):
	def setUp(self):
		super().setUp()
		self.root = make_group("Director goal", owner=DIRECTOR)
		self.child = make_goal("Owner goal", owner=OWNER, parents=[self.root.name])

	def test_owner_of_a_parent_edits_a_child(self):
		self.assertTrue(can(DIRECTOR, "write", GOAL, self.child.name))
		with as_user(DIRECTOR):
			doc = frappe.get_doc(GOAL, self.child.name)
			doc.description = "Edited by the director"
			doc.save()
		self.assertEqual(frappe.db.get_value(GOAL, self.child.name, "description"), "Edited by the director")

	def test_unrelated_owner_edits_a_goal(self):
		self.assertFalse(can(OUTSIDER, "read", GOAL, self.child.name))
		self.assertFalse(can(OUTSIDER, "write", GOAL, self.child.name))
		doc = frappe.get_doc(GOAL, self.child.name)
		doc.description = "Not mine"
		with as_user(OUTSIDER):
			with self.assertRaises(frappe.PermissionError):
				doc.save()
			loaded = frappe.get_doc(GOAL, self.child.name)
			with self.assertRaises(frappe.PermissionError):
				loaded.check_permission("read")
			with self.assertRaises(frappe.PermissionError):
				api.recalculate(self.child.name)
			with self.assertRaises(frappe.PermissionError):
				api.set_lifecycle_status(self.child.name, "close")

	def test_owner_reads_own_tree_only(self):
		owned = make_group("Owner group", owner=OWNER)
		grandchild = make_goal("Nested", owner=OUTSIDER, parents=[owned.name])
		foreign = make_goal("Foreign branch", owner=OUTSIDER)
		self.assertTrue(can(OWNER, "read", GOAL, self.child.name))
		self.assertTrue(can(OWNER, "read", GOAL, owned.name))
		self.assertTrue(can(OWNER, "read", GOAL, grandchild.name))
		self.assertTrue(can(OWNER, "write", GOAL, grandchild.name))
		self.assertFalse(can(OWNER, "read", GOAL, self.root.name))
		self.assertFalse(can(OWNER, "read", GOAL, foreign.name))
		self.assertTrue(can(MANAGER, "read", GOAL, foreign.name))
		self.assertTrue(can(FINANCE, "read", GOAL, foreign.name))
		self.assertTrue(can(DIRECTOR, "read", GOAL, foreign.name))
		with as_user(OWNER):
			names = set(frappe.get_list(GOAL, pluck="name", limit_page_length=0))
		self.assertIn(self.child.name, names)
		self.assertIn(owned.name, names)
		self.assertIn(grandchild.name, names)
		self.assertNotIn(self.root.name, names)
		self.assertNotIn(foreign.name, names)

	def test_creator_reads_the_goal_but_not_its_descendants(self):
		with as_user(OWNER_B):
			created = new_goal("Created for someone else", owner=OWNER, is_group=1).insert()
		descendant = make_goal("Under a created goal", owner=OUTSIDER, parents=[created.name])
		self.assertTrue(can(OWNER_B, "read", GOAL, created.name))
		self.assertTrue(can(OWNER_B, "write", GOAL, created.name))
		self.assertFalse(can(OWNER_B, "read", GOAL, descendant.name))
		with as_user(OWNER_B):
			names = set(frappe.get_list(GOAL, pluck="name", limit_page_length=0))
		self.assertIn(created.name, names)
		self.assertNotIn(descendant.name, names)

	def test_owner_creator_and_manager_edit(self):
		self.assertTrue(can(OWNER, "write", GOAL, self.child.name))
		self.assertFalse(can(OWNER, "write", GOAL, self.root.name))
		self.assertTrue(can(MANAGER, "write", GOAL, self.root.name))
		with as_user(OWNER_B):
			created = new_goal("Created for someone else", owner=OWNER).insert()
		self.assertTrue(can(OWNER_B, "write", GOAL, created.name))

	def test_owner_creates_goals(self):
		with as_user(OWNER):
			goal = new_goal("Own goal", owner=OWNER).insert()
		self.assertEqual(goal.owner, OWNER)
		with as_user(PLAIN):
			with self.assertRaises(frappe.PermissionError):
				new_goal("Not allowed", owner=OWNER).insert()

	def test_user_without_goal_roles(self):
		self.assertFalse(can(PLAIN, "read", GOAL, self.child.name))
		self.assertFalse(can(PLAIN, "create", GOAL))

	def test_goal_log_follows_goal_read(self):
		log = frappe.get_all(GOAL_LOG, filters={"goal": self.child.name}, pluck="name", limit=1)[0]
		self.assertTrue(can(OWNER, "read", GOAL_LOG, log))
		self.assertFalse(can(OUTSIDER, "read", GOAL_LOG, log))
		self.assertFalse(can(PLAIN, "read", GOAL_LOG, log))
		self.assertFalse(can(OUTSIDER, "write", GOAL_LOG, log))
		with as_user(OUTSIDER):
			self.assertEqual(frappe.get_list(GOAL_LOG, filters={"goal": self.child.name}, pluck="name"), [])
		with as_user(OWNER):
			self.assertIn(log, frappe.get_list(GOAL_LOG, filters={"goal": self.child.name}, pluck="name"))
