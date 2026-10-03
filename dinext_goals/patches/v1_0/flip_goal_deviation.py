"""Deviation became actual minus planned progress; group achievement became the weighted child achievement."""

import frappe

from dinext_goals.constants import GOAL
from dinext_goals.progress import engine


def execute():
	goal = frappe.qb.DocType(GOAL)
	frappe.qb.update(goal).set(goal.deviation, -goal.deviation).run()
	engine.recalculate_active()
