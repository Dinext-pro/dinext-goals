import unittest
from types import SimpleNamespace as Row


class TestRejectedGoalStatus(unittest.TestCase):
    def test_rejected_workflow_state_is_not_a_draft(self):
        from dinext_goals.goals.lifecycle import sync_status
        goal = Row(workflow_state='Rejected', status='For Approval', flags=Row(lifecycle_status=None))
        sync_status(goal, None)
        self.assertEqual(goal.status, 'Rejected')
