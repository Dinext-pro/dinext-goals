"""Goal campaigns: goals from templates for a whole team and one period."""

from __future__ import annotations

import calendar
import json
import re
from datetime import date
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, date_diff, formatdate, getdate, strip_html, today

from dinext_goals import parameters, templates
from dinext_goals.constants import GOAL, GOAL_CAMPAIGN, GOAL_TEMPLATE, STATUS_CANCELLED, STATUS_CLOSED
from dinext_goals.providers import get_registry, list_providers

PERIOD_MONTHS = {"Month": 1, "Quarter": 3, "Half-Year": 6, "Year": 12}
CUSTOM = "Custom"
ROW_PENDING, ROW_CREATED, ROW_SKIPPED, ROW_ERROR = "Pending", "Created", "Skipped", "Error"
ENQUEUE_THRESHOLD = 30
SAVEPOINT = "goal_campaign_row"
REALTIME_EVENT = "dinext_goals_campaign_done"


# ---------------------------------------------------------------- period


def period_start_of(period_type: str, day) -> date:
	day = getdate(day)
	if period_type == "Month":
		return day.replace(day=1)
	if period_type == "Quarter":
		return date(day.year, (day.month - 1) // 3 * 3 + 1, 1)
	if period_type == "Half-Year":
		return date(day.year, 1 if day.month <= 6 else 7, 1)
	if period_type == "Year":
		return date(day.year, 1, 1)
	return day


def period_bounds(period_type: str, start, end=None) -> tuple[date, date]:
	start = period_start_of(period_type, start)
	if period_type in PERIOD_MONTHS:
		return start, getdate(add_days(add_months(start, PERIOD_MONTHS[period_type]), -1))
	end = getdate(end) if end else start
	if end < start:
		frappe.throw(
			_("Period End {0} is before Period Start {1}").format(formatdate(end), formatdate(start))
		)
	return start, end


def next_period(period_type: str, start, end=None) -> tuple[date, date]:
	start, end = period_bounds(period_type, start, end)
	if period_type in PERIOD_MONTHS:
		return period_bounds(period_type, add_months(start, PERIOD_MONTHS[period_type]))
	following = getdate(add_days(end, 1))
	return following, getdate(add_days(following, date_diff(end, start)))


def default_start(period_type: str, day=None) -> date:
	"""The start of the period following the one of ``day`` (today by default)."""
	current = period_start_of(period_type, day or today())
	if period_type in PERIOD_MONTHS:
		return getdate(add_months(current, PERIOD_MONTHS[period_type]))
	return current


def period_code(period_type: str, start, end) -> str:
	start = getdate(start)
	if period_type == "Month":
		return f"{start.year}-{start.month:02d}"
	if period_type == "Quarter":
		return f"{start.year}Q{(start.month - 1) // 3 + 1}"
	if period_type == "Half-Year":
		return f"{start.year}H{1 if start.month <= 6 else 2}"
	if period_type == "Year":
		return str(start.year)
	return f"{start:%Y%m%d}-{getdate(end):%Y%m%d}"


def period_label(period_type: str, start, end) -> str:
	start = getdate(start)
	if period_type == "Month":
		return f"{_(calendar.month_name[start.month])} {start.year}"
	if period_type == "Quarter":
		return _("Q{0} {1}").format((start.month - 1) // 3 + 1, start.year)
	if period_type == "Half-Year":
		return _("H{0} {1}").format(1 if start.month <= 6 else 2, start.year)
	if period_type == "Year":
		return str(start.year)
	return f"{formatdate(start)} – {formatdate(end)}"


@frappe.whitelist()
def period_info(period_type: str, period_start: str | None = None, period_end: str | None = None) -> dict:
	start, end = period_bounds(period_type, period_start or default_start(period_type), period_end)
	return {
		"period_start": str(start),
		"period_end": str(end),
		"period_label": period_label(period_type, start, end),
		"period_code": period_code(period_type, start, end),
	}


# ---------------------------------------------------------------- validation


def load_values(row) -> dict:
	value = row.get("parameter_values")
	if not value:
		return {}
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except ValueError:
			frappe.throw(_("Row {0}: parameter values are not valid JSON").format(row.idx))
	return value if isinstance(value, dict) else {}


def _blank(value: Any) -> bool:
	return value is None or value == "" or value == []


def _display_value(param: dict, value: Any) -> str:
	if isinstance(value, list):
		return ", ".join(str(item) for item in value)
	if param.get("param_type") == "Percent":
		return f"{value}%"
	if param.get("param_type") == "Check":
		return _("Yes") if cint(value) else _("No")
	return str(value)


def parameter_summary(row, asked: list[dict]) -> str:
	values = load_values(row)
	by_code = {param["code"]: param for param in asked}
	parts = []
	for code, value in values.items():
		if _blank(value):
			continue
		param = by_code.get(code, {"code": code})
		parts.append(f"{_(param.get('label') or code)}: {_display_value(param, value)}")
	return "; ".join(parts)


def _row_number(key: str | None) -> int:
	match = re.fullmatch(r"R(\d+)", key or "")
	return int(match.group(1)) if match else 0


def ordered_rows(doc) -> list:
	"""Rows with every parent row before its children; a cycle raises."""
	by_key = {row.row_key: row for row in doc.get("items") or []}
	order, state = [], {}

	def visit(row, path):
		mark = state.get(row.row_key)
		if mark == "done":
			return
		if mark == "visiting":
			frappe.throw(_("Parent rows form a cycle: {0}").format(" → ".join([*path, row.row_key])))
		state[row.row_key] = "visiting"
		if row.parent_row:
			visit(by_key[row.parent_row], [*path, row.row_key])
		state[row.row_key] = "done"
		order.append(row)

	for row in doc.get("items") or []:
		visit(row, [])
	return order


def campaign_status(doc) -> str:
	statuses = {row.status or ROW_PENDING for row in doc.get("items") or []}
	if ROW_CREATED in statuses and statuses <= {ROW_CREATED, ROW_SKIPPED}:
		return "Created"
	if ROW_CREATED in statuses:
		return "Partially Created"
	return "Draft"


def validate_campaign(doc) -> None:
	start, end = period_bounds(
		doc.period_type, doc.period_start or default_start(doc.period_type), doc.period_end
	)
	doc.period_start, doc.period_end = start, end
	doc.period_label = period_label(doc.period_type, start, end)
	if not doc.title:
		doc.title = _("Goals for {0}").format(doc.period_label)

	rows = doc.get("items") or []
	used = {row.row_key for row in rows if row.row_key}
	if len(used) != len([row for row in rows if row.row_key]):
		frappe.throw(_("Row keys must be unique"))
	last = max([_row_number(key) for key in used] or [0])
	for row in rows:
		if not row.row_key:
			last += 1
			row.row_key = f"R{last}"
	keys = {row.row_key for row in rows}
	asked_by_template: dict[str, list[dict]] = {}
	for row in rows:
		if row.parent_row and row.parent_row not in keys:
			frappe.throw(_("Row {0}: parent row {1} does not exist").format(row.row_key, row.parent_row))
		if row.parent_row == row.row_key:
			frappe.throw(_("Row {0} cannot be its own parent").format(row.row_key))
		if row.parent_row and row.parent_goal:
			row.parent_goal = None
		values = load_values(row)
		row.parameter_values = json.dumps(values, ensure_ascii=False, default=str) if values else None
		if row.template not in asked_by_template:
			asked_by_template[row.template] = (
				templates.ask_on_create_fields(row.template)
				if row.template and frappe.db.exists(GOAL_TEMPLATE, row.template)
				else []
			)
		row.parameter_summary = parameter_summary(row, asked_by_template[row.template])
		row.status = row.status or ROW_PENDING
	ordered_rows(doc)
	doc.status = campaign_status(doc)


# ---------------------------------------------------------------- rows


def _login(user: str) -> str:
	return re.sub(r"[^A-Z0-9]+", "-", (user or "").split("@")[0].upper()).strip("-")


def _fill(pattern: str, values: dict[str, str]) -> str:
	result = pattern or ""
	for key, value in values.items():
		result = result.replace("{" + key + "}", value or "")
	return result.strip()


def row_code_prefix(doc, row) -> str | None:
	if row.code_prefix:
		return row.code_prefix.strip()
	code = period_code(doc.period_type, doc.period_start, doc.period_end)
	prefix = _fill(
		doc.code_prefix_pattern or "", {"period": code, "user": _login(row.goal_owner), "n": str(row.idx)}
	)
	return prefix.strip("-") or None


def row_subject_suffix(doc, row) -> str | None:
	if row.subject_suffix:
		return row.subject_suffix.strip()
	full_name = frappe.db.get_value("User", row.goal_owner, "full_name") or row.goal_owner
	suffix = _fill(
		doc.subject_suffix_pattern or "",
		{"period": doc.period_label or "", "full_name": full_name, "n": str(row.idx)},
	)
	return suffix or None


def _root_items(template) -> list:
	return [item for item in templates.ordered_items(template) if not item.parent_key]


def existing_goals(doc, row, template) -> list[str]:
	"""Root goals of the template owned by the row owner and starting in the campaign period."""
	roots = _root_items(template)
	if not roots:
		return []
	filters = {
		"goal_template": template.name,
		"goal_owner": row.goal_owner,
		"exp_start_date": ["between", [doc.period_start, doc.period_end]],
		"status": ["!=", STATUS_CANCELLED],
	}
	root = roots[0]
	if root.goal_code:
		filters["goal_code"] = ["like", f"%{root.goal_code}"]
	else:
		filters["subject"] = ["like", f"{root.subject}%"]
	return frappe.get_all(GOAL, filters=filters, pluck="name", order_by="creation asc")


def _created_codes(template, values: dict) -> set[str]:
	codes = set()
	for param in template.get("template_parameters") or []:
		if cint(param.ask_on_create):
			if _blank(values.get(param.code)) and not param.get(parameters.value_field(param.param_type)):
				continue
		codes.add(param.code)
	return codes


def _provider_requirements(template) -> dict[str, list[str]]:
	"""Required parameter codes of the providers used by the template items, by provider label."""
	registry = get_registry()
	providers = {provider["key"]: provider for provider in list_providers()}
	needed: dict[str, list[str]] = {}
	for item in template.get("items") or []:
		keys = []
		if item.metric_source == "Provider" and item.metric_provider:
			keys.append(item.metric_provider)
		if item.target_source == "Provider":
			keys.append(item.target_provider or item.metric_provider)
		for key in keys:
			if key not in registry or key not in providers:
				continue
			provider = providers[key]
			required = [param["code"] for param in provider.get("params") or [] if param.get("required")]
			if required:
				needed.setdefault(provider["label"], [])
				needed[provider["label"]] += [
					code for code in required if code not in needed[provider["label"]]
				]
	return needed


def _row_parent(doc, row) -> str | None:
	return None if row.parent_row else (row.parent_goal or doc.default_parent_goal or None)


def preview_rows(doc) -> list[dict]:
	by_key = {row.row_key: row for row in doc.get("items") or []}
	cache: dict[str, Any] = {}
	parent_codes: dict[str, set[str]] = {}
	pairs: dict[tuple[str, str], int] = {}
	for row in doc.get("items") or []:
		pairs[(row.goal_owner, row.template)] = pairs.get((row.goal_owner, row.template), 0) + 1

	def template_of(name):
		if name not in cache:
			cache[name] = (
				frappe.get_doc(GOAL_TEMPLATE, name) if frappe.db.exists(GOAL_TEMPLATE, name) else None
			)
		return cache[name]

	def goal_codes(goal):
		if goal not in parent_codes:
			parent_codes[goal] = set(parameters.resolve_for_name(goal)) if goal else set()
		return parent_codes[goal]

	def available_codes(row, seen=()):
		template = template_of(row.template)
		codes = _created_codes(template, load_values(row)) if template else set()
		if row.parent_row and row.parent_row in by_key and row.parent_row not in seen:
			return codes | available_codes(by_key[row.parent_row], (*seen, row.row_key))
		parent = _row_parent(doc, row)
		return codes | (goal_codes(parent) if parent and frappe.db.exists(GOAL, parent) else set())

	result = []
	for row in ordered_rows(doc):
		template = template_of(row.template)
		warnings = []
		info = {
			"row_key": row.row_key,
			"idx": row.idx,
			"goal_owner": row.goal_owner,
			"owner_name": frappe.db.get_value("User", row.goal_owner, "full_name") or row.goal_owner,
			"template": row.template,
			"status": row.status or ROW_PENDING,
			"root_goal": row.root_goal,
			"parent_row": row.parent_row,
			"parent_goal": _row_parent(doc, row),
			"code_prefix": row_code_prefix(doc, row),
			"period_start": str(doc.period_start),
			"period_end": str(doc.period_end),
			"warnings": warnings,
		}
		if not template:
			warnings.append(_("Template {0} does not exist").format(row.template))
			result.append(info)
			continue
		roots = _root_items(template)
		suffix = row_subject_suffix(doc, row)
		info["subjects"] = [f"{item.subject} {suffix}".strip() if suffix else item.subject for item in roots]
		info["goal_count"] = len(template.items)
		if not cint(template.is_active):
			warnings.append(_("Template {0} is not active").format(template.name))
		if pairs.get((row.goal_owner, row.template), 0) > 1:
			warnings.append(_("The owner is listed with this template more than once"))
		missing = {
			label: [code for code in codes if code not in available_codes(row)]
			for label, codes in _provider_requirements(template).items()
		}
		for label, codes in missing.items():
			if codes:
				warnings.append(
					_("Metric provider {0} needs parameters: {1}").format(label, ", ".join(codes))
				)
		parent = info["parent_goal"]
		if parent:
			bounds = frappe.db.get_value(
				GOAL, parent, ["exp_start_date", "exp_end_date", "status"], as_dict=True
			)
			if not bounds:
				warnings.append(_("Parent goal {0} does not exist").format(parent))
			else:
				if bounds.status in (STATUS_CLOSED, STATUS_CANCELLED):
					warnings.append(_("Parent goal {0} is {1}").format(parent, _(bounds.status)))
				if (bounds.exp_start_date and getdate(bounds.exp_start_date) > getdate(doc.period_end)) or (
					bounds.exp_end_date and getdate(bounds.exp_end_date) < getdate(doc.period_start)
				):
					warnings.append(_("Parent goal {0} does not overlap the period").format(parent))
		if info["status"] != ROW_CREATED:
			existing = existing_goals(doc, row, template)
			if existing:
				info["existing"] = existing
				warnings.append(
					_("Goals of this template already exist for the owner in the period: {0}").format(
						", ".join(existing)
					)
				)
		result.append(info)
	return result


@frappe.whitelist()
def preview(name: str) -> list[dict]:
	doc = frappe.get_doc(GOAL_CAMPAIGN, name)
	doc.check_permission("read")
	return preview_rows(doc)


# ---------------------------------------------------------------- creation


@frappe.whitelist(methods=["POST"])
def create(name: str) -> dict:
	doc = frappe.get_doc(GOAL_CAMPAIGN, name)
	doc.check_permission("write")
	frappe.has_permission(GOAL, "create", throw=True)
	pending = [row for row in doc.items if row.status != ROW_CREATED]
	if len(pending) > ENQUEUE_THRESHOLD and not frappe.flags.in_test:
		frappe.enqueue(
			"dinext_goals.campaigns.run_campaign",
			queue="long",
			timeout=3600,
			name=name,
			notify=True,
			job_id=f"goal_campaign::{name}",
			deduplicate=True,
			enqueue_after_commit=True,
		)
		return {"queued": True, "rows": len(pending)}
	return run_campaign(name)


def run_campaign(name: str, notify: bool = False) -> dict:
	doc = frappe.get_doc(GOAL_CAMPAIGN, name)
	roots = {row.row_key: row.root_goal for row in doc.items if row.status == ROW_CREATED and row.root_goal}
	templates_cache: dict[str, Any] = {}
	summary = {"rows": 0, "goals": 0, "skipped": 0, "errors": 0}
	for row in ordered_rows(doc):
		if row.status == ROW_CREATED:
			continue
		if row.parent_row:
			parent = roots.get(row.parent_row)
			if not parent:
				_fail(row, _("Parent row {0} has no created goals").format(row.parent_row), summary)
				continue
		else:
			parent = _row_parent(doc, row)
		if row.template not in templates_cache:
			templates_cache[row.template] = frappe.get_doc(GOAL_TEMPLATE, row.template)
		existing = (
			[] if cint(doc.allow_duplicates) else existing_goals(doc, row, templates_cache[row.template])
		)
		if existing:
			row.status = ROW_SKIPPED
			row.message = _("Goals of this template already exist for the owner in the period: {0}").format(
				", ".join(existing)
			)
			summary["skipped"] += 1
			continue
		messages = len(frappe.local.message_log or [])
		frappe.db.savepoint(SAVEPOINT)
		try:
			created = templates.create_goals(
				row.template,
				start_date=doc.period_start,
				end_date=doc.period_end,
				goal_owner=row.goal_owner,
				code_prefix=row_code_prefix(doc, row),
				parent_goal=parent,
				company=doc.company,
				values=load_values(row),
				subject_suffix=row_subject_suffix(doc, row),
			)
		except Exception as exc:
			frappe.db.rollback(save_point=SAVEPOINT)
			frappe.local.message_log = (frappe.local.message_log or [])[:messages]
			_fail(row, strip_html(str(exc)) or type(exc).__name__, summary)
			continue
		row.status = ROW_CREATED
		row.root_goal = created[0] if created else None
		row.created_count = len(created)
		row.message = None
		roots[row.row_key] = row.root_goal
		summary["rows"] += 1
		summary["goals"] += len(created)
	doc.flags.ignore_permissions = True
	doc.save()
	if notify:
		frappe.publish_realtime(
			REALTIME_EVENT, {"name": name, **summary}, user=frappe.session.user, after_commit=True
		)
	return summary


def _fail(row, message: str, summary: dict) -> None:
	row.status = ROW_ERROR
	row.message = message
	summary["errors"] += 1


@frappe.whitelist(methods=["POST"])
def copy_to_next_period(name: str) -> str:
	source = frappe.get_doc(GOAL_CAMPAIGN, name)
	source.check_permission("read")
	frappe.has_permission(GOAL_CAMPAIGN, "create", throw=True)
	start, end = next_period(source.period_type, source.period_start, source.period_end)
	doc = frappe.copy_doc(source)
	doc.period_start, doc.period_end = start, end
	label = period_label(source.period_type, start, end)
	if source.period_label and source.period_label in (source.title or ""):
		doc.title = source.title.replace(source.period_label, label)
	else:
		doc.title = _("Goals for {0}").format(label)
	doc.status = "Draft"
	for row in doc.items:
		row.status = ROW_PENDING
		row.root_goal = None
		row.created_count = 0
		row.message = None
	doc.insert()
	return doc.name


# ---------------------------------------------------------------- team


def cost_center_team(cost_center: str, on_date) -> list[str]:
	if not frappe.db.exists("DocType", "Worker"):
		frappe.throw(_("Cost center teams need the Worker doctype (Dinext Timesheets)"))
	from dinext_goals.providers.timesheet_utilization import team_users

	return team_users(cost_center, on_date)


def department_team(department: str) -> list[str]:
	bounds = frappe.db.get_value("Department", department, ["lft", "rgt"], as_dict=True)
	if not bounds:
		frappe.throw(_("Department {0} does not exist").format(department))
	departments = frappe.get_all(
		"Department", filters={"lft": [">=", bounds.lft], "rgt": ["<=", bounds.rgt]}, pluck="name"
	)
	return frappe.get_all(
		"Employee",
		filters={"department": ["in", departments], "status": "Active", "user_id": ["is", "set"]},
		pluck="user_id",
		order_by="employee_name asc",
	)


@frappe.whitelist()
def get_team(source: str, value: str, on_date: str | None = None) -> list[dict]:
	frappe.has_permission(GOAL_CAMPAIGN, "write", throw=True)
	if source == "Cost Center":
		users = cost_center_team(value, on_date or today())
	elif source == "Department":
		users = department_team(value)
	else:
		frappe.throw(_("Unknown team source {0}").format(source))
	if not users:
		return []
	rows = frappe.get_all(
		"User",
		filters={"name": ["in", list(dict.fromkeys(users))], "enabled": 1},
		fields=["name", "full_name"],
	)
	order = {user: index for index, user in enumerate(dict.fromkeys(users))}
	return [
		{"user": row.name, "full_name": row.full_name or row.name}
		for row in sorted(rows, key=lambda row: order[row.name])
	]
