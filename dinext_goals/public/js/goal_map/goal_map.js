const CARD_W = 260;
const CARD_H = 140;
const GAP_X = 70;
const GAP_Y = 18;
const PADDING = 32;
const MIN_SCALE = 0.2;
const MAX_SCALE = 2;

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

function num(value, decimals) {
	const v = Number(value || 0);
	const d = decimals == null ? (Math.abs(v) >= 1000 ? 0 : 2) : decimals;
	return format_number(v, null, d);
}

function rag_class(rag) {
	return rag ? `dinext-goal-rag-${String(rag).toLowerCase()}` : "dinext-goal-rag-none";
}

function clamp(value, min, max) {
	return Math.max(min, Math.min(max, value));
}

export class GoalMap {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.collapsed = new Set();
		this.view = { x: PADDING, y: PADDING, scale: 1 };
		this.trees = [];
		this.make_filters();
		this.make_body();
		this.apply_route_options();
	}

	make_filters() {
		const reload = () => this.load();
		this.filters = {
			root: this.page.add_field({
				fieldname: "root",
				label: __("Root Goal"),
				fieldtype: "Link",
				options: "Goal",
				change: reload,
			}),
			goal_type: this.page.add_field({
				fieldname: "goal_type",
				label: __("Goal Type"),
				fieldtype: "Link",
				options: "Goal Type",
				change: reload,
			}),
			goal_owner: this.page.add_field({
				fieldname: "goal_owner",
				label: __("Goal Owner"),
				fieldtype: "Link",
				options: "User",
				change: reload,
			}),
			company: this.page.add_field({
				fieldname: "company",
				label: __("Company"),
				fieldtype: "Link",
				options: "Company",
				change: reload,
			}),
			show_linked: this.page.add_field({
				fieldname: "show_linked",
				label: __("Show Linked Documents"),
				fieldtype: "Check",
				change: reload,
			}),
		};
		this.page.set_primary_action(__("Refresh"), reload, "refresh");
	}

	make_body() {
		this.$map = $(`
			<div class="dinext-goal-map" data-testid="goal-map">
				<div class="dinext-goal-map-toolbar">
					<button class="btn btn-xs btn-default" data-action="zoom-in" title="${__("Zoom In")}">+</button>
					<button class="btn btn-xs btn-default" data-action="zoom-out" title="${__("Zoom Out")}">&minus;</button>
					<button class="btn btn-xs btn-default" data-action="fit">${__("Fit to Screen")}</button>
					<button class="btn btn-xs btn-default" data-action="expand">${__("Expand All")}</button>
					<button class="btn btn-xs btn-default" data-action="collapse">${__("Collapse All")}</button>
				</div>
				<div class="dinext-goal-map-canvas">
					<svg class="dinext-goal-map-links"></svg>
				</div>
				<div class="dinext-goal-map-legend">
					<span><span class="dinext-goal-rag-dot dinext-goal-rag-green"></span>${__("On track")}</span>
					<span><span class="dinext-goal-rag-dot dinext-goal-rag-yellow"></span>${__("At risk")}</span>
					<span><span class="dinext-goal-rag-dot dinext-goal-rag-red"></span>${__("Off track")}</span>
				</div>
			</div>`).appendTo(this.page.main);
		this.$canvas = this.$map.find(".dinext-goal-map-canvas");
		this.$svg = this.$map.find("svg");

		this.$map.on("click", "[data-action]", (e) => {
			const action = $(e.currentTarget).attr("data-action");
			if (action === "zoom-in") this.zoom(1.2);
			if (action === "zoom-out") this.zoom(1 / 1.2);
			if (action === "fit") this.fit();
			if (action === "expand") {
				this.collapsed.clear();
				this.render();
			}
			if (action === "collapse") {
				this.walk((node) => node.children && node.children.length && this.collapsed.add(node.id));
				this.trees.forEach((tree) => this.collapsed.delete(tree.id));
				this.render();
			}
		});
		this.$map.on("click", ".dinext-goal-card-toggle", (e) => {
			e.stopPropagation();
			const id = $(e.currentTarget).closest(".dinext-goal-card").attr("data-id");
			this.collapsed.has(id) ? this.collapsed.delete(id) : this.collapsed.add(id);
			this.render();
		});
		this.$map.on("click", ".dinext-goal-linked-open", (e) => {
			e.stopPropagation();
			const card = this.linked_cards[$(e.currentTarget).closest(".dinext-goal-card").attr("data-id")];
			if (card) {
				frappe.route_options = card.route_options || {};
				frappe.set_route("List", card.doctype);
			}
		});
		this.$map.on("click", ".dinext-goal-card[data-goal]", (e) => {
			if (this.dragged) return;
			frappe.set_route("Form", "Goal", $(e.currentTarget).attr("data-goal"));
		});
		this.bind_pan_zoom();
	}

	bind_pan_zoom() {
		let start = null;
		this.$map.on("mousedown", (e) => {
			if ($(e.target).closest(".dinext-goal-card, .dinext-goal-map-toolbar, button").length) return;
			start = { x: e.clientX, y: e.clientY, vx: this.view.x, vy: this.view.y };
			this.dragged = false;
			this.$map.addClass("is-panning");
		});
		$(document).on("mousemove.dinext_goal_map", (e) => {
			if (!start) return;
			const dx = e.clientX - start.x;
			const dy = e.clientY - start.y;
			if (Math.abs(dx) + Math.abs(dy) > 3) this.dragged = true;
			this.view.x = start.vx + dx;
			this.view.y = start.vy + dy;
			this.apply_transform();
		});
		$(document).on("mouseup.dinext_goal_map", () => {
			start = null;
			this.$map.removeClass("is-panning");
			setTimeout(() => (this.dragged = false), 0);
		});
		this.$map[0].addEventListener(
			"wheel",
			(e) => {
				e.preventDefault();
				const rect = this.$map[0].getBoundingClientRect();
				this.zoom(e.deltaY < 0 ? 1.1 : 1 / 1.1, e.clientX - rect.left, e.clientY - rect.top);
			},
			{ passive: false }
		);
	}

	apply_route_options() {
		const options = frappe.route_options;
		if (options) {
			frappe.route_options = null;
			Object.entries(options).forEach(([key, value]) => {
				if (this.filters[key]) this.filters[key].set_value(value);
			});
		}
		this.load();
	}

	get_filters() {
		const values = {};
		Object.entries(this.filters).forEach(([key, field]) => {
			const value = field.get_value();
			if (value) values[key] = value;
		});
		return values;
	}

	load() {
		clearTimeout(this.load_timer);
		this.load_timer = setTimeout(() => {
			frappe.xcall("dinext_goals.api.get_goal_map", this.get_filters()).then((data) => {
				this.trees = (data && data.trees) || [];
				this.render();
				this.fit();
				if (data && data.truncated) {
					frappe.show_alert({ message: __("The map is truncated; narrow down the filters"), indicator: "orange" });
				}
			});
		}, 50);
	}

	walk(fn) {
		const visit = (node) => {
			fn(node);
			(node.children || []).forEach(visit);
		};
		this.trees.forEach(visit);
	}

	visible_children(node) {
		if (this.collapsed.has(node.id)) return [];
		const children = [...(node.children || [])];
		if (node.linked) {
			children.push({ id: `${node.id}#linked`, linked_card: node.linked, children: [] });
		}
		return children;
	}

	layout() {
		const positions = [];
		let row = 0;
		const place = (node, depth) => {
			const children = this.visible_children(node);
			let y;
			if (!children.length) {
				y = row * (CARD_H + GAP_Y);
				row += 1;
			} else {
				const ys = children.map((child) => place(child, depth + 1));
				y = (ys[0] + ys[ys.length - 1]) / 2;
			}
			positions.push({ node, x: depth * (CARD_W + GAP_X), y, children });
			return y;
		};
		this.trees.forEach((tree) => {
			place(tree, 0);
			row += 0.5;
		});
		return positions;
	}

	render() {
		this.$canvas.find(".dinext-goal-card").remove();
		this.$map.find(".dinext-goal-map-empty").remove();
		this.linked_cards = {};
		if (!this.trees.length) {
			this.$svg.empty();
			this.$map.append(`<div class="dinext-goal-map-empty">${__("No goals match the filters")}</div>`);
			return;
		}
		const positions = this.layout();
		const byId = {};
		positions.forEach((p) => (byId[p.node.id] = p));
		let width = 0;
		let height = 0;
		const paths = [];
		positions.forEach((p) => {
			width = Math.max(width, p.x + CARD_W);
			height = Math.max(height, p.y + CARD_H);
			this.$canvas.append(this.card_html(p.node, p.x, p.y));
			p.children.forEach((child) => {
				const c = byId[child.id];
				if (!c) return;
				const x1 = p.x + CARD_W;
				const y1 = p.y + CARD_H / 2;
				const x2 = c.x;
				const y2 = c.y + CARD_H / 2;
				const mx = (x1 + x2) / 2;
				const cls = child.linked_card ? "is-linked-doc" : "";
				paths.push(`<path class="${cls}" d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}"></path>`);
			});
		});
		this.$svg.attr({ width, height }).html(paths.join(""));
		this.$canvas.css({ width, height });
		this.size = { width, height };
		this.apply_transform();
	}

	card_html(node, x, y) {
		const style = `left:${x}px;top:${y}px;height:${CARD_H}px`;
		if (node.linked_card) {
			return this.linked_card_html(node, style);
		}
		const hasChildren = (node.children && node.children.length) || node.linked;
		const toggle = hasChildren
			? `<button class="dinext-goal-card-toggle" title="${__("Expand / Collapse")}">${this.collapsed.has(node.id) ? "+" : "&minus;"}</button>`
			: "";
		const shared = node.shared ? `<span class="dinext-goal-card-badge">${__("shared")}</span>` : "";
		const unit = node.unit ? ` ${esc(node.unit)}` : "";
		const rows = [
			`<div class="dinext-goal-card-row"><span>${__("Progress")}</span><span>${num(node.progress, 1)}% / ${num(node.planned_progress, 1)}%</span></div>`,
		];
		if (!node.is_group && node.metric_type && node.metric_type !== "Boolean") {
			rows.push(
				`<div class="dinext-goal-card-row"><span>${__("Actual / Target")}</span><span>${num(node.current_value)} / ${num(node.target)}${unit}</span></div>`
			);
		}
		if (node.coefficient) {
			rows.push(`<div class="dinext-goal-card-row"><span>${__("Coefficient")}</span><span>${num(node.coefficient, 2)}</span></div>`);
		}
		if (node.result_label) {
			rows.push(
				`<div class="dinext-goal-card-row"><span>${esc(node.result_label)}</span><span><b>${num(node.result_value)}</b></span></div>`
			);
		}
		return `
			<div class="dinext-goal-card ${rag_class(node.rag_status)}" style="${style}" data-id="${esc(node.id)}" data-goal="${esc(node.name)}"
				title="${esc(node.subject)}">
				<div class="dinext-goal-card-title"><span class="dinext-goal-rag-dot ${rag_class(node.rag_status)}"></span>${esc(node.subject)}</div>
				<div class="dinext-goal-card-meta">${esc(__(node.goal_type))} · ${esc(node.owner_name)} · ${esc(__(node.status))}${shared}</div>
				${rows.join("")}
				<div class="dinext-goal-progress">
					<div class="dinext-goal-progress-bar ${rag_class(node.rag_status)}" style="width:${clamp(node.progress || 0, 0, 100)}%"></div>
					<div class="dinext-goal-progress-plan" style="left:${clamp(node.planned_progress || 0, 0, 100)}%"></div>
				</div>
				${toggle}
			</div>`;
	}

	linked_card_html(node, style) {
		const card = node.linked_card;
		this.linked_cards[node.id] = card;
		let body;
		if (card.restricted) {
			body = `<div class="dinext-goal-card-meta">${__("No access to these documents")}</div>`;
		} else if (card.error) {
			body = `<div class="dinext-goal-card-meta text-danger">${esc(card.error)}</div>`;
		} else {
			const aggregate =
				card.aggregation === "Count"
					? ""
					: `<div class="dinext-goal-card-row"><span>${esc(__(card.aggregation))} ${esc(card.field || "")}</span><span>${num(card.value)}</span></div>`;
			body = `
				<div class="dinext-goal-card-row"><span>${__("Documents")}</span><span>${num(card.count, 0)}</span></div>
				${aggregate}
				<div class="dinext-goal-card-row"><span></span><a class="dinext-goal-linked-open">${__("Analysis")}</a></div>`;
		}
		return `
			<div class="dinext-goal-card is-linked-doc" style="${style}" data-id="${esc(node.id)}">
				<div class="dinext-goal-card-title">${esc(__(card.doctype))}</div>
				<div class="dinext-goal-card-meta">${__("Linked documents")}</div>
				${body}
			</div>`;
	}

	apply_transform() {
		this.$canvas.css("transform", `translate(${this.view.x}px, ${this.view.y}px) scale(${this.view.scale})`);
	}

	zoom(factor, cx, cy) {
		const rect = this.$map[0].getBoundingClientRect();
		const ox = cx == null ? rect.width / 2 : cx;
		const oy = cy == null ? rect.height / 2 : cy;
		const scale = clamp(this.view.scale * factor, MIN_SCALE, MAX_SCALE);
		const ratio = scale / this.view.scale;
		this.view.x = ox - (ox - this.view.x) * ratio;
		this.view.y = oy - (oy - this.view.y) * ratio;
		this.view.scale = scale;
		this.apply_transform();
	}

	fit() {
		if (!this.size) return;
		const rect = this.$map[0].getBoundingClientRect();
		const scale = clamp(
			Math.min((rect.width - PADDING * 2) / this.size.width, (rect.height - PADDING * 2) / this.size.height),
			MIN_SCALE,
			1
		);
		this.view.scale = scale;
		this.view.x = PADDING;
		this.view.y = Math.max(PADDING, (rect.height - this.size.height * scale) / 2);
		this.apply_transform();
	}
}
