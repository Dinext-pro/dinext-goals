// Copyright (c) 2026, Dinext and contributors
// For license information, please see license.txt

const GOAL_TEMPLATE_PARAM_FIELDTYPES = {
	Int: "Int",
	Float: "Float",
	Currency: "Currency",
	Percent: "Percent",
	Data: "Data",
	Select: "Select",
	Date: "Date",
	Check: "Check",
	Link: "Link",
	"Link List": "MultiSelectList",
};

frappe.ui.form.on("Goal Template", {
	setup(frm) {
		frappe.call("dinext_goals.api.list_metric_providers").then((r) => {
			const rows = r.message || [];
			const option = (p) => ({ value: p.key, label: p.label });
			frm.fields_dict.items.grid.update_docfield_property("metric_provider", "options", rows.map(option));
			frm.fields_dict.items.grid.update_docfield_property(
				"target_provider",
				"options",
				rows.filter((p) => p.supports_target).map(option)
			);
		});
	},

	refresh(frm) {
		if (frm.is_new() || !frm.doc.is_active || !frappe.model.can_create("Goal")) {
			return;
		}
		frm.add_custom_button(__("Create Goals"), () => dinext_goals_open_create_dialog(frm)).addClass(
			"btn-primary"
		);
	},
});

function dinext_goals_param_field(param) {
	const field = {
		fieldname: `param__${param.code}`,
		label: __(param.label || param.code),
		fieldtype: GOAL_TEMPLATE_PARAM_FIELDTYPES[param.param_type] || "Data",
		description: param.description ? __(param.description) : "",
		default: param.default,
	};
	if (param.param_type === "Select") {
		field.options = ["", ...(param.select_options || "").split("\n").filter(Boolean)].join("\n");
	}
	if (param.param_type === "Link") {
		field.options = param.link_doctype;
	}
	if (param.param_type === "Link List") {
		field.get_data = (txt) => frappe.db.get_link_options(param.link_doctype, txt);
		field.default = Array.isArray(param.default) ? param.default : [];
	}
	if (param.param_type === "Percent" && typeof param.default === "number") {
		field.default = param.default * 100;
	}
	return field;
}

async function dinext_goals_open_create_dialog(frm) {
	const r = await frappe.call("dinext_goals.api.get_template_dialog_fields", { template: frm.doc.name });
	const params = r.message || [];
	const fields = [
		{ fieldname: "start_date", fieldtype: "Date", label: __("Start Date"), reqd: 1, default: frappe.datetime.get_today() },
		{ fieldname: "goal_owner", fieldtype: "Link", options: "User", label: __("Goal Owner"), reqd: 1, default: frappe.session.user },
		{ fieldname: "code_prefix", fieldtype: "Data", label: __("Goal Code Prefix") },
		{ fieldname: "subject_suffix", fieldtype: "Data", label: __("Subject Suffix"), description: __("Appended to every goal subject, e.g. a period or a person.") },
		{ fieldname: "column_break_main", fieldtype: "Column Break" },
		{
			fieldname: "parent_goal",
			fieldtype: "Link",
			options: "Goal",
			label: __("Parent Goal", null, "Goal"),
			get_query: () => ({ filters: { is_group: 1, status: ["not in", ["Closed", "Cancelled"]] } }),
		},
		{ fieldname: "company", fieldtype: "Link", options: "Company", label: __("Company"), default: frappe.defaults.get_user_default("Company") },
	];
	if (params.length) {
		fields.push({ fieldname: "parameters_section", fieldtype: "Section Break", label: __("Parameters") });
		params.forEach((param) => fields.push(dinext_goals_param_field(param)));
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Create Goals from {0}", [frm.doc.template_name]),
		fields,
		size: "large",
		primary_action_label: __("Create"),
		primary_action: async (values) => {
			const paramValues = {};
			params.forEach((param) => {
				let value = values[`param__${param.code}`];
				if (param.param_type === "Percent" && value !== undefined && value !== null && value !== "") {
					value = Number(value);
				}
				if (value !== undefined) {
					paramValues[param.code] = value;
				}
			});
			dialog.disable_primary_action();
			try {
				const res = await frappe.call({
					method: "dinext_goals.api.create_goals_from_template",
					args: {
						template: frm.doc.name,
						start_date: values.start_date,
						goal_owner: values.goal_owner,
						code_prefix: values.code_prefix,
						subject_suffix: values.subject_suffix,
						parent_goal: values.parent_goal,
						company: values.company,
						values: paramValues,
					},
					freeze: true,
					freeze_message: __("Creating goals..."),
				});
				const created = res.message || [];
				dialog.hide();
				frappe.show_alert({ message: __("{0} goals created", [created.length]), indicator: "green" });
				if (created.length) {
					frappe.set_route("Form", "Goal", created[0]);
				}
			} finally {
				dialog.enable_primary_action();
			}
		},
	});
	dialog.show();
}
