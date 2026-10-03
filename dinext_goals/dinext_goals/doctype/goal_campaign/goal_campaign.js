// Copyright (c) 2026, Dinext and contributors
// For license information, please see license.txt

(function () {
	const CAMPAIGN = "dinext_goals.campaigns";
	const REALTIME_EVENT = "dinext_goals_campaign_done";
	const ROW_COLORS = { Pending: "gray", Created: "green", Skipped: "orange", Error: "red" };
	const esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));

	frappe.ui.form.on("Goal Campaign", {
		setup(frm) {
			frm.set_query("default_template", () => ({ filters: { is_active: 1 } }));
			frm.set_query("template", "items", () => ({ filters: { is_active: 1 } }));
			const group_goals = () => ({ filters: { is_group: 1, status: ["not in", ["Closed", "Cancelled"]] } });
			frm.set_query("default_parent_goal", group_goals);
			frm.set_query("parent_goal", "items", group_goals);
			frm.set_query("goal_owner", "items", () => ({ query: "frappe.core.doctype.user.user.user_query" }));
		},

		onload(frm) {
			if (frm.is_new() && !frm.doc.period_start) {
				update_period(frm);
			}
		},

		refresh(frm) {
			update_parent_row_options(frm);
			add_buttons(frm);
			render_preview(frm, frm.__preview);
			frappe.realtime.off(REALTIME_EVENT);
			frappe.realtime.on(REALTIME_EVENT, (data) => {
				if (data && data.name === frm.doc.name) {
					show_summary(data);
					frm.reload_doc();
				}
			});
		},

		period_type(frm) {
			update_period(frm, true);
		},

		period_start(frm) {
			update_period(frm);
		},

		period_end(frm) {
			if (frm.doc.period_type === "Custom") {
				update_period(frm);
			}
		},

		items_remove(frm) {
			update_parent_row_options(frm);
		},
	});

	frappe.ui.form.on("Goal Campaign Item", {
		items_add(frm, cdt, cdn) {
			const row = locals[cdt][cdn];
			row.row_key = next_row_key(frm);
			if (frm.doc.default_template && !row.template) {
				row.template = frm.doc.default_template;
			}
			frm.refresh_field("items");
			update_parent_row_options(frm);
		},

		goal_owner(frm) {
			update_parent_row_options(frm);
		},

		template(frm, cdt, cdn) {
			frappe.model.set_value(cdt, cdn, "parameter_values", null);
			frappe.model.set_value(cdt, cdn, "parameter_summary", "");
		},
	});

	function update_period(frm, reset_start) {
		if (!frm.doc.period_type) {
			return;
		}
		const args = { period_type: frm.doc.period_type };
		if (frm.doc.period_start && !reset_start) {
			args.period_start = frm.doc.period_start;
		}
		if (frm.doc.period_type === "Custom" && frm.doc.period_end) {
			args.period_end = frm.doc.period_end;
		}
		frappe.xcall(`${CAMPAIGN}.period_info`, args).then((info) => {
			const values = {};
			["period_start", "period_end", "period_label"].forEach((field) => {
				if (frm.doc[field] !== info[field]) {
					values[field] = info[field];
				}
			});
			if (Object.keys(values).length) {
				frm.set_value(values);
			}
		});
	}

	function next_row_key(frm) {
		const numbers = (frm.doc.items || []).map((row) => parseInt((row.row_key || "").replace(/^R/, ""), 10) || 0);
		return `R${Math.max(0, ...numbers) + 1}`;
	}

	function row_title(row) {
		return [row.row_key, row.owner_name || row.goal_owner, row.template].filter(Boolean).join(" · ");
	}

	function update_parent_row_options(frm) {
		const options = [{ value: "", label: "" }].concat(
			(frm.doc.items || []).filter((row) => row.row_key).map((row) => ({ value: row.row_key, label: row_title(row) }))
		);
		frm.fields_dict.items.grid.update_docfield_property("parent_row", "options", options);
	}

	function can_edit(frm) {
		return !frm.is_new() && frm.perm && frm.perm[0] && frm.perm[0].write;
	}

	function add_buttons(frm) {
		if (!frm.perm || !frm.perm[0] || !frm.perm[0].write) {
			return;
		}
		const team = __("Add Team");
		frm.add_custom_button(__("Users"), () => add_users_dialog(frm), team);
		frm.add_custom_button(__("Cost Center Team"), () => add_team_dialog(frm, "Cost Center"), team);
		frm.add_custom_button(__("Department"), () => add_team_dialog(frm, "Department"), team);

		const rows = __("Selected Rows");
		frm.add_custom_button(__("Set Parameters"), () => parameters_dialog(frm), rows);
		frm.add_custom_button(__("Set Template"), () => template_dialog(frm), rows);
		frm.add_custom_button(__("Set Parent"), () => parent_dialog(frm), rows);

		if (!can_edit(frm)) {
			return;
		}
		frm.add_custom_button(__("Preview"), () => with_saved(frm).then(() => load_preview(frm)));
		if (frm.doc.status !== "Created" && (frm.doc.items || []).length) {
			frm.add_custom_button(__("Create Goals"), () => create_goals(frm)).addClass("btn-primary");
		}
		frm.add_custom_button(__("Next Period"), () => copy_to_next_period(frm));
		if ((frm.doc.items || []).some((row) => row.root_goal)) {
			frm.add_custom_button(__("Goal Map"), () => {
				frappe.route_options = {
					status: ["Draft", "For Approval", "Active"],
					period_from: (frm.doc.period_start || "").slice(0, 7),
					period_to: (frm.doc.period_end || "").slice(0, 7),
				};
				frappe.set_route("goal-map");
			});
		}
	}

	function with_saved(frm) {
		return frm.is_dirty() ? frm.save() : Promise.resolve();
	}

	function add_rows(frm, users, template) {
		const existing = new Set((frm.doc.items || []).map((row) => `${row.goal_owner}\n${row.template}`));
		let added = 0;
		users.forEach((user) => {
			if (existing.has(`${user}\n${template}`)) {
				return;
			}
			existing.add(`${user}\n${template}`);
			const row = frm.add_child("items", { goal_owner: user, template, row_key: next_row_key(frm) });
			frappe.model.set_value(row.doctype, row.name, "goal_owner", user);
			added += 1;
		});
		frm.refresh_field("items");
		update_parent_row_options(frm);
		frappe.show_alert({
			message: __("{0} rows added, {1} already listed", [added, users.length - added]),
			indicator: added ? "green" : "orange",
		});
	}

	function template_field(frm) {
		return {
			fieldname: "template",
			fieldtype: "Link",
			options: "Goal Template",
			label: __("Template"),
			reqd: 1,
			default: frm.doc.default_template,
			get_query: () => ({ filters: { is_active: 1 } }),
		};
	}

	function add_users_dialog(frm) {
		const dialog = new frappe.ui.Dialog({
			title: __("Add Users"),
			fields: [
				template_field(frm),
				{
					fieldname: "users",
					fieldtype: "MultiSelectList",
					label: __("Users"),
					reqd: 1,
					get_data: (txt) => frappe.db.get_link_options("User", txt, { enabled: 1, user_type: "System User" }),
				},
			],
			primary_action_label: __("Add"),
			primary_action(values) {
				dialog.hide();
				add_rows(frm, values.users || [], values.template);
			},
		});
		dialog.show();
	}

	function add_team_dialog(frm, source) {
		const dialog = new frappe.ui.Dialog({
			title: source === "Cost Center" ? __("Add Cost Center Team") : __("Add Department Employees"),
			fields: [
				template_field(frm),
				{
					fieldname: "value",
					fieldtype: "Link",
					options: source,
					label: __(source),
					reqd: 1,
				},
				{
					fieldname: "on_date",
					fieldtype: "Date",
					label: __("Team On"),
					default: frm.doc.period_start,
					depends_on: `eval:${source === "Cost Center"}`,
					description: __("Workers whose latest cost center assignment on this date is in the cost center or its children."),
				},
				{ fieldname: "team_html", fieldtype: "HTML" },
			],
			primary_action_label: __("Add"),
			primary_action(values) {
				frappe
					.xcall(`${CAMPAIGN}.get_team`, { source, value: values.value, on_date: values.on_date })
					.then((team) => {
						if (!team.length) {
							frappe.msgprint(__("No users found"));
							return;
						}
						dialog.hide();
						add_rows(
							frm,
							team.map((member) => member.user),
							values.template
						);
					});
			},
		});
		dialog.show();
	}

	function selected_rows(frm) {
		const names = frm.fields_dict.items.grid.get_selected_children().map((row) => row.name);
		const rows = (frm.doc.items || []).filter((row) => names.includes(row.name));
		if (!rows.length) {
			frappe.msgprint(__("Select rows in the table first"));
		}
		return rows;
	}

	function parse_values(row) {
		if (!row.parameter_values) {
			return {};
		}
		if (typeof row.parameter_values === "object") {
			return row.parameter_values;
		}
		try {
			return JSON.parse(row.parameter_values) || {};
		} catch (e) {
			return {};
		}
	}

	function percent_default(param, value) {
		// param_field() treats a numeric Percent default as a fraction; row values are already percents.
		return param.param_type === "Percent" && typeof value === "number" ? value / 100 : value;
	}

	async function parameters_dialog(frm) {
		const rows = selected_rows(frm);
		if (!rows.length) {
			return;
		}
		const templates = [...new Set(rows.map((row) => row.template))];
		if (templates.length !== 1) {
			frappe.msgprint(__("Select rows of one template to set its parameters"));
			return;
		}
		const params = await frappe.xcall("dinext_goals.api.get_template_dialog_fields", { template: templates[0] });
		if (!params.length) {
			frappe.msgprint(__("Template {0} has no parameters asked on create", [templates[0]]));
			return;
		}
		const current = rows.length === 1 ? parse_values(rows[0]) : {};
		const fields = params.map((param) =>
			dinext_goals.param_field(
				param.code in current ? { ...param, default: percent_default(param, current[param.code]) } : param
			)
		);
		const dialog = new frappe.ui.Dialog({
			title:
				rows.length === 1
					? __("Parameters of {0}", [row_title(rows[0])])
					: __("Parameters of {0} rows", [rows.length]),
			fields: [
				{
					fieldname: "intro",
					fieldtype: "HTML",
					options: `<div class="text-muted small">${
						rows.length === 1
							? __("Empty values are inherited from the parent goal or taken from the template.")
							: __("Filled values are set on every selected row; empty values keep the row values.")
					}</div>`,
				},
				...fields,
			],
			size: "large",
			primary_action_label: __("Apply"),
			primary_action(values) {
				const update = dinext_goals.param_values(params, values, { skip_blank: rows.length > 1 });
				rows.forEach((row) => {
					const merged = rows.length === 1 ? update : { ...parse_values(row), ...update };
					Object.keys(merged).forEach((code) => {
						const value = merged[code];
						if (value === null || value === "" || (Array.isArray(value) && !value.length)) {
							delete merged[code];
						}
					});
					frappe.model.set_value(row.doctype, row.name, "parameter_values", JSON.stringify(merged));
					frappe.model.set_value(row.doctype, row.name, "parameter_summary", summary(params, merged));
				});
				dialog.hide();
			},
		});
		dialog.show();
	}

	function summary(params, values) {
		return params
			.filter((param) => param.code in values)
			.map((param) => {
				let value = values[param.code];
				if (Array.isArray(value)) value = value.join(", ");
				if (param.param_type === "Percent") value = `${value}%`;
				return `${__(param.label || param.code)}: ${value}`;
			})
			.join("; ");
	}

	function template_dialog(frm) {
		const rows = selected_rows(frm);
		if (!rows.length) {
			return;
		}
		frappe.prompt([template_field(frm)], (values) => {
			rows.forEach((row) => frappe.model.set_value(row.doctype, row.name, "template", values.template));
			update_parent_row_options(frm);
		}, __("Template of {0} rows", [rows.length]));
	}

	function parent_dialog(frm) {
		const rows = selected_rows(frm);
		if (!rows.length) {
			return;
		}
		const selected = new Set(rows.map((row) => row.row_key));
		const options = [{ value: "", label: "" }].concat(
			(frm.doc.items || [])
				.filter((row) => row.row_key && !selected.has(row.row_key))
				.map((row) => ({ value: row.row_key, label: row_title(row) }))
		);
		frappe.prompt(
			[
				{
					fieldname: "parent_row",
					fieldtype: "Select",
					options,
					label: __("Parent Row"),
					description: __("Create under the root goal of another row of this campaign."),
				},
				{
					fieldname: "parent_goal",
					fieldtype: "Link",
					options: "Goal",
					label: __("Parent Goal", null, "Goal"),
					depends_on: "eval:!doc.parent_row",
					get_query: () => ({ filters: { is_group: 1, status: ["not in", ["Closed", "Cancelled"]] } }),
				},
			],
			(values) => {
				rows.forEach((row) => {
					frappe.model.set_value(row.doctype, row.name, "parent_row", values.parent_row || "");
					frappe.model.set_value(row.doctype, row.name, "parent_goal", values.parent_row ? "" : values.parent_goal || "");
				});
			},
			__("Parent of {0} rows", [rows.length])
		);
	}

	function load_preview(frm) {
		return frappe.xcall(`${CAMPAIGN}.preview`, { name: frm.doc.name }).then((rows) => {
			frm.__preview = rows || [];
			render_preview(frm, frm.__preview);
			frm.scroll_to_field("preview_html");
			return frm.__preview;
		});
	}

	function render_preview(frm, rows) {
		const field = frm.get_field("preview_html");
		if (!field) {
			return;
		}
		if (!rows) {
			field.$wrapper.html(
				`<div class="text-muted small">${__("Press Preview to check the goals before creating them.")}</div>`
			);
			return;
		}
		if (!rows.length) {
			field.$wrapper.html(`<div class="text-muted small">${__("No rows")}</div>`);
			return;
		}
		const warnings = rows.reduce((count, row) => count + row.warnings.length, 0);
		const body = rows
			.map((row) => {
				const parent = row.parent_row
					? `${__("Row", null, "Goal Campaign")} ${esc(row.parent_row)}`
					: row.parent_goal
					? `<a href="/app/goal/${encodeURIComponent(row.parent_goal)}">${esc(row.parent_goal)}</a>`
					: "";
				const status = row.root_goal
					? `<a href="/app/goal/${encodeURIComponent(row.root_goal)}">${esc(__(row.status))}</a>`
					: esc(__(row.status));
				const notes = row.warnings.map((text) => `<div class="text-warning">${esc(text)}</div>`).join("");
				return `<tr data-row="${esc(row.row_key)}">
					<td>${esc(row.row_key)}</td>
					<td>${esc(row.owner_name)}</td>
					<td>${esc(row.template)}</td>
					<td>${(row.subjects || []).map(esc).join("<br>")}${row.goal_count ? ` <span class="text-muted">(${__("{0} goals", [row.goal_count])})</span>` : ""}</td>
					<td><code>${esc(row.code_prefix || "")}</code></td>
					<td>${frappe.datetime.str_to_user(row.period_start)} – ${frappe.datetime.str_to_user(row.period_end)}</td>
					<td>${parent}</td>
					<td><span class="indicator-pill ${ROW_COLORS[row.status] || "gray"}">${status}</span>${notes}</td>
				</tr>`;
			})
			.join("");
		field.$wrapper.html(`
			<div class="dinext-goal-campaign-preview" data-testid="campaign-preview">
				<div class="small ${warnings ? "text-warning" : "text-success"}">${
					warnings ? __("{0} warnings", [warnings]) : __("No warnings")
				}</div>
				<table class="table table-sm table-bordered">
					<thead><tr>
						<th>${__("Row", null, "Goal Campaign")}</th><th>${__("Goal Owner")}</th><th>${__("Template")}</th>
						<th>${__("Root Goals")}</th><th>${__("Goal Code Prefix")}</th><th>${__("Period")}</th>
						<th>${__("Parent")}</th><th>${__("Status")}</th>
					</tr></thead>
					<tbody>${body}</tbody>
				</table>
			</div>`);
	}

	function show_summary(summary) {
		frappe.msgprint({
			title: __("Goals Created"),
			indicator: summary.errors ? "orange" : "green",
			message: __("Rows created: {0}, goals: {1}, skipped: {2}, errors: {3}", [
				summary.rows,
				summary.goals,
				summary.skipped,
				summary.errors,
			]),
		});
	}

	function create_goals(frm) {
		with_saved(frm)
			.then(() => load_preview(frm))
			.then((rows) => {
				const pending = rows.filter((row) => row.status !== "Created").length;
				const warnings = rows.reduce((count, row) => count + row.warnings.length, 0);
				const message = warnings
					? __("Create goals for {0} rows? The preview has {1} warnings.", [pending, warnings])
					: __("Create goals for {0} rows?", [pending]);
				frappe.confirm(message, () =>
					frappe
						.call({
							method: `${CAMPAIGN}.create`,
							args: { name: frm.doc.name },
							freeze: true,
							freeze_message: __("Creating goals..."),
						})
						.then((r) => {
							const result = r.message || {};
							if (result.queued) {
								frappe.show_alert({
									message: __("Creating goals for {0} rows in the background", [result.rows]),
									indicator: "blue",
								});
								return;
							}
							frm.__preview = null;
							show_summary(result);
							frm.reload_doc();
						})
				);
			});
	}

	function copy_to_next_period(frm) {
		with_saved(frm).then(() =>
			frappe.xcall(`${CAMPAIGN}.copy_to_next_period`, { name: frm.doc.name }).then((name) => {
				frappe.show_alert({ message: __("Campaign {0} created", [name]), indicator: "green" });
				frappe.set_route("Form", "Goal Campaign", name);
			})
		);
	}
})();
