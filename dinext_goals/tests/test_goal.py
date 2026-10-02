import frappe

from dinext_goals import api
from dinext_goals.constants import (
	GOAL,
	GOAL_LOG,
	STATUS_ACTIVE,
	STATUS_CLOSED,
	STATUS_FOR_APPROVAL,
	STATUS_ON_HOLD,
)
from dinext_goals.goals import hierarchy, lifecycle
from dinext_goals.tests.utils import PLAIN, GoalTestCase, activate, make_goal, make_group, new_goal


class TestGoalController(GoalTestCase):
	def test_create_goal_with_required_fields(self):
		goal = make_goal("Leaf", current_value=25)
		self.assertEqual(goal.status, "Draft")
		self.assertEqual(goal.workflow_state or "Draft", "Draft")
		self.assertEqual(goal.progress, 25)

	def test_leaf_needs_metric_type(self):
		with self.assertRaises(frappe.ValidationError):
			make_goal("Leaf", metric_type=None)

	def test_end_before_start(self):
		with self.assertRaises(frappe.ValidationError):
			make_goal("Leaf", exp_start_date="2026-05-01", exp_end_date="2026-04-30")

	def test_negative_weight(self):
		with self.assertRaises(frappe.ValidationError):
			make_goal("Leaf", weight=-1)

	def test_goal_owner_must_hold_goal_role(self):
		with self.assertRaises(frappe.ValidationError):
			make_goal("Leaf", owner=PLAIN)

	def test_parent_must_be_group(self):
		leaf = make_goal("Leaf")
		with self.assertRaises(frappe.ValidationError):
			make_goal("Child", parents=[leaf.name])

	def test_cycle_is_rejected(self):
		root = make_group("Root")
		middle = make_group("Middle", parents=[root.name])
		bottom = make_group("Bottom", parents=[middle.name])
		root.append("parents", {"parent_goal": bottom.name})
		with self.assertRaises(frappe.ValidationError):
			root.save()

	def test_own_and_duplicate_parent(self):
		group = make_group("Group")
		group.append("parents", {"parent_goal": group.name})
		with self.assertRaises(frappe.ValidationError):
			group.save()
		other = make_group("Other")
		with self.assertRaises(frappe.ValidationError):
			make_goal("Twice", parents=[other.name, other.name])

	def test_several_parents(self):
		first = make_group("First")
		second = make_group("Second")
		shared = make_goal("Shared", parents=[first.name, second.name], current_value=40)
		self.assertEqual(sorted(hierarchy.get_parent_names(shared.name)), sorted([first.name, second.name]))
		self.assertEqual(self.reload(first.name).progress, 40)
		self.assertEqual(self.reload(second.name).progress, 40)

	def test_group_with_children_stays_group(self):
		group = make_group("Group")
		make_goal("Child", parents=[group.name])
		group.reload()
		group.is_group = 0
		group.metric_type = "Numeric"
		with self.assertRaises(frappe.ValidationError):
			group.save()

	def test_goal_code_unique_within_tree(self):
		root = make_group("Root")
		make_goal("A", parents=[root.name], goal_code="KPI")
		with self.assertRaises(frappe.ValidationError):
			make_goal("B", parents=[root.name], goal_code="KPI")
		make_goal("Other tree", goal_code="KPI")

	def test_edit_target_of_active_goal(self):
		goal = make_goal("Leaf")
		activate(goal.name)
		goal = self.reload(goal.name)
		goal.target = 200
		with self.assertRaises(frappe.ValidationError):
			goal.save()
		goal = self.reload(goal.name)
		goal.description = "Still editable"
		goal.current_value = 10
		goal.save()
		self.assertEqual(self.reload(goal.name).current_value, 10)

	def test_parents_locked_after_draft(self):
		group = make_group("Group")
		goal = make_goal("Leaf")
		activate(goal.name)
		goal = self.reload(goal.name)
		goal.append("parents", {"parent_goal": group.name})
		with self.assertRaises(frappe.ValidationError):
			goal.save()

	def test_status_follows_workflow_state(self):
		doc = new_goal("Unsaved")
		for state, status in (
			("Parent Approval", STATUS_FOR_APPROVAL),
			("Finance Approval", STATUS_FOR_APPROVAL),
		):
			doc.workflow_state = state
			lifecycle.sync_status(doc, None)
			self.assertEqual(doc.status, status)
		doc.workflow_state = "Approved"
		lifecycle.sync_status(doc, frappe._dict(status=STATUS_FOR_APPROVAL))
		self.assertEqual(doc.status, STATUS_ACTIVE)
		lifecycle.sync_status(doc, frappe._dict(status=STATUS_ON_HOLD))
		self.assertEqual(doc.status, STATUS_ON_HOLD)

	def test_close_an_active_goal(self):
		goal = make_goal("Leaf", exp_start_date="2025-01-01", exp_end_date="2025-12-31", current_value=10)
		activate(goal.name)
		frappe.db.set_value(GOAL, goal.name, "is_overdue", 1)
		with self.assertRaises(frappe.ValidationError):
			api.set_lifecycle_status(goal.name, "resume")
		self.assertEqual(api.set_lifecycle_status(goal.name, "hold")["status"], STATUS_ON_HOLD)
		self.assertEqual(api.set_lifecycle_status(goal.name, "resume")["status"], STATUS_ACTIVE)
		self.assertEqual(api.set_lifecycle_status(goal.name, "close")["status"], STATUS_CLOSED)
		closed = self.reload(goal.name)
		self.assertEqual(closed.is_overdue, 0)
		closed.current_value = 99
		closed.save()
		self.assertEqual(self.reload(goal.name).progress, 10, "closed goals keep their final values")

	def test_lifecycle_from_draft_is_rejected(self):
		goal = make_goal("Leaf")
		with self.assertRaises(frappe.ValidationError):
			api.set_lifecycle_status(goal.name, "close")

	def test_manual_change_is_logged(self):
		goal = make_goal("Leaf")
		goal.current_value = 30
		goal.save()
		logs = frappe.get_all(
			GOAL_LOG, filters={"goal": goal.name}, fields=["source", "current_value"], order_by="creation asc"
		)
		self.assertEqual(logs[-1].source, "Manual")
		self.assertEqual(logs[-1].current_value, 30)

	def test_delete_refreshes_parent_and_logs(self):
		group = make_group("Group")
		keep = make_goal("Keep", parents=[group.name], current_value=100)
		drop = make_goal("Drop", parents=[group.name], current_value=0)
		self.assertEqual(self.reload(group.name).progress, 50)
		frappe.delete_doc(GOAL, drop.name)
		self.assertFalse(frappe.db.exists(GOAL_LOG, {"goal": drop.name}))
		self.assertEqual(self.reload(group.name).progress, 100)
		self.assertTrue(frappe.db.exists(GOAL, keep.name))
