// Copyright (c) 2026, Dinext and contributors
// For license information, please see license.txt

// Shared by the Goal, Goal Template and Goal Campaign forms (hooks.py doctype_js).
frappe.provide("dinext_goals");
frappe.require("/assets/dinext_goals/css/goals.css");

dinext_goals.PARAM_FIELDTYPES = {
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

dinext_goals.load_providers = function () {
	if (!dinext_goals._providers) {
		dinext_goals._providers = frappe
			.xcall("dinext_goals.api.list_metric_providers")
			.then((rows) => rows || [])
			.catch((error) => {
				dinext_goals._providers = null;
				throw error;
			});
	}
	return dinext_goals._providers;
};

dinext_goals.provider_options = function (providers, kind) {
	const rows = kind === "target" ? providers.filter((p) => p.supports_target) : providers;
	return [
		{ value: "", label: "" },
		...rows.map((p) => ({ value: p.key, label: p.available ? p.label : `${p.label} (${__("unavailable")})` })),
	];
};

dinext_goals.provider_card = function (providers, key, kind, fallback_key) {
	const esc = frappe.utils.escape_html;
	if (!key && kind === "target") {
		const fallback = providers.find((p) => p.key === fallback_key);
		const name = fallback ? `<b>${esc(fallback.label)}</b>` : __("the metric provider");
		return `<div class="dinext-goal-provider-card text-muted small" data-testid="target-provider-info">${__(
			"The target is calculated by {0}.",
			[name]
		)}</div>`;
	}
	const provider = providers.find((p) => p.key === key);
	if (!provider) {
		return key
			? `<div class="alert alert-warning small">${__("Metric provider {0} is not registered", [esc(key)])}</div>`
			: "";
	}
	const flags = [
		provider.available
			? `<span class="indicator-pill green">${__("Available")}</span>`
			: `<span class="indicator-pill red">${__("Unavailable on this site")}</span>`,
		provider.supports_target
			? `<span class="indicator-pill blue">${__("Can calculate the target")}</span>`
			: `<span class="indicator-pill gray">${__("Fact only")}</span>`,
	].join(" ");
	const details = (provider.details || []).map((line) => `<li>${esc(line)}</li>`).join("");
	const params = (provider.params || [])
		.map(
			(p) => `<tr>
				<td><code>${esc(p.code)}</code></td>
				<td>${esc(__(p.param_type))}${p.link_doctype ? ` (${esc(__(p.link_doctype))})` : ""}</td>
				<td>${p.required ? __("Required") : __("Optional")}</td>
			</tr>`
		)
		.join("");
	return `<div class="dinext-goal-provider-card" data-testid="${kind}-provider-info" data-provider="${esc(provider.key)}">
		<div class="dinext-goal-provider-head"><b>${esc(provider.label)}</b> <span class="text-muted">${esc(provider.key)}</span></div>
		<div class="dinext-goal-provider-flags">${flags}</div>
		<div class="text-muted">${esc(provider.description || "")}</div>
		${details ? `<ul class="dinext-goal-provider-details">${details}</ul>` : ""}
		${
			params
				? `<table class="table table-sm table-bordered dinext-goal-provider-params">
					<thead><tr><th>${__("Parameter")}</th><th>${__("Type")}</th><th></th></tr></thead>
					<tbody>${params}</tbody>
				</table>`
				: `<div class="text-muted small">${__("No parameters")}</div>`
		}
	</div>`;
};

// fields: {metric, target} jQuery wrappers of the *_provider_info HTML fields.
dinext_goals.render_provider_cards = function (fields, doc, providers) {
	if (fields.metric) {
		fields.metric.html(
			doc.metric_source === "Provider" ? dinext_goals.provider_card(providers, doc.metric_provider, "metric") : ""
		);
	}
	if (fields.target) {
		fields.target.html(
			doc.target_source === "Provider"
				? dinext_goals.provider_card(providers, doc.target_provider, "target", doc.metric_provider)
				: ""
		);
	}
};

dinext_goals.param_field = function (param) {
	const field = {
		fieldname: `param__${param.code}`,
		label: __(param.label || param.code),
		fieldtype: dinext_goals.PARAM_FIELDTYPES[param.param_type] || "Data",
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
};

// Dialog values of param_field() fields, keyed by parameter code.
dinext_goals.param_values = function (params, values, { skip_blank = false } = {}) {
	const result = {};
	params.forEach((param) => {
		let value = values[`param__${param.code}`];
		if (param.param_type === "Percent" && value !== undefined && value !== null && value !== "") {
			value = Number(value);
		}
		const blank = value === undefined || value === null || value === "" || (Array.isArray(value) && !value.length);
		if (value !== undefined && !(skip_blank && blank)) {
			result[param.code] = value;
		}
	});
	return result;
};
