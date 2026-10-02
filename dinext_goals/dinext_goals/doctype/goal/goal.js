// Copyright (c) 2026, Dinext and contributors
// For license information, please see license.txt

(function () {
	const ECHARTS_ASSET = "/assets/dinext_common/js/echarts.min.js";
	const GOALS_CSS = "/assets/dinext_goals/css/goals.css";
	const TREND_ID = "dinext-goal-trend";
	const FROZEN = ["Closed", "Cancelled"];
	const LIFECYCLE = [
		{ action: "hold", label: "Put On Hold", from: ["Active"] },
		{ action: "resume", label: "Resume", from: ["On Hold"] },
		{
			action: "close",
			label: "Close Goal",
			from: ["Active", "On Hold"],
			confirm: "Close this goal? Its values will no longer be recalculated.",
		},
		{
			action: "cancel",
			label: "Cancel Goal",
			from: ["Active", "On Hold"],
			confirm: "Cancel this goal? It will be excluded from the roll-up of its parents.",
		},
	];
	const COLORS = { actual: "#1b3bff", planned: "#c482f7", value: "#16a34a", valuePlan: "#86efac" };
	let providers = null;

	frappe.ui.form.on("Goal", {
		setup(frm) {
			frm.set_query("parent_goal", "parents", () => ({
				filters: { is_group: 1, name: ["!=", frm.doc.name || ""] },
			}));
			frm.set_query("goal_owner", () => ({ query: "frappe.core.doctype.user.user.user_query" }));
		},

		refresh(frm) {
			frappe.require(GOALS_CSS);
			load_providers().then(() => {
				set_provider_options(frm);
				render_effective_params(frm);
			});
			add_buttons(frm);
			render_children(frm);
			render_headline(frm);
			render_trend(frm);
		},

		metric_provider(frm) {
			render_effective_params(frm);
		},

		target_provider(frm) {
			render_effective_params(frm);
		},
	});

	function load_providers() {
		if (providers) {
			return Promise.resolve(providers);
		}
		return frappe.xcall("dinext_goals.api.list_metric_providers").then((rows) => {
			providers = rows || [];
			return providers;
		});
	}

	function provider_option(p) {
		return { value: p.key, label: p.available ? p.label : `${p.label} (${__("unavailable")})` };
	}

	function set_provider_options(frm) {
		frm.set_df_property("metric_provider", "options", (providers || []).map(provider_option));
		frm.set_df_property("target_provider", "options", (providers || []).filter((p) => p.supports_target).map(provider_option));
	}

	function can_write(frm) {
		return !frm.is_new() && frm.perm && frm.perm[0] && frm.perm[0].write;
	}

	function add_buttons(frm) {
		if (frm.is_new()) {
			return;
		}
		const status = frm.doc.status;
		if (can_write(frm) && !FROZEN.includes(status)) {
			frm.add_custom_button(__("Recalculate Progress"), () => recalculate(frm));
		}
		if (frm.doc.is_group && !FROZEN.includes(status) && frappe.model.can_create("Goal")) {
			frm.add_custom_button(__("Add Child Goal"), () => add_child_goal(frm));
		}
		if (can_write(frm)) {
			LIFECYCLE.filter((item) => item.from.includes(status)).forEach((item) => {
				frm.add_custom_button(__(item.label), () => run_lifecycle(frm, item), __("Status"));
			});
		}
		frm.add_custom_button(__("Goal Map"), () => {
			frappe.route_options = { root: frm.doc.name };
			frappe.set_route("goal-map");
		}, __("View"));
		frm.add_custom_button(__("Goal Log"), () => {
			frappe.route_options = { goal: frm.doc.name };
			frappe.set_route("List", "Goal Log");
		}, __("View"));
		if (frm.doc.is_group && (frappe.user.has_role("Goal Manager") || frappe.user.has_role("System Manager"))) {
			frm.add_custom_button(__("Save as Template"), () => save_as_template(frm), __("Actions"));
		}
	}

	function recalculate(frm) {
		frappe
			.xcall("dinext_goals.api.recalculate", { goal: frm.doc.name }, "POST")
			.then((summary) => {
				const errors = summary.errors || [];
				if (errors.length) {
					frappe.msgprint({
						title: __("Recalculation finished with errors"),
						indicator: "orange",
						message: errors.map((e) => `<b>${frappe.utils.escape_html(e.goal)}</b>: ${frappe.utils.escape_html(e.message)}`).join("<br>"),
					});
				} else {
					frappe.show_alert({
						message: __("Recalculated {0} goals, {1} changed", [summary.recalculated, summary.changed]),
						indicator: "green",
					});
				}
				frm.reload_doc();
			});
	}

	function add_child_goal(frm) {
		frappe.model.with_doctype("Goal", () => {
			const doc = frappe.model.get_new_doc("Goal");
			Object.assign(doc, {
				goal_type: frm.doc.goal_type,
				company: frm.doc.company,
				department: frm.doc.department,
				exp_start_date: frm.doc.exp_start_date,
				exp_end_date: frm.doc.exp_end_date,
				goal_owner: frappe.session.user,
			});
			const row = frappe.model.add_child(doc, "parents");
			row.parent_goal = frm.doc.name;
			row.parent_subject = frm.doc.subject;
			frappe.set_route("Form", "Goal", doc.name);
		});
	}

	function run_lifecycle(frm, item) {
		const go = () =>
			frappe
				.xcall("dinext_goals.api.set_lifecycle_status", { goal: frm.doc.name, action: item.action }, "POST")
				.then(() => frm.reload_doc());
		if (item.confirm) {
			frappe.confirm(__(item.confirm), go);
		} else {
			go();
		}
	}

	function save_as_template(frm) {
		frappe.prompt(
			[{ fieldname: "template_name", fieldtype: "Data", label: __("Template Name"), reqd: 1, default: frm.doc.subject }],
			(values) =>
				frappe
					.xcall("dinext_goals.api.save_as_template", { goal: frm.doc.name, template_name: values.template_name }, "POST")
					.then((name) => frappe.set_route("Form", "Goal Template", name)),
			__("Save as Template"),
			__("Save")
		);
	}

	function esc(value) {
		return frappe.utils.escape_html(value == null ? "" : String(value));
	}

	function rag_class(rag) {
		return rag ? `dinext-goal-rag-${String(rag).toLowerCase()}` : "dinext-goal-rag-none";
	}

	function fmt_number(value) {
		return format_number(value || 0, null, 2);
	}

	function render_headline(frm) {
		if (frm.is_new() || !frm.dashboard) {
			return;
		}
		const d = frm.doc;
		const parts = [
			`<span class="dinext-goal-rag-dot ${rag_class(d.rag_status)}"></span>`,
			`<b>${esc(__(d.rag_status || "No RAG status"))}</b>`,
			__("Progress {0}% of planned {1}%", [fmt_number(d.progress), fmt_number(d.planned_progress)]),
		];
		if (d.result_formula && d.result_label) {
			parts.push(`${esc(d.result_label)}: <b>${fmt_number(d.result_value)}</b>`);
		}
		if (d.is_overdue) {
			parts.push(`<span class="text-danger">${__("Overdue")}</span>`);
		}
		frm.dashboard.set_headline(`<div class="dinext-goal-headline">${parts.join(" · ")}</div>`);
	}

	function render_children(frm) {
		const field = frm.get_field("children_html");
		if (!field || frm.is_new() || !frm.doc.is_group) {
			return;
		}
		frappe.xcall("dinext_goals.api.get_children", { goal: frm.doc.name }).then((rows) => {
			if (!rows || !rows.length) {
				field.$wrapper.html(`<div class="text-muted small">${__("No child goals yet")}</div>`);
				return;
			}
			const body = rows
				.map(
					(row) => `
				<div class="dinext-goal-child">
					<div class="dinext-goal-child-title">
						<span class="dinext-goal-rag-dot ${rag_class(row.rag_status)}"></span>
						<a href="/app/goal/${encodeURIComponent(row.name)}">${esc(row.subject)}</a>
						<span class="text-muted small">${esc(row.owner_name)} · ${esc(__(row.status))} · ${__("weight")} ${fmt_number(row.weight)}</span>
					</div>
					<div class="dinext-goal-progress" title="${__("Planned", null, "Goal")}: ${fmt_number(row.planned_progress)}%">
						<div class="dinext-goal-progress-bar ${rag_class(row.rag_status)}" style="width:${Math.max(0, Math.min(100, row.progress || 0))}%"></div>
						<div class="dinext-goal-progress-plan" style="left:${Math.max(0, Math.min(100, row.planned_progress || 0))}%"></div>
					</div>
					<div class="dinext-goal-child-value">${fmt_number(row.progress)}%</div>
				</div>`
				)
				.join("");
			field.$wrapper.html(`<div class="dinext-goal-children">${body}</div>`);
		});
	}

	function render_effective_params(frm) {
		const field = frm.get_field("effective_parameters_html");
		if (!field) {
			return;
		}
		if (frm.is_new()) {
			field.$wrapper.html(`<div class="text-muted small">${__("Save the goal to see effective parameters")}</div>`);
			return;
		}
		frappe.xcall("dinext_goals.api.get_effective_parameters", { goal: frm.doc.name }).then((rows) => {
			rows = rows || [];
			const codes = new Set(rows.map((r) => r.code));
			const used = new Set();
			if (frm.doc.metric_source === "Provider" && frm.doc.metric_provider) {
				used.add(frm.doc.metric_provider);
			}
			if (frm.doc.target_source === "Provider" && (frm.doc.target_provider || frm.doc.metric_provider)) {
				used.add(frm.doc.target_provider || frm.doc.metric_provider);
			}
			const warning = (providers || [])
				.filter((p) => used.has(p.key))
				.map((provider) => {
					const missing = (provider.params || []).filter((p) => p.required && !codes.has(p.code)).map((p) => p.code);
					return missing.length
						? `<div class="alert alert-warning small">${__("Metric provider {0} needs parameters: {1}", [esc(provider.label), esc(missing.join(", "))])}</div>`
						: "";
				})
				.join("");
			if (!rows.length) {
				field.$wrapper.html(`${warning}<div class="text-muted small">${__("No parameters")}</div>`);
				return;
			}
			const body = rows
				.map((r) => {
					const source = r.inherited
						? `<a href="/app/goal/${encodeURIComponent(r.source)}">${esc(r.source_title || r.source)}</a>`
						: `<span class="text-muted">${__("This goal")}</span>`;
					return `<tr>
						<td><code>${esc(r.code)}</code></td>
						<td>${esc(__(r.label))}</td>
						<td>${esc(__(r.param_type))}</td>
						<td>${esc(r.value)}</td>
						<td>${source}</td>
						<td>${r.editable_when_active ? __("Yes") : ""}</td>
					</tr>`;
				})
				.join("");
			field.$wrapper.html(`${warning}
				<table class="table table-sm table-bordered dinext-goal-params">
					<thead><tr>
						<th>${__("Code")}</th><th>${__("Label")}</th><th>${__("Type")}</th>
						<th>${__("Value")}</th><th>${__("Source", null, "Goal Parameter")}</th><th>${__("Editable When Active")}</th>
					</tr></thead>
					<tbody>${body}</tbody>
				</table>`);
		});
	}

	function render_trend(frm) {
		let wrapper = frm.$wrapper.find(`#${TREND_ID}`);
		if (frm.is_new()) {
			dispose_trend(wrapper);
			return;
		}
		if (!wrapper.length) {
			const section = frm.dashboard.add_section("", __("Plan and Actual"), "dinext-goal-trend-section");
			wrapper = $(`<div id="${TREND_ID}" class="dinext-goal-trend">
				<div class="dinext-goal-trend-state text-muted small">${__("Loading chart...")}</div>
				<div class="dinext-goal-trend-chart"></div>
			</div>`);
			section.append(wrapper);
			frm.dashboard.show();
		}
		frappe.require([ECHARTS_ASSET], () => {
			frappe.xcall("dinext_goals.api.get_goal_trend", { goal: frm.doc.name }).then((data) => {
				wrapper.data("trend", data);
				draw_trend(wrapper, data);
				watch_theme(wrapper);
			});
		});
	}

	function dispose_trend(wrapper) {
		if (!wrapper || !wrapper.length) {
			return;
		}
		const chart = wrapper.data("chart");
		if (chart) {
			chart.dispose();
		}
		const observer = wrapper.data("observer");
		if (observer) {
			observer.disconnect();
		}
		wrapper.closest(".dinext-goal-trend-section").remove();
	}

	function is_dark() {
		const attrs = [
			document.documentElement.getAttribute("data-theme"),
			document.documentElement.getAttribute("data-theme-mode"),
		]
			.filter(Boolean)
			.join(" ")
			.toLowerCase();
		return attrs.includes("dark");
	}

	function palette() {
		const styles = getComputedStyle(document.documentElement);
		const dark = is_dark();
		const cssVar = (name, fallback) => (styles.getPropertyValue(name) || "").trim() || fallback;
		return {
			text: cssVar("--text-color", dark ? "#e5e7eb" : "#1f2937"),
			muted: cssVar("--text-muted", dark ? "#a3aab8" : "#6b7280"),
			axis: cssVar("--border-color", dark ? "#3f4653" : "#cbd5e1"),
			split: dark ? "rgba(229, 231, 235, 0.12)" : "rgba(15, 23, 42, 0.12)",
			tooltipBg: dark ? "rgba(24, 28, 36, 0.96)" : "rgba(255, 255, 255, 0.96)",
			tooltipText: dark ? "#f9fafb" : "#1f2937",
			today: dark ? "rgba(229, 231, 235, 0.6)" : "rgba(15, 23, 42, 0.6)",
		};
	}

	function ts(value) {
		return value ? frappe.datetime.str_to_obj(value).getTime() : null;
	}

	function draw_trend(wrapper, data) {
		const state = wrapper.find(".dinext-goal-trend-state");
		const dom = wrapper.find(".dinext-goal-trend-chart")[0];
		if (!data || !data.start || !data.end) {
			state.text(__("Set the expected dates to see the plan")).show();
			return;
		}
		state.hide();
		let chart = wrapper.data("chart");
		if (!chart) {
			chart = echarts.init(dom, null, { renderer: "canvas" });
			wrapper.data("chart", chart);
			$(window).off("resize.dinext_goal_trend").on("resize.dinext_goal_trend", () => chart.resize());
		}
		const theme = palette();
		const start = ts(data.start);
		const end = ts(data.end);
		const today = ts(data.today);
		const logs = data.logs || [];
		const progress = logs.map((row) => [ts(row.log_date), row.progress]);
		const showValue = !data.is_group && data.metric_type && data.metric_type !== "Boolean";
		const unit = data.unit ? ` ${data.unit}` : "";
		const series = [
			{
				name: __("Actual Progress, %"),
				type: "line",
				step: "end",
				data: progress,
				symbolSize: 6,
				lineStyle: { width: 2, color: COLORS.actual },
				itemStyle: { color: COLORS.actual },
				markLine: today
					? {
							symbol: "none",
							silent: true,
							label: { formatter: __("Today"), color: theme.muted },
							lineStyle: { type: "dashed", color: theme.today },
							data: [{ xAxis: today }],
					  }
					: undefined,
			},
			{
				name: __("Planned Progress, %"),
				type: "line",
				data: [
					[start, 0],
					[end, 100],
				],
				symbol: "none",
				lineStyle: { width: 2, type: "dashed", color: COLORS.planned },
				itemStyle: { color: COLORS.planned },
			},
		];
		const yAxis = [
			{
				type: "value",
				name: "%",
				min: 0,
				max: (v) => Math.max(100, Math.ceil(v.max / 10) * 10),
				axisLabel: { color: theme.muted },
				nameTextStyle: { color: theme.text },
				axisLine: { lineStyle: { color: theme.axis } },
				splitLine: { lineStyle: { color: theme.split } },
			},
		];
		if (showValue) {
			yAxis.push({
				type: "value",
				name: data.unit || __("Value"),
				axisLabel: { color: theme.muted },
				nameTextStyle: { color: theme.text },
				axisLine: { lineStyle: { color: theme.axis } },
				splitLine: { show: false },
			});
			series.push(
				{
					name: __("Actual Value") + unit,
					type: "line",
					step: "end",
					yAxisIndex: 1,
					data: logs.map((row) => [ts(row.log_date), row.current_value]),
					symbolSize: 5,
					lineStyle: { width: 2, color: COLORS.value },
					itemStyle: { color: COLORS.value },
				},
				{
					name: __("Planned Value", null, "Goal") + unit,
					type: "line",
					yAxisIndex: 1,
					data: [
						[start, data.baseline],
						[end, data.target],
					],
					symbol: "none",
					lineStyle: { width: 2, type: "dotted", color: COLORS.valuePlan },
					itemStyle: { color: COLORS.valuePlan },
				}
			);
		}
		chart.setOption(
			{
				animation: false,
				grid: { left: 48, right: showValue ? 64 : 24, top: 40, bottom: 36 },
				legend: { top: 0, textStyle: { color: theme.text } },
				tooltip: {
					trigger: "axis",
					backgroundColor: theme.tooltipBg,
					borderColor: theme.axis,
					textStyle: { color: theme.tooltipText },
					valueFormatter: (v) => (v == null ? "" : format_number(v, null, 2)),
				},
				xAxis: {
					type: "time",
					min: Math.min(start, ...progress.map((p) => p[0]).filter(Boolean)),
					max: Math.max(end, today || end),
					axisLabel: { color: theme.muted },
					axisLine: { lineStyle: { color: theme.axis } },
				},
				yAxis,
				series,
			},
			true
		);
		if (!logs.length) {
			state.text(__("No progress history yet")).show();
		}
	}

	function watch_theme(wrapper) {
		if (wrapper.data("observer")) {
			return;
		}
		const redraw = frappe.utils.debounce(() => {
			if (wrapper.closest("body").length) {
				draw_trend(wrapper, wrapper.data("trend"));
			}
		}, 150);
		const observer = new MutationObserver(redraw);
		observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "data-theme-mode", "class"] });
		wrapper.data("observer", observer);
	}
})();
