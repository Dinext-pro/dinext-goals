// Copyright (c) 2026, Dinext and contributors
// For license information, please see license.txt

frappe.ui.form.on("Goal Template", {
	setup(frm) {
		dinext_goals.load_providers().then((rows) => {
			const grid = frm.fields_dict.items.grid;
			grid.update_docfield_property("metric_provider", "options", dinext_goals.provider_options(rows, "metric"));
			grid.update_docfield_property("target_provider", "options", dinext_goals.provider_options(rows, "target"));
		});
	},

	refresh(frm) {
		if (frm.is_new() || !frm.doc.is_active || !frappe.model.can_create("Goal")) {
			return;
		}
		frm.add_custom_button(__("Create Goals"), () => dinext_goals_open_create_dialog(frm)).addClass(
			"btn-primary"
		);
		if (frappe.model.can_create("Goal Campaign")) {
			frm.add_custom_button(__("Bulk Create"), () =>
				frappe.new_doc("Goal Campaign", { default_template: frm.doc.name })
			);
		}
	},
});

frappe.ui.form.on("Goal Template Item", {
	form_render(frm, cdt, cdn) {
		dinext_goals_render_item_providers(frm, cdt, cdn);
	},
	metric_source: dinext_goals_render_item_providers,
	metric_provider: dinext_goals_render_item_providers,
	target_source: dinext_goals_render_item_providers,
	target_provider: dinext_goals_render_item_providers,
});

function dinext_goals_render_item_providers(frm, cdt, cdn) {
	const row = frm.fields_dict.items.grid.grid_rows_by_docname[cdn];
	const form = row && row.grid_form;
	if (!form) {
		return;
	}
	const wrapper = (fieldname) => form.fields_dict[fieldname] && form.fields_dict[fieldname].$wrapper;
	dinext_goals.load_providers().then((providers) =>
		dinext_goals.render_provider_cards(
			{ metric: wrapper("metric_provider_info"), target: wrapper("target_provider_info") },
			locals[cdt][cdn],
			providers
		)
	);
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
		params.forEach((param) => fields.push(dinext_goals.param_field(param)));
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Create Goals from {0}", [frm.doc.template_name]),
		fields,
		size: "large",
		primary_action_label: __("Create"),
		primary_action: async (values) => {
			const paramValues = dinext_goals.param_values(params, values);
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
