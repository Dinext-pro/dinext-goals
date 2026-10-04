frappe.pages["goal-map"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Goal Map"),
		single_column: true,
	});
	frappe.require(["goal_map.bundle.js", "/assets/dinext_goals/css/goals.css"], () => {
		wrapper.goal_map = new dinext_goals.GoalMap(page, wrapper);
	});
};

frappe.pages["goal-map"].on_page_show = function (wrapper) {
	if (wrapper.goal_map) {
		wrapper.goal_map.apply_route_options();
	}
};
