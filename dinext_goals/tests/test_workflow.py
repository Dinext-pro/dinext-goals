import json
from unittest.mock import patch

import frappe
from dinext_common.workflow_approval import api as workflow_api

from dinext_goals import api as goals_api
from dinext_goals.constants import GOAL, ROLE_FINANCE, STATUS_ACTIVE, STATUS_DRAFT, STATUS_FOR_APPROVAL
from dinext_goals.goals import approvers
from dinext_goals.progress import engine
from dinext_goals.tests.utils import (
	DIRECTOR,
	FINANCE,
	MANAGER,
	OWNER,
	GoalTestCase,
	as_user,
	make_goal,
	make_group,
	new_goal,
)


def act(user, goal, action, comment=None):
	with as_user(user):
		return workflow_api.apply_workflow(frappe.get_doc(GOAL, goal).as_dict(), action, comment=comment)


def open_approvers(goal):
	return sorted(
		frappe.get_all(
			"Workflow Task",
			filters={
				"reference_doctype": GOAL,
				"reference_name": goal,
				"status": "Working",
				"workflow_state": "Parent Approval",
			},
			pluck="approver",
		)
	)


def state(goal):
	return frappe.db.get_value(GOAL, goal, ["workflow_state", "status"])


class TestGoalApproval(GoalTestCase):
	def _tree(self, **leaf_values):
		root = make_group("Director goal", owner=DIRECTOR)
		middle = make_group("Manager goal", owner=MANAGER, parents=[root.name])
		leaf = make_goal("Specialist goal", owner=OWNER, parents=[middle.name], **leaf_values)
		return root, middle, leaf

	def test_two_level_approval(self):
		_root, _middle, leaf = self._tree()
		self.assertEqual(leaf.approver_users.split("\n"), sorted([DIRECTOR, MANAGER]))
		act(OWNER, leaf.name, "Submit for Approval")
		self.assertEqual(state(leaf.name), ("Parent Approval", STATUS_FOR_APPROVAL))
		self.assertEqual(open_approvers(leaf.name), sorted([DIRECTOR, MANAGER]))
		act(MANAGER, leaf.name, "Approve")
		self.assertEqual(state(leaf.name), ("Parent Approval", STATUS_FOR_APPROVAL))
		act(DIRECTOR, leaf.name, "Approve")
		self.assertEqual(state(leaf.name), ("Finance Approval", STATUS_FOR_APPROVAL))
		act(FINANCE, leaf.name, "Approve")
		self.assertEqual(state(leaf.name), ("Approved", STATUS_ACTIVE))

	def test_only_the_goal_owner_submits(self):
		_root, _middle, leaf = self._tree()
		with self.assertRaises(frappe.ValidationError):
			act(MANAGER, leaf.name, "Submit for Approval")
		self.assertEqual(state(leaf.name), ("Draft", STATUS_DRAFT))

	def test_root_goal(self):
		root = make_goal("Root goal", owner=OWNER)
		users = root.approver_users.split("\n")
		self.assertIn(MANAGER, users)
		self.assertNotIn(DIRECTOR, users)
		self.assertNotIn(OWNER, users)
		act(OWNER, root.name, "Submit for Approval")
		self.assertIn(MANAGER, open_approvers(root.name))

	def test_creator_does_not_approve(self):
		with as_user(MANAGER):
			root = make_goal("Created by the manager", owner=OWNER)
		self.assertNotIn(MANAGER, (root.approver_users or "").split("\n"))

	def test_rejection(self):
		_root, _middle, leaf = self._tree()
		act(OWNER, leaf.name, "Submit for Approval")
		with self.assertRaises((frappe.ValidationError, ValueError)):
			act(MANAGER, leaf.name, "Reject")
		act(MANAGER, leaf.name, "Reject", comment="Target is too low")
		self.assertEqual(state(leaf.name), ("Draft", STATUS_DRAFT))
		self.assertTrue(
			frappe.db.exists(
				"Workflow Task",
				{"reference_doctype": GOAL, "reference_name": leaf.name, "vote_comment": "Target is too low"},
			)
		)

	def test_nobody_can_approve(self):
		doc = new_goal("Lonely")
		doc.workflow_state = "Parent Approval"
		doc.approver_users = ""
		with self.assertRaises(frappe.ValidationError) as raised:
			approvers.validate_submission(doc, None)
		self.assertIn("Goal Approver", str(raised.exception))
		doc.approver_users = MANAGER
		real = approvers.users_with_role
		with patch.object(
			approvers, "users_with_role", lambda role: set() if role == ROLE_FINANCE else real(role)
		):
			with self.assertRaises(frappe.ValidationError) as raised:
				approvers.validate_submission(doc, None)
		self.assertIn("Goal Finance Approver", str(raised.exception))

	def test_recalculate_during_approval(self):
		make_goal("WF SRC 1")
		_root, _middle, leaf = self._tree(
			progress_method="Auto",
			metric_source="Linked Documents",
			linked_document_type=GOAL,
			aggregation="Count",
			linked_document_filter=json.dumps({"subject": ["like", "WF SRC %"]}),
			target=10,
		)
		self.assertEqual(leaf.current_value, 1)
		act(OWNER, leaf.name, "Submit for Approval")
		tasks = sorted(
			frappe.get_all(
				"Workflow Task",
				filters={"reference_doctype": GOAL, "reference_name": leaf.name, "status": "Working"},
				pluck="name",
			)
		)
		make_goal("WF SRC 2")
		engine.recalculate(leaf.name)
		self.assertEqual(frappe.db.get_value(GOAL, leaf.name, "current_value"), 2)
		make_goal("WF SRC 3")
		with as_user(OWNER):
			goals_api.recalculate(leaf.name)
		self.assertEqual(frappe.db.get_value(GOAL, leaf.name, "current_value"), 3)
		self.assertEqual(
			sorted(
				frappe.get_all(
					"Workflow Task",
					filters={"reference_doctype": GOAL, "reference_name": leaf.name, "status": "Working"},
					pluck="name",
				)
			),
			tasks,
		)
		act(MANAGER, leaf.name, "Approve")
		act(DIRECTOR, leaf.name, "Approve")
		self.assertEqual(state(leaf.name)[0], "Finance Approval")
