import frappe

from dinext_goals.constants import GOAL
from dinext_goals.parameters import sync_goal_projects


def execute():
	sync_goal_projects(frappe.get_all(GOAL, pluck="name"))
