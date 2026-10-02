# Copyright (c) 2026, Dinext and Contributors
# See license.txt

from frappe.tests.utils import FrappeTestCase

import dinext_goals


class TestDinextGoalsScaffold(FrappeTestCase):
	def test_version_is_set(self):
		self.assertTrue(dinext_goals.__version__)
