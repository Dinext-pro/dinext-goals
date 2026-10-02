"""Demo of the ИТК motivation system (KPI_v6) on the Russian demo team.

Run:      bench --site localhost execute dinext_goals.demo.motivation_itk.setup
Remove:   bench --site localhost execute dinext_goals.demo.motivation_itk.teardown

Q3 2026 goes through the approval engine, is recalculated and closed; Q4 2026 stays Active with a
few branches left For Approval. Every record the demo creates carries the ``DEMO-ITK`` marker or is
listed in the global state, so ``setup`` can be re-run and ``teardown`` removes exactly what was added.

Extra timesheet hours are written as already approved positions (like imported history): the
timesheet approval workflow finalizes through background Workflow Tasks and cannot be driven
synchronously from a script.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta

import frappe
from frappe.utils import getdate, now_datetime

from dinext_goals.constants import (
	GOAL,
	GOAL_TEMPLATE,
	ROLE_APPROVER,
	ROLE_FINANCE,
	ROLE_MANAGER,
	ROLE_OWNER,
	STATUS_ACTIVE,
)
from dinext_goals.goals import hierarchy, lifecycle
from dinext_goals.progress import engine
from dinext_goals.providers.timesheet_utilization import APPROVED_STATUS, planned_hours, utilized_hours

MARKER = "DEMO-ITK"
STATE_KEY = "dinext_goals_demo_motivation_itk"
COMPANY = "Dinext"
COMPANY_ROOT_CC = "Dinext - D"
CASH = "Cash - D"
INCOME = "Sales - D"
EXPENSE = "Salary - D"

DIRECTOR = "dinext.test.user07@example.com"
FINANCE = "dinext.test.user05@example.com"
SERVICE_USERS = {DIRECTOR: "Директор ИТК (user07)", FINANCE: "Финансист (user05)"}

ELENA = "screens.elena.ru@example.test"
ALEXEY = "screens.alexey.ru@example.test"
DMITRY = "screens.dmitry.ru@example.test"
SERGEY = "screens.sergey.ru@example.test"
MARIA = "screens.maria.ru@example.test"
ANNA = "screens.anna.ru@example.test"

CC_ITK = "ЦФО ИТК - D"
CC_IMPL = "ЦФО Внедрение - D"
CC_SUPP = "ЦФО Сопровождение - D"

T_MANAGER = "Квартальный бонус менеджера"
T_SPECIALIST = "Квартальный бонус специалиста"
T_MONTHLY = "Ежемесячная премия"
T_PROJECT = "Проектный бонус"

VALID_FROM = "2026-07-01"
PERIODS = {
	"Q3": {
		"start": "2026-07-01",
		"end": "2026-09-30",
		"label": "III кв. 2026",
		"months": ((7, "июль"), (8, "август"), (9, "сентябрь")),
	},
	"Q4": {"start": "2026-10-01", "end": "2026-12-31", "label": "IV кв. 2026", "months": ((10, "октябрь"),)},
}
ITK_PROJECTS = ["DEMO-RU-01", "DEMO-RU-05", "DEMO-RU-09"]
ITK_TARGET = {"Q3": 2_500_000, "Q4": 3_000_000}

CFOS = (
	{
		"key": "IMPL",
		"subject": "ЦФО Внедрение",
		"manager": ELENA,
		"cost_center": CC_IMPL,
		"projects": ["DEMO-RU-01", "DEMO-RU-09"],
		"profit_target": {"Q3": 1_000_000, "Q4": 1_200_000},
		"specialists": ("VOLKOV", "ORLOV"),
	},
	{
		"key": "SUPP",
		"subject": "ЦФО Сопровождение",
		"manager": SERGEY,
		"cost_center": CC_SUPP,
		"projects": ["DEMO-RU-05"],
		"profit_target": {"Q3": 1_000_000, "Q4": 1_000_000},
		"specialists": ("SMIRNOVA", "MOROZOVA"),
	},
)

# bonus_base and k_prem follow the grade rules of KPI_v6; points_plan spreads К балл over its steps.
SPECIALISTS = {
	"VOLKOV": {
		"user": ALEXEY,
		"grade": 4,
		"bonus_base": 15,
		"k_prem": 20,
		"points_plan": 400,
		"k_pers": {"Q3": 100, "Q4": 100},
	},
	"ORLOV": {
		"user": DMITRY,
		"grade": 3,
		"bonus_base": 10,
		"k_prem": 20,
		"points_plan": 600,
		"k_pers": {"Q3": 80},
	},
	"SMIRNOVA": {
		"user": MARIA,
		"grade": 3,
		"bonus_base": 10,
		"k_prem": 20,
		"points_plan": 350,
		"k_pers": {"Q3": 120},
	},
	"MOROZOVA": {
		"user": ANNA,
		"grade": 2,
		"bonus_base": 0,
		"k_prem": 30,
		"points_plan": 500,
		"k_pers": {"Q3": 50},
	},
}

WORKERS = {
	ELENA: {"cost_center": CC_IMPL, "utilization": 30},
	ALEXEY: {"cost_center": CC_IMPL, "utilization": 70},
	DMITRY: {"cost_center": CC_IMPL, "utilization": 80},
	SERGEY: {"cost_center": CC_SUPP, "utilization": 30},
	MARIA: {"cost_center": CC_SUPP, "utilization": 80},
	ANNA: {"cost_center": CC_SUPP, "utilization": 80},
}

# Q3 utilization targets, % of plan: Внедрение team lands above 110% (К перс 1.2), Сопровождение at 90-110%.
Q3_UTILIZATION = {ALEXEY: 115, DMITRY: 85, MARIA: 95, ANNA: 70}
OCTOBER_HOURS = {ELENA: 3, ALEXEY: 6, DMITRY: 4, SERGEY: 2, MARIA: 7, ANNA: 3}
OCTOBER_DAYS = ("2026-10-01", "2026-10-02")
TIMESHEET_TASK = {CC_IMPL: ("DEMO-RU-09", "TASK-2026-00069"), CC_SUPP: ("DEMO-RU-05", "TASK-2026-00049")}
OCTOBER_POINTS = {ALEXEY: 80, DMITRY: 30, MARIA: 90, ANNA: 40}

# (posting date, project, cost center, income, expense)
JOURNAL = (
	("2026-07-15", "DEMO-RU-09", CC_IMPL, 300_000, 144_000),
	("2026-08-14", "DEMO-RU-09", CC_IMPL, 300_000, 144_000),
	("2026-09-15", "DEMO-RU-09", CC_IMPL, 300_000, 144_000),
	("2026-07-15", "DEMO-RU-05", CC_SUPP, 450_000, 150_000),
	("2026-08-14", "DEMO-RU-05", CC_SUPP, 150_000, 120_000),
	("2026-09-15", "DEMO-RU-05", CC_SUPP, 150_000, 80_000),
	("2026-10-01", "DEMO-RU-09", CC_IMPL, 250_000, 100_000),
	("2026-10-01", "DEMO-RU-05", CC_SUPP, 50_000, 30_000),
)
# DEMO-RU-05 budget, Aug-Nov 2026: 1.2M income and 0.6M expense, planned profit 600k.
BUDGET_RU05 = ((INCOME, 300_000), (EXPENSE, 150_000))
BUDGET_MONTHS = (8, 9, 10, 11)

ROLES = {
	DIRECTOR: (ROLE_MANAGER, ROLE_APPROVER, ROLE_OWNER),
	FINANCE: (ROLE_FINANCE,),
	ELENA: (ROLE_OWNER, ROLE_APPROVER),
	SERGEY: (ROLE_OWNER, ROLE_APPROVER),
	ALEXEY: (ROLE_OWNER,),
	DMITRY: (ROLE_OWNER,),
	MARIA: (ROLE_OWNER,),
	ANNA: (ROLE_OWNER,),
}


# ---------------------------------------------------------------- state


def _load_state() -> dict:
	raw = frappe.db.get_global(STATE_KEY)
	return json.loads(raw) if raw else {}


def _save_state(state: dict) -> None:
	frappe.db.set_global(STATE_KEY, json.dumps(state, ensure_ascii=False))


def _track(state: dict, key: str, value) -> None:
	state.setdefault(key, []).append(value)


# ---------------------------------------------------------------- params


def _param(
	code, param_type, value=None, *, label=None, link_doctype=None, options=None, editable=0, inherit=1
):
	row = {
		"code": code,
		"label": label or code,
		"param_type": param_type,
		"link_doctype": link_doctype,
		"select_options": options,
		"inherit": inherit,
		"editable_when_active": editable,
	}
	if value is not None:
		if param_type in ("Int", "Float", "Currency", "Percent"):
			row["value_number"] = value
		elif param_type == "Link":
			row["value_link"] = value
		elif param_type == "Link List":
			row["value_list"] = "\n".join(value)
		elif param_type == "Date":
			row["value_date"] = value
		elif param_type == "Check":
			row["value_check"] = value
		else:
			row["value_data"] = value
	return row


# ---------------------------------------------------------------- master data


def _ensure_users(state: dict) -> None:
	for email, full_name in SERVICE_USERS.items():
		if frappe.db.exists("User", email):
			continue
		first, _sep, last = full_name.partition(" ")
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": first,
				"last_name": last,
				"send_welcome_email": 0,
				"user_type": "System User",
			}
		).insert(ignore_permissions=True)
		_track(state, "users", email)
	for user, roles in ROLES.items():
		current = set(frappe.get_roles(user))
		missing = [role for role in roles if role not in current]
		if missing:
			frappe.get_doc("User", user).add_roles(*missing)
			for role in missing:
				_track(state, "roles", [user, role])


def _ensure_cost_centers(state: dict) -> None:
	for name, parent, is_group in ((CC_ITK, COMPANY_ROOT_CC, 1), (CC_IMPL, CC_ITK, 0), (CC_SUPP, CC_ITK, 0)):
		if frappe.db.exists("Cost Center", name):
			continue
		frappe.get_doc(
			{
				"doctype": "Cost Center",
				"cost_center_name": name.rsplit(" - ", 1)[0],
				"company": COMPANY,
				"parent_cost_center": parent,
				"is_group": is_group,
			}
		).insert(ignore_permissions=True)
		_track(state, "cost_centers", name)


def _worker_of(user: str) -> str:
	return frappe.db.get_value("Worker", {"wuser": user}, "name")


def _insert_child(doctype: str, parent: str, parentfield: str, values: dict) -> str:
	idx = frappe.db.count(doctype, {"parent": parent, "parenttype": "Worker", "parentfield": parentfield}) + 1
	row = frappe.get_doc(
		{
			"doctype": doctype,
			"parent": parent,
			"parenttype": "Worker",
			"parentfield": parentfield,
			"idx": idx,
			**values,
		}
	)
	row.db_insert()
	return row.name


def _ensure_worker_rows(state: dict) -> None:
	for user, spec in WORKERS.items():
		worker = _worker_of(user)
		name = _insert_child(
			"Cost Center Table",
			worker,
			"cost_center_table",
			{"cct_valid_from": VALID_FROM, "cct_cost_center": spec["cost_center"]},
		)
		_track(state, "child_rows", ["Cost Center Table", name])
		name = _insert_child(
			"Worker Utilization Table",
			worker,
			"utilization",
			{"util_valid_from": VALID_FROM, "utilization": spec["utilization"]},
		)
		_track(state, "child_rows", ["Worker Utilization Table", name])
		frappe.clear_document_cache("Worker", worker)


def _post_journal() -> None:
	for posting_date, project, cost_center, income, expense in JOURNAL:
		for account, amount, is_income in ((INCOME, income, True), (EXPENSE, expense, False)):
			cash = {"account": CASH, "cost_center": cost_center, "project": project}
			line = {"account": account, "cost_center": cost_center, "project": project}
			if is_income:
				cash["debit_in_account_currency"] = amount
				line["credit_in_account_currency"] = amount
			else:
				cash["credit_in_account_currency"] = amount
				line["debit_in_account_currency"] = amount
			je = frappe.get_doc(
				{
					"doctype": "Journal Entry",
					"company": COMPANY,
					"posting_date": posting_date,
					"voucher_type": "Journal Entry",
					"user_remark": f"{MARKER}: {project}",
					"accounts": [line, cash],
				}
			)
			je.insert(ignore_permissions=True)
			je.submit()


def _ensure_budget(state: dict) -> None:
	for account, monthly in BUDGET_RU05:
		doc = frappe.get_doc(
			{
				"doctype": "Project Budget",
				"pb_project": "DEMO-RU-05",
				"pb_account": account,
				"project_budget_amount": [
					{"pba_year": 2026, "pba_month": month, "pba_plan": monthly} for month in BUDGET_MONTHS
				],
			}
		).insert(ignore_permissions=True)
		_track(state, "budgets", doc.name)


def _ensure_energy_points() -> None:
	for user, points in OCTOBER_POINTS.items():
		frappe.get_doc(
			{
				"doctype": "Energy Point Log",
				"user": user,
				"type": "Auto",
				"points": points,
				"reason": MARKER,
				"reference_doctype": "Project",
				"reference_name": "DEMO-RU-09",
			}
		).insert(ignore_permissions=True)


# ---------------------------------------------------------------- timesheets


def _absence_days(user: str, date_from, date_to) -> set[date]:
	days: set[date] = set()
	for leave in frappe.get_all(
		"Application For Leave",
		filters={
			"lauser": user,
			"status": APPROVED_STATUS,
			"alfrom_date": ["<=", date_to],
			"alto_date": [">=", date_from],
		},
		fields=["alfrom_date", "alto_date", "altype_of_leave"],
	):
		if leave.altype_of_leave == "Отгул":
			continue
		day = getdate(leave.alfrom_date)
		while day <= getdate(leave.alto_date):
			days.add(day)
			day += timedelta(days=1)
	return days


def _working_days(user: str, date_from, date_to) -> list[date]:
	worker = frappe.get_doc("Worker", _worker_of(user))
	holidays = {
		getdate(d)
		for d in frappe.get_all(
			"Holiday",
			filters={"parent": worker.wholiday_list, "holiday_date": ["between", [date_from, date_to]]},
			pluck="holiday_date",
		)
	}
	absent = _absence_days(user, date_from, date_to)
	days, day = [], getdate(date_from)
	while day <= getdate(date_to):
		if day.weekday() < 5 and day not in holidays and day not in absent:
			days.append(day)
		day += timedelta(days=1)
	return days


def _spread(total: float, days: list[date]) -> dict[date, float]:
	if total <= 0 or not days:
		return {}
	per_day = round(total / len(days) * 4) / 4
	hours = {day: per_day for day in days}
	hours[days[-1]] = round(total - per_day * (len(days) - 1), 2)
	return {day: value for day, value in hours.items() if value > 0}


def _insert_position(user: str, hours_by_day: dict[date, float]) -> None:
	"""One approved position per ISO week, inserted without workflow hooks."""
	cost_center = WORKERS[user]["cost_center"]
	project, task = TIMESHEET_TASK[cost_center]
	template = frappe.get_all(
		"User Timesheet Position",
		filters={"user": user},
		fields=["user_group", "custom_username", "project_role"],
		limit=1,
	)
	template = template[0] if template else frappe._dict()
	full_name = template.custom_username or frappe.db.get_value("User", user, "full_name")
	weeks: dict[date, dict[date, float]] = defaultdict(dict)
	for day, value in hours_by_day.items():
		weeks[day - timedelta(days=day.weekday())][day] = value
	for monday, days in sorted(weeks.items()):
		sunday = monday + timedelta(days=6)
		timesheet = f"{full_name} - {monday} - {sunday}"
		doc = frappe.get_doc(
			{
				"doctype": "User Timesheet Position",
				"user": user,
				"user_timesheet": timesheet if frappe.db.exists("User Timesheet", timesheet) else None,
				"custom_username": full_name,
				"user_group": template.user_group,
				"project_role": template.project_role or "Разработчик",
				"project": project,
				"document_type": "Task",
				"document_name": task,
				"status": APPROVED_STATUS,
				"workflow_state": APPROVED_STATUS,
				"period": f"{monday.year}-{monday.month:02d}-{monday.isocalendar()[1]}",
				"all_hours": sum(days.values()),
				"custom_data": MARKER,
			}
		)
		doc.owner = user
		doc.creation = doc.modified = now_datetime()
		doc.set_new_name()
		doc.db_insert()
		for idx, (day, value) in enumerate(sorted(days.items()), start=1):
			row = frappe.get_doc(
				{
					"doctype": "User Timesheet Position Details",
					"parent": doc.name,
					"parenttype": "User Timesheet Position",
					"parentfield": "table",
					"idx": idx,
					"date": day,
					"hours": value,
					"utilized_hours": value,
					"description": MARKER,
				}
			)
			row.db_insert()


def _ensure_timesheets() -> None:
	q3 = PERIODS["Q3"]
	for user, percent in Q3_UTILIZATION.items():
		plan = planned_hours(user, q3["start"], q3["end"])
		missing = plan * percent / 100.0 - utilized_hours([user], q3["start"], q3["end"])
		_insert_position(user, _spread(missing, _working_days(user, q3["start"], q3["end"])))
	for user, per_day in OCTOBER_HOURS.items():
		_insert_position(user, {getdate(day): per_day for day in OCTOBER_DAYS})


# ---------------------------------------------------------------- templates


def _template_item(key, subject, **values):
	item = {"item_key": key, "subject": subject, "goal_code": key, "weight": 1, "progress_method": "Auto"}
	item.update(values)
	return item


def _utilization_item(key, subject, parent, scale_spec, **values):
	return _template_item(
		key,
		subject,
		parent_key=parent,
		metric_type="Percent",
		unit="%",
		baseline=0,
		target=100,
		metric_source="Provider",
		metric_provider="timesheet_utilization",
		scale_spec=scale_spec,
		**values,
	)


MANAGER_RESULT = (
	'0 if tree_goal("ITK-PROFIT").value <= 0 else max(0, params.profit_share * child("PROFIT").value'
	' * (child("PROFIT").coefficient if tree_goal("ITK-PROFIT").achievement >= 50'
	' else (1 if child("PROFIT").achievement >= 80 else 0))'
	' * child("KPERS").coefficient)'
)
SPECIALIST_RESULT = (
	'round(child("UTIL").coefficient * child("UTIL").value / 100 * params.bonus_base'
	' * child("KPERS").coefficient * child("POINTS").coefficient * 100, 2)'
)
MONTHLY_RESULT = "round(params.k_prem * min(1, goal.value / 100) * 100, 2)"
PROJECT_RESULT = "params.project_bonus_share * max(0, goal.value - goal.target)"


def _templates() -> list[dict]:
	return [
		{
			"template_name": T_MANAGER,
			"goal_type": "KPI",
			"default_duration_days": 92,
			"items": [
				_template_item(
					"MGR",
					"Квартальный бонус менеджера",
					is_group=1,
					result_label="Расчетный бонус, ₽",
					result_formula=MANAGER_RESULT,
				),
				_template_item(
					"PROFIT",
					"Валовая прибыль ЦФО (К выпол)",
					parent_key="MGR",
					weight=2,
					metric_type="Currency",
					currency="RUB",
					baseline=0,
					target=0,
					metric_source="Provider",
					metric_provider="gl_profit",
					scale_spec="0:0\n50:1",
				),
				_utilization_item(
					"KPERS", "Утилизация команды ЦФО (К перс)", "MGR", "0:0.5\n50:0.8\n90:1\n110:1.2"
				),
			],
			"template_parameters": [
				_param("cost_center", "Link", label="ЦФО", link_doctype="Cost Center") | {"ask_on_create": 1},
				_param("scope", "Select", "team", label="Режим утилизации", options="user\nteam")
				| {"item_key": "KPERS"},
			],
		},
		{
			"template_name": T_SPECIALIST,
			"goal_type": "KPI",
			"default_duration_days": 92,
			"items": [
				_template_item(
					"SPEC",
					"Квартальный бонус специалиста",
					is_group=1,
					result_label="Бонус, % квартального дохода",
					result_formula=SPECIALIST_RESULT,
				),
				_utilization_item(
					"UTIL", "Коммерческая утилизация (К выпол ут)", "SPEC", "0:0\n50:0.3\n90:1"
				),
				_template_item(
					"POINTS",
					"Баллы активности (К балл)",
					parent_key="SPEC",
					metric_type="Numeric",
					unit="баллы",
					baseline=0,
					target_source="Formula",
					target_formula="params.points_plan",
					metric_source="Provider",
					metric_provider="energy_points",
					scale_spec="0:0\n50:0.5\n80:1\n120.0001:1.2",
				),
				_template_item(
					"KPERS",
					"Персональные цели (К перс)",
					parent_key="SPEC",
					goal_type="Personal",
					progress_method="Manual",
					owner_source="Parent Goal Owner",
					metric_type="Numeric",
					unit="%",
					baseline=0,
					target=100,
					scale_spec="50:0.5\n80:0.8\n100:1\n120:1.2",
					description="Оценку 50/80/100/120 вводит менеджер.",
				),
			],
			"template_parameters": [
				_param("grade", "Int", label="Грейд") | {"ask_on_create": 1},
				_param("bonus_base", "Percent", label="База бонуса, % дохода") | {"ask_on_create": 1},
				_param("k_prem", "Percent", label="К прем") | {"ask_on_create": 1},
				_param("points_plan", "Int", label="План баллов") | {"ask_on_create": 1},
				_param("scope", "Select", "user", label="Режим утилизации", options="user\nteam")
				| {"item_key": "UTIL"},
			],
		},
		{
			"template_name": T_MONTHLY,
			"goal_type": "KPI",
			"default_duration_days": 31,
			"items": [
				_utilization_item(
					"MONTH",
					"Ежемесячная премия: утилизация",
					None,
					"",
					result_label="Премия, % месячного дохода",
					result_formula=MONTHLY_RESULT,
				),
			],
			"template_parameters": [
				_param("k_prem", "Percent", label="К прем") | {"ask_on_create": 1},
				_param("scope", "Select", "user", label="Режим утилизации", options="user\nteam"),
			],
		},
		{
			"template_name": T_PROJECT,
			"goal_type": "Project Goal",
			"default_duration_days": 92,
			"items": [
				_template_item(
					"PROJECT",
					"Проектный бонус",
					metric_type="Currency",
					currency="RUB",
					baseline=0,
					target_source="Provider",
					target_provider="project_budget_profit",
					metric_source="Provider",
					metric_provider="gl_profit",
					result_label="Фонд проектного бонуса, ₽",
					result_formula=PROJECT_RESULT,
				),
			],
			"template_parameters": [
				_param("projects", "Link List", label="Проекты", link_doctype="Project")
				| {"ask_on_create": 1},
			],
		},
	]


def _ensure_templates() -> None:
	for spec in _templates():
		frappe.get_doc(
			{
				"doctype": GOAL_TEMPLATE,
				"is_active": 1,
				"description": f"Демо системы мотивации ИТК ({MARKER}).",
				**spec,
			}
		).insert(ignore_permissions=True)


# ---------------------------------------------------------------- goals


def _goal(subject, code, owner, start, end, *, parent=None, goal_type="Strategic", **values) -> str:
	doc = frappe.get_doc(
		{
			"doctype": GOAL,
			"subject": subject,
			"goal_code": code,
			"goal_type": goal_type,
			"goal_owner": owner,
			"company": COMPANY,
			"exp_start_date": start,
			"exp_end_date": end,
			"parents": [{"parent_goal": parent}] if parent else [],
			**values,
		}
	)
	doc.flags.skip_related_recalculation = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _from_template(template, start, owner, prefix, parent, values=None, suffix=None) -> dict[str, str]:
	from dinext_goals import templates

	names = templates.create_goals(
		template,
		start_date=start,
		goal_owner=owner,
		code_prefix=prefix,
		parent_goal=parent,
		company=COMPANY,
		values=values or {},
		subject_suffix=suffix,
	)
	return {frappe.db.get_value(GOAL, name, "goal_code"): name for name in names}


def _month_bounds(year: int, month: int) -> tuple[date, date]:
	start = date(year, month, 1)
	end = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
	return start, end


def _build_quarter(quarter: str) -> dict:
	period = PERIODS[quarter]
	start, end, label = period["start"], period["end"], period["label"]
	prefix = f"{MARKER}-{quarter}"
	tree: dict = {"root": None, "cfo": {}, "specialists": {}, "monthly": {}, "projects": {}}

	tree["root"] = _goal(
		f"Дирекция ИТК, {label}",
		prefix,
		DIRECTOR,
		start,
		end,
		is_group=1,
		parameters=[
			_param("itk_cost_center", "Link", CC_ITK, label="ЦФО ИТК", link_doctype="Cost Center"),
			_param("profit_share", "Percent", 5, label="Доля прибыли в бонусе менеджера"),
			_param("project_bonus_share", "Percent", 30, label="Доля проектного бонуса"),
			_param("reference_date", "Date", end, label="Дата среза", editable=1),
		],
	)
	tree["itk_profit"] = _goal(
		f"Валовая прибыль ЦФО ИТК, {label}",
		f"{prefix}-ITK-PROFIT",
		DIRECTOR,
		start,
		end,
		parent=tree["root"],
		goal_type="KPI",
		metric_type="Currency",
		currency="RUB",
		baseline=0,
		target=ITK_TARGET[quarter],
		metric_source="Provider",
		metric_provider="gl_profit",
		parameters=[
			_param("projects", "Link List", ITK_PROJECTS, label="Проекты ИТК", link_doctype="Project")
		],
	)
	for cfo in CFOS:
		cfo_prefix = f"{prefix}-{cfo['key']}"
		cfo_goal = _goal(
			f"{cfo['subject']}, {label}",
			cfo_prefix,
			cfo["manager"],
			start,
			end,
			parent=tree["root"],
			is_group=1,
			parameters=[
				_param("cost_center", "Link", cfo["cost_center"], label="ЦФО", link_doctype="Cost Center"),
				_param("projects", "Link List", cfo["projects"], label="Проекты ЦФО", link_doctype="Project"),
			],
		)
		manager = _from_template(T_MANAGER, start, cfo["manager"], cfo_prefix, cfo_goal, suffix=label)
		frappe.db.set_value(GOAL, manager[f"{cfo_prefix}-PROFIT"], "target", cfo["profit_target"][quarter])
		tree["cfo"][cfo["key"]] = {"goal": cfo_goal, "manager": manager}
		for key in cfo["specialists"]:
			spec = SPECIALISTS[key]
			full_name = frappe.db.get_value("User", spec["user"], "full_name")
			spec_prefix = f"{prefix}-{key}"
			tree["specialists"][key] = _from_template(
				T_SPECIALIST,
				start,
				spec["user"],
				spec_prefix,
				cfo_goal,
				values={k: spec[k] for k in ("grade", "bonus_base", "k_prem", "points_plan")},
				suffix=f"— {full_name}, {label}",
			)
			monthly = _goal(
				f"Ежемесячная премия — {full_name}, {label}",
				f"{spec_prefix}-MONTHLY",
				spec["user"],
				start,
				end,
				parent=cfo_goal,
				goal_type="KPI",
				is_group=1,
			)
			months = {"group": monthly}
			for month, month_label in period["months"]:
				month_start, month_end = _month_bounds(2026, month)
				created = _from_template(
					T_MONTHLY,
					month_start,
					spec["user"],
					f"{spec_prefix}-M{month:02d}",
					monthly,
					values={"k_prem": spec["k_prem"]},
					suffix=f"— {full_name}, {month_label} 2026",
				)
				goal_name = next(iter(created.values()))
				frappe.db.set_value(GOAL, goal_name, "exp_end_date", month_end)
				months[month] = goal_name
			tree["monthly"][key] = months
	if quarter == "Q3":
		tree["projects"]["DEMO-RU-01"] = _from_template(
			T_PROJECT,
			"2026-05-01",
			ELENA,
			f"{prefix}-IMPL-RU01",
			tree["cfo"]["IMPL"]["goal"],
			values={"projects": ["DEMO-RU-01"]},
			suffix="DEMO-RU-01",
		)
		frappe.db.set_value(
			GOAL, tree["projects"]["DEMO-RU-01"][f"{prefix}-IMPL-RU01-PROJECT"], "exp_end_date", end
		)
	else:
		tree["projects"]["DEMO-RU-05"] = _from_template(
			T_PROJECT,
			"2026-08-01",
			SERGEY,
			f"{prefix}-SUPP-RU05",
			tree["cfo"]["SUPP"]["goal"],
			values={"projects": ["DEMO-RU-05"]},
			suffix="DEMO-RU-05",
		)
		frappe.db.set_value(
			GOAL, tree["projects"]["DEMO-RU-05"][f"{prefix}-SUPP-RU05-PROJECT"], "exp_end_date", "2026-11-30"
		)
	engine.recalculate(tree["root"])
	return tree


# ---------------------------------------------------------------- approval


def _act(user: str, goal: str, action: str) -> None:
	from dinext_common.workflow_approval import api as workflow_api

	frappe.set_user(user)
	try:
		workflow_api.apply_workflow(frappe.get_doc(GOAL, goal).as_dict(), action)
	finally:
		frappe.set_user("Administrator")


def submit(goal: str) -> None:
	_act(frappe.db.get_value(GOAL, goal, "goal_owner"), goal, "Submit for Approval")


def approve(goal: str) -> None:
	"""Submit by the owner, approve by every parent-goal owner, then by finance."""
	submit(goal)
	for user in (frappe.db.get_value(GOAL, goal, "approver_users") or "").split("\n"):
		if user:
			_act(user, goal, "Approve")
	_act(FINANCE, goal, "Approve")
	status = frappe.db.get_value(GOAL, goal, "status")
	if status != STATUS_ACTIVE:
		frappe.throw(f"Demo goal {goal} ended in status {status} instead of Active")


def _tree_names(root: str) -> list[str]:
	return [root, *hierarchy.get_descendants(root)]


def _set_k_pers(tree: dict, quarter: str) -> None:
	for key, goals in tree["specialists"].items():
		value = SPECIALISTS[key]["k_pers"].get(quarter)
		if value is None:
			continue
		name = goals[f"{MARKER}-{quarter}-{key}-KPERS"]
		doc = frappe.get_doc(GOAL, name)
		frappe.set_user(doc.goal_owner)
		try:
			doc.current_value = value
			doc.save()
		finally:
			frappe.set_user("Administrator")


def _close(root: str) -> None:
	frappe.set_user(DIRECTOR)
	try:
		for name in hierarchy.topological_order(_tree_names(root)):
			lifecycle.apply_lifecycle_action(frappe.get_doc(GOAL, name), "close")
	finally:
		frappe.set_user("Administrator")


def _q4_pending(tree: dict) -> set[str]:
	"""Specialist branches of Сопровождение stay For Approval in Q4."""
	pending: set[str] = set()
	for key in ("SMIRNOVA", "MOROZOVA"):
		pending.update(tree["specialists"][key].values())
		pending.update(tree["monthly"][key].values())
	return pending


# ---------------------------------------------------------------- entry points


def setup() -> dict:
	frappe.only_for(("System Manager", "Administrator"))
	if _load_state():
		teardown()
	frappe.flags.mute_emails = True
	frappe.set_user("Administrator")
	state: dict = {}
	try:
		_ensure_users(state)
		_ensure_cost_centers(state)
		_ensure_worker_rows(state)
		_post_journal()
		_ensure_budget(state)
		_ensure_energy_points()
		_ensure_timesheets()
		_ensure_templates()
		_save_state(state)
		frappe.db.commit()

		q3 = _build_quarter("Q3")
		for name in _tree_names(q3["root"]):
			approve(name)
		_set_k_pers(q3, "Q3")
		engine.recalculate(q3["root"])
		_close(q3["root"])

		q4 = _build_quarter("Q4")
		pending = _q4_pending(q4)
		for name in _tree_names(q4["root"]):
			if name in pending:
				submit(name)
			else:
				approve(name)
		_set_k_pers(q4, "Q4")
		engine.recalculate(q4["root"])
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		_save_state(state)
		frappe.db.commit()
		raise
	finally:
		frappe.flags.mute_emails = False
	result = summary()
	print(json.dumps(result, ensure_ascii=False, indent=1, default=str))
	return result


def summary() -> dict:
	fields = [
		"goal_code",
		"subject",
		"status",
		"current_value",
		"target",
		"achievement_percent",
		"coefficient",
		"result_value",
		"rag_status",
	]
	return {
		row.goal_code: {k: row[k] for k in fields[1:]}
		for row in frappe.get_all(
			GOAL, filters={"goal_code": ["like", f"{MARKER}-%"]}, fields=fields, order_by="goal_code"
		)
	}


def _demo_goals() -> list[str]:
	return frappe.get_all(GOAL, filters={"goal_code": ["like", f"{MARKER}-%"]}, pluck="name")


def _delete_workflow_tasks(goals: list[str]) -> None:
	"""Same cleanup as dinext_common retention: actions and ToDos first, then the guarded tasks."""
	tasks = frappe.get_all(
		"Workflow Task", filters={"reference_doctype": GOAL, "reference_name": ["in", goals]}, pluck="name"
	)
	if not tasks:
		return
	for doctype, filters in (
		("Workflow Action", {"custom_workflow_task": ["in", tasks]}),
		("ToDo", {"reference_type": "Workflow Task", "reference_name": ["in", tasks]}),
		("ToDo", {"reference_type": GOAL, "reference_name": ["in", goals]}),
	):
		for name in frappe.get_all(doctype, filters=filters, pluck="name"):
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
	previous = getattr(frappe.flags, "in_workflow_task_retention", False)
	frappe.flags.in_workflow_task_retention = True
	try:
		for task in tasks:
			frappe.delete_doc("Workflow Task", task, ignore_permissions=True, force=True)
	finally:
		frappe.flags.in_workflow_task_retention = previous


def teardown() -> None:
	frappe.only_for(("System Manager", "Administrator"))
	frappe.set_user("Administrator")
	state = _load_state()

	goals = _demo_goals()
	if goals:
		_delete_workflow_tasks(goals)
		frappe.db.delete("Goal Log", {"goal": ["in", goals]})
		# Parents first: their children are gone by the time after_delete would recalculate them.
		for name in reversed(hierarchy.topological_order(goals)):
			frappe.delete_doc(GOAL, name, ignore_permissions=True, force=True)

	for template in frappe.get_all(
		GOAL_TEMPLATE, filters={"description": ["like", f"%{MARKER}%"]}, pluck="name"
	):
		frappe.delete_doc(GOAL_TEMPLATE, template, ignore_permissions=True, force=True)

	positions = frappe.get_all("User Timesheet Position", filters={"custom_data": MARKER}, pluck="name")
	if positions:
		frappe.db.delete("User Timesheet Position Details", {"parent": ["in", positions]})
		frappe.db.delete("User Timesheet Position", {"name": ["in", positions]})

	for log in frappe.get_all("Energy Point Log", filters={"reason": MARKER}, pluck="name"):
		frappe.delete_doc("Energy Point Log", log, ignore_permissions=True, force=True)

	for je in frappe.get_all(
		"Journal Entry", filters={"user_remark": ["like", f"{MARKER}:%"]}, fields=["name", "docstatus"]
	):
		if je.docstatus == 1:
			frappe.get_doc("Journal Entry", je.name).cancel()
		frappe.db.delete("GL Entry", {"voucher_type": "Journal Entry", "voucher_no": je.name})
		frappe.db.delete("Payment Ledger Entry", {"voucher_type": "Journal Entry", "voucher_no": je.name})
		frappe.delete_doc("Journal Entry", je.name, ignore_permissions=True, force=True)

	for budget in state.get("budgets", []):
		if frappe.db.exists("Project Budget", budget):
			frappe.delete_doc("Project Budget", budget, ignore_permissions=True, force=True)

	for doctype, name in state.get("child_rows", []):
		frappe.db.delete(doctype, {"name": name})
	for user in WORKERS:
		worker = _worker_of(user)
		if worker:
			frappe.clear_document_cache("Worker", worker)

	for name in reversed(state.get("cost_centers", [])):
		if frappe.db.exists("Cost Center", name):
			frappe.delete_doc("Cost Center", name, ignore_permissions=True, force=True)

	for user, role in state.get("roles", []):
		if frappe.db.exists("User", user):
			frappe.get_doc("User", user).remove_roles(role)
	for user in state.get("users", []):
		if frappe.db.exists("User", user):
			frappe.delete_doc("User", user, ignore_permissions=True, force=True)

	frappe.db.set_global(STATE_KEY, None)
	frappe.db.commit()


def is_installed() -> bool:
	return bool(_demo_goals() or _load_state())
