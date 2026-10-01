# Copyright (c) 2026, Dinext and Contributors
# See license.txt

import dinext_goals
from frappe.tests.utils import FrappeTestCase


class TestDinextGoalsScaffold(FrappeTestCase):
	def test_version_is_set(self):
		self.assertTrue(dinext_goals.__version__)
