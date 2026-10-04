// The user's top-level goal in the Desk toolbar, enabled in Goals Settings.
(function () {
	const METHOD = "dinext_goals.api.get_navbar_goal";
	const REFRESH_MS = 60 * 1000;
	const MAP_STATUSES = ["Draft", "For Approval", "Active", "On Hold"];
	const RAGS = ["green", "yellow", "red"];
	let loaded_at = 0;
	let loading = false;

	const esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));

	function compact(value) {
		const v = Number(value || 0);
		const abs = Math.abs(v);
		if (abs >= 1e6) return { text: format_number(v / 1e6, null, abs >= 1e8 ? 0 : 1), suffix: __("M", null, "Number suffix") };
		if (abs >= 1e4) return { text: format_number(v / 1e3, null, abs >= 1e5 ? 0 : 1), suffix: __("K", null, "Number suffix") };
		return { text: format_number(v, null, Number.isInteger(v) ? 0 : 1), suffix: "" };
	}

	// Same rule as the goal map card: a metric leaf shows its fact, a group or Boolean goal its progress.
	function display(goal) {
		if (!goal.is_group && goal.metric_type && goal.metric_type !== "Boolean") {
			const value = compact(goal.current_value);
			const currency =
				goal.metric_type === "Currency" ? get_currency_symbol(goal.currency) || goal.currency || "" : "";
			return { text: value.text, unit: [value.suffix, goal.unit || currency].filter(Boolean).join(" ") };
		}
		return { text: format_number(goal.progress || 0, null, 1), unit: "%" };
	}

	function tooltip(goal) {
		const lines = [goal.subject];
		if (!goal.is_group && goal.metric_type && goal.metric_type !== "Boolean") {
			const unit = goal.unit || (goal.metric_type === "Currency" ? goal.currency || "" : "");
			lines.push(
				`${__("Actual / Target")}: ${format_number(goal.current_value || 0, null, 2)} / ${format_number(
					goal.target || 0,
					null,
					2
				)}${unit ? " " + unit : ""}`
			);
		} else {
			lines.push(`${__("Progress")}: ${format_number(goal.progress || 0, null, 1)}%`);
		}
		lines.push(`${__("Achievement")}: ${format_number(goal.achievement_percent || 0, null, 1)}%`);
		lines.push(__("Open the goal map"));
		return lines.join("\n");
	}

	function render(goal) {
		const $nav = $(".navbar .navbar-collapse .navbar-nav").first();
		$nav.find(".dinext-goal-navbar").remove();
		if (!goal || !$nav.length) return;
		const rag = RAGS.includes(String(goal.rag_status || "").toLowerCase())
			? String(goal.rag_status).toLowerCase()
			: "none";
		const value = display(goal);
		const $item = $(`
			<li class="nav-item dinext-goal-navbar d-none d-sm-flex">
				<button type="button" class="btn-reset nav-link dinext-goal-navbar-value dinext-goal-rag-${rag}"
					data-goal="${esc(goal.name)}" title="${esc(tooltip(goal))}">
					<span class="dinext-goal-navbar-number">${esc(value.text)}</span>
					${value.unit ? `<span class="dinext-goal-navbar-unit">${esc(value.unit)}</span>` : ""}
				</button>
			</li>`);
		$item.find("button").on("click", () => {
			frappe.route_options = { root: goal.name, status: MAP_STATUSES };
			frappe.set_route("goal-map");
		});
		$nav.prepend($item);
	}

	function refresh(force) {
		if (loading || (!force && Date.now() - loaded_at < REFRESH_MS)) return;
		loading = true;
		frappe
			.xcall(METHOD)
			.then((goal) => {
				loaded_at = Date.now();
				render(goal);
			})
			.catch(() => render(null))
			.finally(() => {
				loading = false;
			});
	}

	$(document).on("app_ready", () => {
		if (!frappe.session || frappe.session.user === "Guest") return;
		refresh(true);
		frappe.router.on("change", () => refresh(false));
	});

	frappe.provide("dinext_goals");
	dinext_goals.refresh_navbar_goal = () => refresh(true);
})();
