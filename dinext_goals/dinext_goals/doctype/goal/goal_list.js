frappe.listview_settings["Goal"] = {
	add_fields: ["status", "rag_status", "is_overdue"],
	get_indicator(doc) {
		const label = __(doc.status, null, "Goal");
		const filter = `status,=,${doc.status}`;
		if (doc.status === "Active") {
			const color = { Red: "red", Yellow: "orange", Green: "green" }[doc.rag_status] || "blue";
			return [label, color, filter];
		}
		const colors = {
			Draft: "gray",
			"For Approval": "orange",
			"On Hold": "yellow",
			Closed: "green",
			Cancelled: "red",
			Template: "light-blue",
		};
		return [label, colors[doc.status] || "gray", filter];
	},
};
