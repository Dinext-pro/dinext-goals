"""Many-to-many goal hierarchy stored in the ``Goal Parent`` child table."""

from __future__ import annotations

from collections.abc import Iterable

import frappe
from frappe import _

from dinext_goals.constants import GOAL, GOAL_PARENT


def _unique(values: Iterable[str | None]) -> list[str]:
	seen: set[str] = set()
	result = []
	for value in values:
		if value and value not in seen:
			seen.add(value)
			result.append(value)
	return result


def doc_parent_names(doc) -> list[str]:
	return _unique(row.parent_goal for row in (doc.get("parents") or []))


def get_parents_of(goals: Iterable[str]) -> dict[str, list[str]]:
	goals = _unique(goals)
	result: dict[str, list[str]] = {goal: [] for goal in goals}
	if not goals:
		return result
	rows = frappe.get_all(
		GOAL_PARENT,
		filters={"parent": ["in", goals], "parenttype": GOAL, "parentfield": "parents"},
		fields=["parent", "parent_goal"],
		order_by="idx asc",
	)
	for row in rows:
		if row.parent_goal not in result[row.parent]:
			result[row.parent].append(row.parent_goal)
	return result


def get_children_of(goals: Iterable[str]) -> dict[str, list[str]]:
	goals = _unique(goals)
	result: dict[str, list[str]] = {goal: [] for goal in goals}
	if not goals:
		return result
	rows = frappe.get_all(
		GOAL_PARENT,
		filters={"parent_goal": ["in", goals], "parenttype": GOAL, "parentfield": "parents"},
		fields=["parent", "parent_goal"],
		order_by="parent asc",
	)
	for row in rows:
		if row.parent not in result[row.parent_goal]:
			result[row.parent_goal].append(row.parent)
	return result


def get_parent_names(goal: str) -> list[str]:
	return get_parents_of([goal])[goal]


def get_child_names(goal: str) -> list[str]:
	return get_children_of([goal])[goal]


def ancestor_levels(goal: str | None, direct_parents: Iterable[str]) -> list[list[str]]:
	"""Ancestors grouped by distance; a goal reachable by several paths keeps its shortest distance."""
	seen: set[str] = {goal} if goal else set()
	frontier = [name for name in _unique(direct_parents) if name not in seen]
	levels: list[list[str]] = []
	while frontier:
		levels.append(frontier)
		seen.update(frontier)
		parents = get_parents_of(frontier)
		frontier = _unique(p for name in frontier for p in parents[name] if p not in seen)
	return levels


def doc_ancestor_levels(doc) -> list[list[str]]:
	return ancestor_levels(None if doc.is_new() else doc.name, doc_parent_names(doc))


def doc_ancestors(doc) -> list[str]:
	return [name for level in doc_ancestor_levels(doc) for name in level]


def get_ancestors(goal: str) -> list[str]:
	return [name for level in ancestor_levels(goal, get_parent_names(goal)) for name in level]


def get_descendants(goal: str) -> list[str]:
	seen = {goal}
	result: list[str] = []
	frontier = [goal]
	while frontier:
		children = get_children_of(frontier)
		frontier = _unique(c for name in frontier for c in children[name] if c not in seen)
		seen.update(frontier)
		result.extend(frontier)
	return result


def get_roots(goal: str | None, direct_parents: Iterable[str]) -> list[str]:
	direct_parents = _unique(direct_parents)
	if not direct_parents:
		return [goal] if goal else []
	candidates = [name for level in ancestor_levels(goal, direct_parents) for name in level]
	parents = get_parents_of(candidates)
	return [name for name in candidates if not parents[name]]


def get_tree_members(goal: str | None, direct_parents: Iterable[str]) -> list[str]:
	members: list[str] = []
	for root in get_roots(goal, direct_parents):
		members.append(root)
		members.extend(get_descendants(root))
	return _unique(members)


def validate_parents(doc) -> None:
	names = [row.parent_goal for row in (doc.get("parents") or []) if row.parent_goal]
	duplicates = sorted({name for name in names if names.count(name) > 1})
	if duplicates:
		frappe.throw(_("Parent goal {0} is listed more than once").format(", ".join(duplicates)))
	if not doc.is_new() and doc.name in names:
		frappe.throw(_("A goal cannot be its own parent"))

	if names:
		groups = {
			row.name: row
			for row in frappe.get_all(
				GOAL, filters={"name": ["in", names]}, fields=["name", "is_group", "subject"]
			)
		}
		for name in names:
			if name not in groups:
				frappe.throw(_("Parent goal {0} does not exist").format(name))
			if not groups[name].is_group:
				frappe.throw(
					_("Parent goal {0} must be a group goal").format(frappe.bold(groups[name].subject))
				)

	if not doc.is_new():
		_assert_not_cycle(doc.name, names)
		if not doc.is_group and get_child_names(doc.name):
			frappe.throw(_("A goal with child goals must stay a group goal"))


def _assert_not_cycle(goal: str, direct_parents: list[str]) -> None:
	seen: set[str] = set()
	frontier = _unique(direct_parents)
	while frontier:
		if goal in frontier:
			frappe.throw(_("Circular reference: goal {0} would become its own ancestor").format(goal))
		seen.update(frontier)
		parents = get_parents_of(frontier)
		frontier = _unique(p for name in frontier for p in parents[name] if p not in seen)


def validate_goal_code(doc) -> None:
	if not doc.goal_code:
		return
	members = [
		name
		for name in get_tree_members(None if doc.is_new() else doc.name, doc_parent_names(doc))
		if name != doc.name
	]
	if not members:
		return
	clash = frappe.get_all(
		GOAL, filters={"name": ["in", members], "goal_code": doc.goal_code}, pluck="name", limit=1
	)
	if clash:
		frappe.throw(
			_("Goal code {0} is already used in this goal tree by {1}").format(doc.goal_code, clash[0])
		)


def topological_order(goals: Iterable[str]) -> list[str]:
	"""Order goals children-first within the given set."""
	goals = _unique(goals)
	members = set(goals)
	children = get_children_of(goals)
	ordered: list[str] = []
	state: dict[str, int] = {}

	def visit(name: str) -> None:
		stack = [(name, iter(children.get(name, [])))]
		state[name] = 1
		while stack:
			current, iterator = stack[-1]
			child = next(iterator, None)
			if child is None:
				stack.pop()
				state[current] = 2
				ordered.append(current)
				continue
			if child in members and state.get(child) is None:
				state[child] = 1
				stack.append((child, iter(children.get(child, []))))

	for goal in goals:
		if state.get(goal) is None:
			visit(goal)
	return ordered
