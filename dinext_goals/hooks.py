app_name = "dinext_goals"
app_title = "Dinext Goals"
app_publisher = "Dinext"
app_description = "Dinext Goals"
app_email = "info@dinext.ru"
app_license = "GNU General Public License (v3)"

required_apps = ["dinext_common", "erpnext"]

after_install = "dinext_goals.install.after_install"
after_migrate = ["dinext_goals.install.after_migrate"]

fixtures = [
	{
		"doctype": "Role",
		"filters": [
			["name", "in", ["Goal Manager", "Goal Owner", "Goal Approver", "Goal Finance Approver"]],
		],
	},
	{
		"doctype": "Workflow State",
		"filters": [
			["workflow_state_name", "in", ["Draft", "Parent Approval", "Finance Approval", "Approved"]],
		],
	},
	{
		"doctype": "Workflow Action Master",
		"filters": [
			["name", "in", ["Submit for Approval", "Approve", "Reject"]],
		],
	},
	{
		"doctype": "Workflow",
		"filters": [
			["name", "in", ["Goal Approval"]],
		],
	},
	{
		"doctype": "Goal Type",
		"filters": [
			["name", "in", ["OKR", "KPI", "Project Goal", "Personal", "Strategic"]],
		],
	},
	{
		"doctype": "Goal Template",
		"filters": [
			[
				"name",
				"in",
				[
					"Бонус руководителя подразделения",
					"Бонус сотрудника",
					"Премия за утилизацию",
					"Проектный бонус",
				],
			],
		],
	},
]

has_permission = {
	"Goal": "dinext_goals.goals.permissions.goal_has_permission",
	"Goal Log": "dinext_goals.goals.permissions.goal_log_has_permission",
}

permission_query_conditions = {
	"Goal": "dinext_goals.goals.permissions.goal_query_conditions",
	"Goal Log": "dinext_goals.goals.permissions.goal_log_query_conditions",
}

app_include_js = ["/assets/dinext_goals/js/goal_navbar.js"]
app_include_css = ["/assets/dinext_goals/css/goal_navbar.css"]

doctype_js = {
	"Project": "public/js/project_goals.js",
	"Goal": "public/js/goals_common.js",
	"Goal Template": "public/js/goals_common.js",
	"Goal Campaign": "public/js/goals_common.js",
}

override_doctype_dashboards = {
	"Project": "dinext_goals.integrations.project.get_dashboard_data",
}

scheduler_events = {
	"daily": ["dinext_goals.tasks.daily"],
}

dinext_goals_metric_providers = {
	"gl_profit": "dinext_goals.providers.gl_profit.provider",
	"project_budget_profit": "dinext_goals.providers.project_budget.provider",
	"timesheet_utilization": "dinext_goals.providers.timesheet_utilization.provider",
	"energy_points": "dinext_goals.providers.energy_points.provider",
}

workflow_approval_fingerprint_excluded_fields = [
	{
		"Goal": [
			"progress",
			"current_value",
			"achievement_percent",
			"planned_progress",
			"deviation",
			"rag_status",
			"is_overdue",
			"last_calculated_on",
			"coefficient",
			"result_value",
			"approver_users",
			"goal_projects",
			"status",
		],
	}
]
