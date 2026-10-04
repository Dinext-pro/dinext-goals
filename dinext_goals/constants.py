MODULE = "Dinext Goals"

GOAL = "Goal"
GOAL_PARENT = "Goal Parent"
GOAL_PARAMETER = "Goal Parameter"
GOAL_LOG = "Goal Log"
GOAL_TEMPLATE = "Goal Template"
GOAL_CAMPAIGN = "Goal Campaign"
SETTINGS = "Goals Settings"

ROLE_MANAGER = "Goal Manager"
ROLE_OWNER = "Goal Owner"
ROLE_APPROVER = "Goal Approver"
ROLE_FINANCE = "Goal Finance Approver"
GOAL_ROLES = (ROLE_MANAGER, ROLE_OWNER, ROLE_APPROVER, ROLE_FINANCE)

WORKFLOW_NAME = "Goal Approval"
STATE_DRAFT = "Draft"
STATE_PARENT_APPROVAL = "Parent Approval"
STATE_FINANCE_APPROVAL = "Finance Approval"
STATE_APPROVED = "Approved"
ACTION_SUBMIT = "Submit for Approval"
ACTION_APPROVE = "Approve"
ACTION_REJECT = "Reject"

STATUS_DRAFT = "Draft"
STATUS_FOR_APPROVAL = "For Approval"
STATUS_ACTIVE = "Active"
STATUS_ON_HOLD = "On Hold"
STATUS_CLOSED = "Closed"
STATUS_CANCELLED = "Cancelled"
LIVE_STATUSES = (STATUS_ACTIVE, STATUS_ON_HOLD)

STATE_TO_STATUS = {
	STATE_DRAFT: STATUS_DRAFT,
	STATE_PARENT_APPROVAL: STATUS_FOR_APPROVAL,
	STATE_FINANCE_APPROVAL: STATUS_FOR_APPROVAL,
	STATE_APPROVED: STATUS_ACTIVE,
}

# action -> (allowed source statuses, target status)
LIFECYCLE_ACTIONS = {
	"hold": ((STATUS_ACTIVE,), STATUS_ON_HOLD),
	"resume": ((STATUS_ON_HOLD,), STATUS_ACTIVE),
	"close": ((STATUS_ACTIVE, STATUS_ON_HOLD), STATUS_CLOSED),
	"cancel": ((STATUS_ACTIVE, STATUS_ON_HOLD), STATUS_CANCELLED),
}

DRAFT_ONLY_FIELDS = (
	"exp_start_date",
	"exp_end_date",
	"priority",
	"baseline",
	"target",
	"target_source",
	"target_provider",
	"metric_type",
	"is_group",
	"weight",
)

CALCULATED_FIELDS = (
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
)

RAG_GREEN = "Green"
RAG_YELLOW = "Yellow"
RAG_RED = "Red"

LOG_SOURCE_MANUAL = "Manual"
LOG_SOURCE_AUTO = "Auto"
