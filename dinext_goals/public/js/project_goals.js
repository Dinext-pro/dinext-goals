frappe.ui.form.on("Project", {
	onload(frm) {
		keep_goals_connection(frm);
	},
	refresh(frm) {
		if (frm.is_new() || !frappe.model.can_read("Goal")) {
			return;
		}
		frm.add_custom_button(
			__("Goal Map"),
			() => {
				frappe.route_options = { project: frm.doc.name };
				frappe.set_route("goal-map");
			},
			__("View")
		);
	},
});

// Site Client Scripts may replace dashboard.data.transactions on refresh and re-render the links,
// so the Goals group is added at render time rather than once from the server dashboard data.
function keep_goals_connection(frm) {
	const dashboard = frm.dashboard;
	if (!dashboard || dashboard.dinext_goals_connection) {
		return;
	}
	dashboard.dinext_goals_connection = true;
	const render_links = dashboard.render_links.bind(dashboard);
	dashboard.render_links = function () {
		const data = this.data;
		const transactions = (data && data.transactions) || [];
		const listed = transactions.some((group) => (group.items || []).includes("Goal"));
		if (data && !listed && frappe.model.can_read("Goal")) {
			data.transactions = transactions.concat([{ label: __("Goals"), items: ["Goal"] }]);
			data.non_standard_fieldnames = { ...(data.non_standard_fieldnames || {}), Goal: "project" };
		}
		return render_links();
	};
}
