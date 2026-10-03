const ECHARTS_ASSETS = [
	"/assets/dinext_common/js/echarts.min.js",
	"/assets/dinext_common/js/charts/dinext-charts-core.js",
];
const SERIES_ID = "goals";
const CARD_W = 236;
const CARD_H = 132;
const LINKED_H = 100;
const PAD = 10;
const INNER_W = CARD_W - PAD * 2;
const TOGGLE = 26;
const TOGGLE_GAP = 6;
const AVATAR = 22;
const GAP = { TB: { cross: 28, depth: 84 }, LR: { cross: 22, depth: 96 } };
const MARGIN = 40;
// Labels are drawn at fontSize * zoom; small rasterised sizes run a few percent wider than a 1:1 measure.
const FIT_SLACK = 1.06;
const MIN_ZOOM = 0.1;
const MAX_ZOOM = 2.5;
const READABLE_ZOOM = 0.4;
const BAR_STEPS = 20;
const RAGS = ["green", "yellow", "red", "none"];
const ORIENT_KEY = "dinext_goal_map_orient";
const STATUSES = ["Draft", "For Approval", "Active", "On Hold", "Closed", "Cancelled"];
const AVATAR_COLORS = ["#2563eb", "#7c3aed", "#db2777", "#ea580c", "#0d9488", "#4f46e5", "#0891b2", "#65a30d"];

// Card text is measured at zoom 1 and fonts scale linearly with the zoom, so it fits at any zoom.
const STYLE = {
	title: { fontSize: 13, fontWeight: 600, lineHeight: 17 },
	meta: { fontSize: 11, fontWeight: 400, lineHeight: 26 },
	value: { fontSize: 24, fontWeight: 700, lineHeight: 30 },
	unit: { fontSize: 11, fontWeight: 600, lineHeight: 30 },
	small: { fontSize: 11, fontWeight: 400, lineHeight: 16 },
	link: { fontSize: 12, fontWeight: 600, lineHeight: 18 },
	toggle: { fontSize: 18, fontWeight: 600, lineHeight: 18 },
	mini: { fontSize: 56, fontWeight: 700, lineHeight: 64 },
	mini_small: { fontSize: 38, fontWeight: 700, lineHeight: 46 },
};
const FIT_ICONS = {
	width: '<path d="M1.5 3v10M14.5 3v10M4 8h8M6.5 5.5 4 8l2.5 2.5M9.5 5.5 12 8l-2.5 2.5"/>',
	height: '<path d="M3 1.5h10M3 14.5h10M8 4v8M5.5 6.5 8 4l2.5 2.5M5.5 9.5 8 12l2.5-2.5"/>',
};

function fit_icon(axis) {
	return `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${FIT_ICONS[axis]}</svg>`;
}

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

function clamp(value, min, max) {
	return Math.max(min, Math.min(max, value));
}

function rich_text(value) {
	return String(value == null ? "" : value).replace(/[{}|\n]/g, " ");
}

function fmt(value, decimals) {
	const v = Number(value || 0);
	return format_number(v, null, decimals == null ? (Number.isInteger(v) ? 0 : 2) : decimals);
}

function compact(value) {
	const v = Number(value || 0);
	const abs = Math.abs(v);
	if (abs >= 1e6) return { text: format_number(v / 1e6, null, abs >= 1e8 ? 0 : 1), suffix: __("M", null, "Number suffix") };
	if (abs >= 1e4) return { text: format_number(v / 1e3, null, abs >= 1e5 ? 0 : 1), suffix: __("K", null, "Number suffix") };
	return { text: fmt(v, Number.isInteger(v) ? 0 : 1), suffix: "" };
}

function rag_key(rag) {
	const key = String(rag || "").toLowerCase();
	return RAGS.includes(key) ? key : "none";
}

function css_var(el, name, fallback) {
	const value = getComputedStyle(el).getPropertyValue(name).trim();
	return value || fallback;
}

function month_name(index) {
	const name = new Date(2000, index, 1).toLocaleString(frappe.boot.lang || "en", { month: "long" });
	return name.charAt(0).toUpperCase() + name.slice(1);
}

function month_options() {
	const year = new Date().getFullYear();
	const options = [];
	for (let y = year - 2; y <= year + 1; y++) {
		for (let m = 0; m < 12; m++) {
			options.push({ label: `${month_name(m)} ${y}`, value: `${y}-${String(m + 1).padStart(2, "0")}` });
		}
	}
	return options;
}

function link_options(doctype, txt, filters) {
	return frappe.db
		.get_link_options(doctype, txt, filters)
		.then((rows) => rows.map((row) => ({ ...row, label: __(row.value), description: row.description || "" })));
}

class TextFitter {
	constructor(family) {
		this.family = family;
		this.ctx = document.createElement("canvas").getContext("2d");
	}

	width(text, style) {
		this.ctx.font = `${style.fontWeight} ${style.fontSize}px ${this.family}`;
		return this.ctx.measureText(text).width * FIT_SLACK;
	}

	truncate(text, width, style) {
		text = rich_text(text).trim();
		if (this.width(text, style) <= width) return text;
		let lo = 0;
		let hi = text.length;
		while (lo < hi) {
			const mid = Math.ceil((lo + hi) / 2);
			if (this.width(text.slice(0, mid).trimEnd() + "…", style) <= width) lo = mid;
			else hi = mid - 1;
		}
		return text.slice(0, lo).trimEnd() + "…";
	}

	wrap(text, width, style, lines) {
		const words = rich_text(text).trim().split(/\s+/).filter(Boolean);
		const result = [];
		let line = "";
		for (const word of words) {
			const next = line ? `${line} ${word}` : word;
			if (!line || result.length === lines - 1 || this.width(next, style) <= width) {
				line = next;
				continue;
			}
			result.push(line);
			line = word;
		}
		if (line) result.push(line);
		return result.map((l) => this.truncate(l, width, style));
	}
}

export class GoalMap {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.collapsed = new Set();
		this.trees = [];
		this.avatars = {};
		this.zoom = 1;
		this.orient = localStorage.getItem(ORIENT_KEY) === "LR" ? "LR" : "TB";
		this.make_filters();
		this.make_body();
		this.ready = new Promise((resolve) => frappe.require(ECHARTS_ASSETS, resolve)).then(() => this.make_chart());
		this.apply_route_options();
	}

	make_filters() {
		const reload = () => this.load();
		const months = month_options();
		// When one bound passes the other, the other bound follows it.
		const period = (fieldname, label, other, is_start) =>
			this.page.add_field({
				fieldname,
				label,
				fieldtype: "Select",
				options: [{ label, value: "" }].concat(months),
				change: () => {
					const value = this.filters[fieldname].get_value();
					const bound = this.filters[other].get_value();
					if (value && bound && (is_start ? bound < value : bound > value)) {
						this.filters[other].set_value(value);
					}
					reload();
				},
			});
		this.filters = {
			root: this.page.add_field({
				fieldname: "root",
				label: __("Root Goal"),
				fieldtype: "Link",
				options: "Goal",
				change: reload,
			}),
			status: this.page.add_field({
				fieldname: "status",
				label: __("Status"),
				fieldtype: "MultiSelectList",
				get_data: () => STATUSES.map((status) => ({ label: __(status), value: status, description: "" })),
				change: reload,
			}),
			period_from: period("period_from", __("Period From"), "period_to", true),
			period_to: period("period_to", __("Period To"), "period_from", false),
			goal_type: this.page.add_field({
				fieldname: "goal_type",
				label: __("Goal Type"),
				fieldtype: "MultiSelectList",
				get_data: (txt) => link_options("Goal Type", txt),
				change: reload,
			}),
			goal_owner: this.page.add_field({
				fieldname: "goal_owner",
				label: __("Goal Owner"),
				fieldtype: "MultiSelectList",
				get_data: (txt) => link_options("User", txt, { enabled: 1, user_type: "System User" }),
				change: reload,
			}),
			company: this.page.add_field({
				fieldname: "company",
				label: __("Company"),
				fieldtype: "Link",
				options: "Company",
				change: reload,
			}),
			project: this.page.add_field({
				fieldname: "project",
				label: __("Project"),
				fieldtype: "Link",
				options: "Project",
				change: reload,
			}),
			show_linked: this.page.add_field({
				fieldname: "show_linked",
				label: __("Show Linked Documents"),
				fieldtype: "Check",
				change: reload,
			}),
		};
		this.orient_field = this.page.add_field({
			fieldname: "orient",
			label: __("Layout"),
			fieldtype: "Select",
			options: [
				{ label: __("Top to Bottom"), value: "TB" },
				{ label: __("Left to Right"), value: "LR" },
			],
			default: this.orient,
			change: () => {
				const value = this.orient_field.get_value() === "LR" ? "LR" : "TB";
				if (value === this.orient) return;
				this.orient = value;
				localStorage.setItem(ORIENT_KEY, value);
				this.render({ fit: true });
			},
		});
		this.page.set_primary_action(__("Refresh"), reload, "refresh");
		this.filters.status.set_options();
		this.filters.status.set_value(["Active"]);
	}

	make_body() {
		this.$map = $(`
			<div class="dinext-goal-map" data-testid="goal-map">
				<div class="dinext-goal-map-chart" data-testid="goal-map-chart"></div>
				<div class="dinext-goal-map-toolbar">
					<button class="btn btn-xs btn-default" data-action="zoom-in" title="${__("Zoom In")}">+</button>
					<button class="btn btn-xs btn-default" data-action="zoom-out" title="${__("Zoom Out")}">&minus;</button>
					<button class="btn btn-xs btn-default" data-action="fit">${__("Fit to Screen")}</button>
					<button class="btn btn-xs btn-default" data-action="fit-width" title="${__("Fit to Width")}" aria-label="${__("Fit to Width")}">${fit_icon("width")}</button>
					<button class="btn btn-xs btn-default" data-action="fit-height" title="${__("Fit to Height")}" aria-label="${__("Fit to Height")}">${fit_icon("height")}</button>
					<button class="btn btn-xs btn-default" data-action="expand">${__("Expand All")}</button>
					<button class="btn btn-xs btn-default" data-action="collapse">${__("Collapse All")}</button>
				</div>
				<div class="dinext-goal-map-legend">
					<span><span class="dinext-goal-rag-dot dinext-goal-rag-green"></span>${__("On track")}</span>
					<span><span class="dinext-goal-rag-dot dinext-goal-rag-yellow"></span>${__("At risk")}</span>
					<span><span class="dinext-goal-rag-dot dinext-goal-rag-red"></span>${__("Off track")}</span>
				</div>
				<div class="dinext-goal-map-empty hidden">${__("No goals match the filters")}</div>
			</div>`).appendTo(this.page.main);
		this.$chart = this.$map.find(".dinext-goal-map-chart");
		this.$empty = this.$map.find(".dinext-goal-map-empty");
		this.$map.on("click", "[data-action]", (e) => {
			const action = $(e.currentTarget).attr("data-action");
			if (action === "zoom-in") this.set_zoom(this.zoom * 1.25);
			if (action === "zoom-out") this.set_zoom(this.zoom / 1.25);
			if (action === "fit") this.fit();
			if (action === "fit-width") this.fit("width");
			if (action === "fit-height") this.fit("height");
			if (action === "expand") {
				this.collapsed.clear();
				this.render({ fit: true });
			}
			if (action === "collapse") {
				this.walk((node) => node.children && node.children.length && this.collapsed.add(node.id));
				this.trees.forEach((tree) => this.collapsed.delete(tree.id));
				this.render({ fit: true });
			}
		});
	}

	make_chart() {
		this.fitter = new TextFitter(getComputedStyle(document.body).fontFamily || "sans-serif");
		this.chart = DinextCharts.mount(this.$chart, {});
		this.unbind_resize = DinextCharts.bindResize(this.chart, this.$chart);
		this.chart.on("click", (params) => this.on_click(params));
		let pending = false;
		this.chart.on("graphroam", (params) => {
			if (params.zoom == null || pending) return;
			pending = true;
			requestAnimationFrame(() => {
				pending = false;
				this.rescale(this.current_zoom());
			});
		});
		new ResizeObserver(() => this.update_view_rect()).observe(this.$chart[0]);
	}

	apply_route_options() {
		const options = frappe.route_options || {};
		frappe.route_options = null;
		const pending = Object.entries(options)
			.filter(([key]) => this.filters[key])
			.map(([key, value]) => this.filters[key].set_value(value));
		Promise.all(pending).then(() => this.load());
	}

	get_filters() {
		const values = { status: this.filters.status.get_value() || [] };
		Object.entries(this.filters).forEach(([key, field]) => {
			const value = field.get_value();
			if (key !== "status" && (Array.isArray(value) ? value.length : value)) values[key] = value;
		});
		return values;
	}

	load() {
		clearTimeout(this.load_timer);
		this.load_timer = setTimeout(() => {
			const filters = this.get_filters();
			const request = (this.request = (this.request || 0) + 1);
			Promise.all([frappe.xcall("dinext_goals.api.get_goal_map", filters), this.ready]).then(([data]) => {
				if (request !== this.request) return;
				this.trees = (data && data.trees) || [];
				this.load_avatars().then(() => request === this.request && this.render({ fit: true }));
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

	load_avatars() {
		const urls = new Set();
		this.walk((node) => node.owner_image && !(node.owner_image in this.avatars) && urls.add(node.owner_image));
		const size = AVATAR * 4;
		return Promise.all(
			[...urls].map(
				(url) =>
					new Promise((resolve) => {
						const img = new Image();
						const done = (canvas) => {
							this.avatars[url] = canvas;
							resolve();
						};
						img.onload = () => {
							const canvas = document.createElement("canvas");
							canvas.width = canvas.height = size;
							const ctx = canvas.getContext("2d");
							ctx.beginPath();
							ctx.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2);
							ctx.clip();
							const side = Math.min(img.width, img.height);
							ctx.drawImage(img, (img.width - side) / 2, (img.height - side) / 2, side, side, 0, 0, size, size);
							done(canvas);
						};
						img.onerror = () => done(null);
						setTimeout(() => resolve(), 3000);
						img.src = url;
					})
			)
		);
	}

	visible_children(node) {
		if (this.collapsed.has(node.id)) return [];
		const children = [...(node.children || [])];
		if (node.linked) children.push({ id: `${node.id}#linked`, linked_card: node.linked, children: [] });
		return children;
	}

	has_children(node) {
		return Boolean((node.children && node.children.length) || node.linked);
	}

	colors() {
		const el = this.$map[0];
		return {
			green: css_var(el, "--dinext-goal-green", "#16a34a"),
			yellow: css_var(el, "--dinext-goal-yellow", "#eab308"),
			red: css_var(el, "--dinext-goal-red", "#dc2626"),
			none: css_var(el, "--dinext-goal-none", "#9ca3af"),
			card: css_var(el, "--dinext-goal-map-card", "#ffffff"),
			bg: css_var(el, "--dinext-goal-map-bg", "#f3f3f3"),
			border: css_var(el, "--dinext-goal-map-line", "#9ca3af"),
			text: css_var(el, "--text-color", "#171717"),
			muted: css_var(el, "--text-muted", "#6b7280"),
			track: css_var(el, "--dinext-goal-track", "#e5e7eb"),
			link: css_var(el, "--dinext-goal-map-link", "#2563eb"),
			shadow: css_var(el, "--dinext-goal-map-shadow", "rgba(15, 23, 42, 0.12)"),
		};
	}

	/* ------------------------------------------------------------ layout */

	layout() {
		const vertical = this.orient === "TB";
		const gap = GAP[this.orient];
		const pitch = vertical ? CARD_W + gap.cross : CARD_H + gap.cross;
		const depth_step = vertical ? CARD_H + gap.depth : CARD_W + gap.depth;
		const placed = [];
		let slot = 0;
		const place = (node, depth) => {
			const kids = this.visible_children(node);
			let cross;
			if (!kids.length) {
				cross = slot * pitch;
				slot += 1;
			} else {
				const values = kids.map((kid) => place(kid, depth + 1));
				cross = (values[0] + values[values.length - 1]) / 2;
			}
			const h = node.linked_card ? LINKED_H : CARD_H;
			const box = vertical
				? { x: cross, y: depth * depth_step + h / 2, w: CARD_W, h }
				: { x: depth * depth_step + CARD_W / 2, y: cross, w: CARD_W, h };
			placed.push({ node, kids, ...box });
			return cross;
		};
		this.trees.forEach((tree) => {
			place(tree, 0);
			slot += 0.5;
		});
		return placed;
	}

	build() {
		const colors = this.colors();
		const vertical = this.orient === "TB";
		const placed = this.layout();
		const byId = {};
		placed.forEach((p) => (byId[p.node.id] = p));
		const cards = [];
		const toggles = [];
		const points = [];
		const edges = [];
		const index = {};
		const nodes = () => cards.concat(points, toggles);
		const point = (x, y) => {
			points.push({ id: `pt:${points.length}`, x, y, symbol: "none", symbolSize: 0, kind: "point", label: { show: false } });
			return points[points.length - 1].id;
		};
		const edge = (source, target, dashed) => {
			edges.push({ source, target, lineStyle: dashed ? { type: [4, 4] } : undefined });
		};

		placed.forEach((p) => {
			cards.push(p.node.linked_card ? this.linked_item(p, colors) : this.card_item(p, colors));
			if (!this.has_children(p.node)) return;
			const tx = vertical ? p.x : p.x + p.w / 2 + TOGGLE_GAP + TOGGLE / 2;
			const ty = vertical ? p.y + p.h / 2 + TOGGLE_GAP + TOGGLE / 2 : p.y;
			const toggle_id = `toggle:${p.node.id}`;
			toggles.push(this.toggle_item(toggle_id, p.node, tx, ty, colors));
			edge(`card:${p.node.id}`, toggle_id);
			if (!p.kids.length) return;
			const kids = p.kids.map((kid) => byId[kid.id]).filter(Boolean);
			const near = vertical ? ty + TOGGLE / 2 : tx + TOGGLE / 2;
			const far = Math.min(...kids.map((k) => (vertical ? k.y - k.h / 2 : k.x - k.w / 2)));
			const bus = near + (far - near) / 2;
			const junctions = [{ id: point(vertical ? tx : bus, vertical ? bus : ty), at: vertical ? tx : ty }];
			kids.forEach((kid) => {
				const id = point(vertical ? kid.x : bus, vertical ? bus : kid.y);
				junctions.push({ id, at: vertical ? kid.x : kid.y, kid });
			});
			edge(toggle_id, junctions[0].id);
			junctions.sort((a, b) => a.at - b.at);
			for (let i = 1; i < junctions.length; i++) edge(junctions[i - 1].id, junctions[i].id);
			junctions.forEach((j) => j.kid && edge(j.id, `card:${j.kid.node.id}`, Boolean(j.kid.node.linked_card)));
		});

		const xs = placed.flatMap((p) => [p.x - p.w / 2, p.x + p.w / 2 + (vertical ? 0 : TOGGLE + TOGGLE_GAP)]);
		const ys = placed.flatMap((p) => [p.y - p.h / 2, p.y + p.h / 2 + (vertical ? TOGGLE + TOGGLE_GAP : 0)]);
		const box = {
			x0: Math.min(...xs) - MARGIN,
			y0: Math.min(...ys) - MARGIN,
			x1: Math.max(...xs) + MARGIN,
			y1: Math.max(...ys) + MARGIN,
		};
		points.push(
			{ id: "bounds:0", x: box.x0, y: box.y0, symbol: "none", symbolSize: 0, kind: "point", label: { show: false } },
			{ id: "bounds:1", x: box.x1, y: box.y1, symbol: "none", symbolSize: 0, kind: "point", label: { show: false } }
		);
		const data = nodes();
		data.forEach((item, i) => (index[item.id] = i));
		const links = edges
			.filter((e) => e.source in index && e.target in index)
			.map((e) => ({ source: index[e.source], target: index[e.target], lineStyle: e.lineStyle }));
		return { data, links, box, placed, index, colors };
	}

	card_item(p, colors) {
		const node = p.node;
		const rag = rag_key(node.rag_status);
		const f = this.fitter;
		const title_lines = f.wrap(node.subject || node.name, INNER_W - 14, STYLE.title, 2);
		if (!title_lines.length) title_lines.push(rich_text(node.name));
		while (title_lines.length < 2) title_lines.push(" ");
		const owner_key = this.avatar_key(node);
		const status = [__(node.status), node.shared ? __("shared") : ""].filter(Boolean).join(" · ");
		const meta = f.truncate(
			[node.owner_name || node.goal_owner, status].filter(Boolean).join(" · "),
			INNER_W - AVATAR - 8,
			STYLE.meta
		);
		const show_metric = !node.is_group && node.metric_type && node.metric_type !== "Boolean";
		let big;
		let unit;
		let target = "";
		if (show_metric) {
			big = compact(node.current_value);
			const currency = node.metric_type === "Currency" ? get_currency_symbol(node.currency) || node.currency : "";
			unit = [big.suffix, node.unit || currency].filter(Boolean).join(" ");
			const t = compact(node.target);
			target = `/ ${t.text}${t.suffix ? " " + t.suffix : ""}`;
		} else {
			big = { text: fmt(node.progress, 1), suffix: "" };
			unit = "%";
		}
		const value_text = f.truncate(big.text, INNER_W * 0.62, STYLE.value);
		const unit_text = f.truncate(unit, INNER_W - f.width(value_text, STYLE.value) - 4, STYLE.unit);
		const target_room = INNER_W - f.width(value_text, STYLE.value) - f.width(unit_text, STYLE.unit) - 12;
		const target_text = target && target_room > 24 ? f.truncate(target, target_room, STYLE.small) : "";
		const progress = __("Progress {0}% · plan {1}%", [fmt(node.progress, 1), fmt(node.planned_progress, 1)]);
		const coefficient = Number(node.coefficient) ? `K ${fmt(node.coefficient, 2)}` : "";
		const progress_text = f.truncate(progress, INNER_W - (coefficient ? f.width(coefficient, STYLE.small) + 8 : 0), STYLE.small);
		const filled = Math.round((clamp(Number(node.progress) || 0, 0, 100) / 100) * BAR_STEPS);
		const bar = `{bf${filled}_${rag}|}{bt${BAR_STEPS - filled}|}`;
		const text = [
			`{dot_${rag}|}{gap|}{title|${title_lines[0]}}`,
			`{title|${title_lines[1]}}`,
			`{${owner_key}|}{gap|}{meta|${meta}}`,
			`{v_${rag}|${value_text}}{unit|${unit_text ? " " + unit_text : ""}}${target_text ? `{target|${target_text}}` : ""}`,
			`{small|${progress_text}}${coefficient ? `{small_r|${coefficient}}` : ""}`,
			bar,
		].join("\n");
		const mini_value = show_metric ? `${big.text}${big.suffix ? " " + big.suffix : ""}` : `${fmt(node.progress, 0)}%`;
		return {
			id: `card:${node.id}`,
			kind: "goal",
			goal: node.name,
			node_id: node.id,
			rag,
			x: p.x,
			y: p.y,
			symbol: "rect",
			symbolSize: [p.w, p.h],
			itemStyle: {
				color: colors.card,
				borderColor: colors[rag],
				borderWidth: rag === "none" ? 1 : 2,
				shadowBlur: 8,
				shadowColor: colors.shadow,
			},
			full: text,
			mini: this.mini_text(mini_value, rag),
			tip: this.tooltip(node),
		};
	}

	linked_item(p, colors) {
		const card = p.node.linked_card;
		const f = this.fitter;
		const lines = [`{title|${f.truncate(__(card.doctype), INNER_W, STYLE.title)}}`, `{small|${f.truncate(__("Linked documents"), INNER_W, STYLE.small)}}`];
		if (card.restricted) {
			lines.push(`{small|${f.truncate(__("No access to these documents"), INNER_W, STYLE.small)}}`, "{small| }");
		} else if (card.error) {
			lines.push(`{error|${f.truncate(card.error, INNER_W, STYLE.small)}}`, "{small| }");
		} else {
			const count = fmt(card.count, 0);
			const aggregate = card.aggregation && card.aggregation !== "Count" ? ` · ${__(card.aggregation)} ${fmt(card.value)}` : "";
			lines.push(
				`{v_none|${f.truncate(count, INNER_W * 0.5, STYLE.value)}}{unit|${f.truncate(" " + __("documents") + aggregate, INNER_W - f.width(count, STYLE.value) - 4, STYLE.unit)}}`,
				`{link|${f.truncate(__("Analysis") + " →", INNER_W, STYLE.link)}}`
			);
		}
		return {
			id: `card:${p.node.id}`,
			kind: "linked",
			card,
			x: p.x,
			y: p.y,
			symbol: "rect",
			symbolSize: [p.w, p.h],
			itemStyle: { color: colors.card, borderColor: colors.link, borderWidth: 1, borderType: [5, 4], shadowBlur: 4, shadowColor: colors.shadow },
			full: lines.join("\n"),
			mini: card.restricted || card.error ? "" : this.mini_text(fmt(card.count, 0), "link"),
			tip: esc(card.error || __(card.doctype)),
		};
	}

	mini_text(value, rag) {
		const f = this.fitter;
		const style = f.width(value, STYLE.mini) <= INNER_W ? "mini" : "mini_small";
		return `{${style}_${rag}|${f.truncate(value, INNER_W, STYLE[style])}}`;
	}

	toggle_item(id, node, x, y, colors) {
		const collapsed = this.collapsed.has(node.id);
		return {
			id,
			kind: "toggle",
			node_id: node.id,
			goal: node.name,
			collapsed,
			x,
			y,
			symbol: "circle",
			symbolSize: TOGGLE,
			itemStyle: { color: colors.card, borderColor: colors.border, borderWidth: 1.5 },
			label: { formatter: `{toggle|${collapsed ? "+" : "−"}}` },
			tip: esc(collapsed ? __("Expand") : __("Collapse")),
		};
	}

	avatar_key(node) {
		let key = node.owner_image && this.avatars[node.owner_image] ? node.owner_image : null;
		if (!key) {
			const name = node.owner_name || node.goal_owner || "";
			let hash = 0;
			for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) | 0;
			const initials = frappe.get_abbr(name, 2);
			const color = AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
			key = `initials:${initials}:${color}`;
			if (!this.avatars[key]) this.avatars[key] = this.initials_canvas(initials, color);
		}
		return `img_${this.image_index(key)}`;
	}

	initials_canvas(initials, color) {
		const size = AVATAR * 4;
		const canvas = document.createElement("canvas");
		canvas.width = canvas.height = size;
		const ctx = canvas.getContext("2d");
		ctx.fillStyle = color;
		ctx.beginPath();
		ctx.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2);
		ctx.fill();
		ctx.fillStyle = "#ffffff";
		ctx.font = `700 ${Math.round(size * 0.4)}px ${this.fitter.family}`;
		ctx.textAlign = "center";
		ctx.textBaseline = "middle";
		ctx.fillText(initials, size / 2, size / 2 + size * 0.03);
		return canvas;
	}

	image_index(url) {
		let i = this.image_keys.indexOf(url);
		if (i < 0) {
			this.image_keys.push(url);
			i = this.image_keys.length - 1;
		}
		return i;
	}

	tooltip(node) {
		const rows = [
			[__("Owner"), node.owner_name || node.goal_owner],
			[__("Status"), __(node.status)],
			[__("Goal Type"), __(node.goal_type)],
			[__("Progress"), `${fmt(node.progress, 1)}% / ${fmt(node.planned_progress, 1)}%`],
		];
		if (!node.is_group && node.metric_type && node.metric_type !== "Boolean") {
			rows.push([__("Actual / Target"), `${fmt(node.current_value)} / ${fmt(node.target)} ${node.unit || node.currency || ""}`]);
		}
		if (Number(node.coefficient)) rows.push([__("Coefficient"), fmt(node.coefficient, 2)]);
		if (node.result_label) rows.push([node.result_label, fmt(node.result_value)]);
		if (node.exp_start_date || node.exp_end_date) {
			rows.push([__("Period"), `${frappe.datetime.str_to_user(node.exp_start_date) || ""} – ${frappe.datetime.str_to_user(node.exp_end_date) || ""}`]);
		}
		return `<div class="dinext-goal-map-tip"><b>${esc(node.subject)}</b>${rows
			.map(([label, value]) => `<div><span>${esc(label)}</span><span>${esc(value)}</span></div>`)
			.join("")}</div>`;
	}

	rich(scale, colors) {
		const s = (style, extra = {}) => ({
			fontFamily: this.fitter.family,
			fontSize: style.fontSize * scale,
			fontWeight: style.fontWeight,
			lineHeight: style.lineHeight * scale,
			color: colors.text,
			align: "left",
			...extra,
		});
		const rich = {
			title: s(STYLE.title),
			meta: s(STYLE.meta, { color: colors.muted }),
			unit: s(STYLE.unit, { color: colors.muted }),
			target: s(STYLE.small, { color: colors.muted, align: "right", lineHeight: STYLE.value.lineHeight * scale }),
			small: s(STYLE.small, { color: colors.muted }),
			small_r: s(STYLE.small, { color: colors.text, fontWeight: 600, align: "right" }),
			link: s(STYLE.link, { color: colors.link }),
			error: s(STYLE.small, { color: colors.red }),
			toggle: s(STYLE.toggle, { align: "center", color: colors.text }),
			gap: { width: 6 * scale, height: 1, lineHeight: 1, align: "left" },
		};
		RAGS.concat("link").forEach((rag) => {
			const color = rag === "none" ? colors.text : colors[rag];
			rich[`mini_${rag}`] = s(STYLE.mini, { color, align: "center" });
			rich[`mini_small_${rag}`] = s(STYLE.mini_small, { color, align: "center" });
		});
		RAGS.forEach((rag) => {
			rich[`v_${rag}`] = s(STYLE.value, { color: rag === "none" ? colors.text : colors[rag] });
			rich[`dot_${rag}`] = {
				width: 8 * scale,
				height: 8 * scale,
				lineHeight: 8 * scale,
				borderRadius: 4 * scale,
				backgroundColor: colors[rag],
				align: "left",
			};
			for (let i = 0; i <= BAR_STEPS; i++) {
				rich[`bf${i}_${rag}`] = {
					width: (INNER_W * i * scale) / BAR_STEPS,
					height: 5 * scale,
					lineHeight: 9 * scale,
					backgroundColor: i ? colors[rag] : "transparent",
					borderRadius: 2.5 * scale,
					align: "left",
				};
			}
		});
		for (let i = 0; i <= BAR_STEPS; i++) {
			rich[`bt${i}`] = {
				width: (INNER_W * i * scale) / BAR_STEPS,
				height: 5 * scale,
				lineHeight: 9 * scale,
				backgroundColor: i ? colors.track : "transparent",
				borderRadius: 2.5 * scale,
				align: "left",
			};
		}
		this.image_keys.forEach((url, i) => {
			rich[`img_${i}`] = {
				width: AVATAR * scale,
				height: AVATAR * scale,
				lineHeight: AVATAR * scale,
				backgroundColor: { image: this.avatars[url] },
				align: "left",
			};
		});
		return rich;
	}

	// Below READABLE_ZOOM the card text is a few pixels high, so cards show only the actual value in the RAG colour.
	label_option(zoom, colors) {
		const key = zoom >= READABLE_ZOOM ? "full" : "mini";
		return {
			show: true,
			formatter: (params) => (params.data && params.data[key]) || "",
			position: "inside",
			width: INNER_W * zoom,
			fontSize: STYLE.small.fontSize * zoom,
			lineHeight: 1,
			overflow: "truncate",
			ellipsis: "…",
			rich: this.rich(zoom, colors),
		};
	}

	/* ------------------------------------------------------------ render */

	view_rect(box) {
		const width = this.$chart.width() || 800;
		const height = this.$chart.height() || 600;
		const w = box.x1 - box.x0;
		const h = box.y1 - box.y0;
		return { left: (width - w) / 2, top: (height - h) / 2, width: w, height: h };
	}

	render({ fit = false, keep } = {}) {
		if (!this.chart) return;
		const empty = !this.trees.length;
		this.$empty.toggleClass("hidden", !empty);
		if (empty) {
			this.chart.clear();
			this.model = null;
			return;
		}
		this.image_keys = [];
		const model = this.build();
		this.model = model;
		let zoom = this.zoom;
		let center;
		if (fit) {
			[zoom, center] = this.fit_view(model);
		} else if (keep) {
			const item = model.data[model.index[keep.id]];
			center = item
				? [item.x - keep.offset[0] / zoom, item.y - keep.offset[1] / zoom]
				: [(model.box.x0 + model.box.x1) / 2, (model.box.y0 + model.box.y1) / 2];
		} else {
			center = this.current_center() || [(model.box.x0 + model.box.x1) / 2, (model.box.y0 + model.box.y1) / 2];
		}
		this.zoom = zoom;
		const colors = model.colors;
		this.chart.setOption(
			{
				backgroundColor: "transparent",
				animation: false,
				tooltip: {
					trigger: "item",
					confine: true,
					enterable: false,
					backgroundColor: colors.card,
					borderColor: colors.border,
					textStyle: { color: colors.text },
					extraCssText: "max-width: 320px; white-space: normal;",
					formatter: (params) => (params.dataType === "node" && params.data && params.data.tip) || "",
				},
				toolbox: {
					show: true,
					right: 12,
					top: 12,
					itemSize: 16,
					iconStyle: { borderColor: colors.muted },
					emphasis: { iconStyle: { borderColor: colors.text } },
					feature: {
						saveAsImage: {
							title: __("Save as Image"),
							name: this.image_name(),
							type: "png",
							pixelRatio: 2,
							backgroundColor: colors.bg,
							excludeComponents: ["toolbox", "thumbnail"],
						},
					},
				},
				thumbnail: {
					show: true,
					right: 12,
					bottom: 12,
					...this.thumbnail_size(),
					itemStyle: { color: colors.bg, borderColor: colors.border, borderWidth: 1 },
					windowStyle: { color: colors.none, opacity: 0.25, borderColor: colors.muted, borderWidth: 1 },
				},
				series: [
					{
						id: SERIES_ID,
						type: "graph",
						layout: "none",
						roam: true,
						roamTrigger: "global",
						nodeScaleRatio: 1,
						scaleLimit: { min: MIN_ZOOM, max: MAX_ZOOM },
						...this.view_rect(model.box),
						zoom,
						center,
						emphasis: { disabled: true },
						label: this.label_option(zoom, colors),
						lineStyle: { color: colors.border, width: 1.5, curveness: 0, opacity: 0.9 },
						edgeSymbol: ["none", "none"],
						data: model.data,
						links: model.links,
					},
				],
			},
			{ notMerge: true }
		);
	}

	current_zoom() {
		const series = this.chart && this.chart.getModel() && this.chart.getModel().getSeriesByIndex(0);
		const view = series && series.coordinateSystem;
		return view && view.getZoom ? view.getZoom() : this.zoom;
	}

	current_center() {
		const series = this.chart && this.chart.getModel() && this.chart.getModel().getSeriesByIndex(0);
		const view = series && series.coordinateSystem;
		return view && view.getCenter ? view.getCenter() : null;
	}

	rescale(zoom) {
		if (!this.model || !zoom || Math.abs(zoom - this.zoom) < 1e-3) return;
		this.zoom = zoom;
		this.chart.setOption({
			series: [{ id: SERIES_ID, label: this.label_option(zoom, this.model.colors) }],
		});
	}

	set_zoom(zoom) {
		if (!this.model) return;
		zoom = clamp(zoom, MIN_ZOOM, MAX_ZOOM);
		this.chart.setOption({ series: [{ id: SERIES_ID, zoom, center: this.current_center() }] });
		this.rescale(zoom);
	}

	// The chart area not covered by the toolbar (top) and the legend (bottom), in chart pixels.
	free_area() {
		const chart = this.$chart[0].getBoundingClientRect();
		const width = chart.width || 800;
		const height = chart.height || 600;
		const toolbar = this.$map.find(".dinext-goal-map-toolbar")[0].getBoundingClientRect();
		const legend = this.$map.find(".dinext-goal-map-legend")[0].getBoundingClientRect();
		const top = toolbar.height ? toolbar.bottom - chart.top + 8 : 12;
		const bottom = legend.height ? chart.bottom - legend.top + 8 : 12;
		const free_h = Math.max(height - top - bottom, height * 0.5);
		return { width, height, left: 12, top: Math.min(top, height - free_h), free_w: Math.max(width - 24, 50), free_h };
	}

	// axis "width" / "height" fills one dimension; along an axis that does not fit, the tree start is shown.
	fit_view(model, axis = "both") {
		const area = this.free_area();
		const box = model.box;
		const w = box.x1 - box.x0;
		const h = box.y1 - box.y0;
		const zx = area.free_w / w;
		const zy = area.free_h / h;
		const zoom =
			axis === "both"
				? clamp(Math.min(zx, zy), MIN_ZOOM, 1)
				: clamp(axis === "width" ? zx : zy, MIN_ZOOM, MAX_ZOOM);
		const target = (start, size, free) => (size * zoom <= free + 1 ? start + size / 2 : start + free / (2 * zoom));
		const px = target(box.x0, w, area.free_w);
		const py = target(box.y0, h, area.free_h);
		const cx = area.left + area.free_w / 2;
		const cy = area.top + area.free_h / 2;
		return [zoom, [px + (area.width / 2 - cx) / zoom, py + (area.height / 2 - cy) / zoom]];
	}

	fit(axis) {
		if (!this.model) return;
		const [zoom, center] = this.fit_view(this.model, axis);
		this.chart.setOption({ series: [{ id: SERIES_ID, zoom, center }] });
		this.rescale(zoom);
	}

	image_name() {
		const root = this.filters.root.get_value();
		return [__("Goal Map"), root].filter(Boolean).join(" ").replace(/[\\/:*?"<>|]+/g, "-");
	}

	update_view_rect() {
		if (!this.chart || !this.model) return;
		this.chart.resize();
		this.chart.setOption({
			thumbnail: this.thumbnail_size(),
			series: [{ id: SERIES_ID, ...this.view_rect(this.model.box) }],
		});
	}

	thumbnail_size() {
		const width = Math.round(clamp(this.$chart.width() * 0.22, 120, 220));
		return { width, height: Math.round(width * 0.7) };
	}

	on_click(params) {
		if (params.dataType !== "node" || !params.data) return;
		const item = params.data;
		if (item.kind === "goal") {
			frappe.set_route("Form", "Goal", item.goal);
		} else if (item.kind === "linked" && item.card && !item.card.restricted && !item.card.error) {
			frappe.route_options = item.card.route_options || {};
			frappe.set_route("List", item.card.doctype);
		} else if (item.kind === "toggle") {
			const card_id = `card:${item.node_id}`;
			const card = this.model.data[this.model.index[card_id]];
			const pixel = this.chart.convertToPixel({ seriesId: SERIES_ID }, [card.x, card.y]);
			const center = [this.$chart.width() / 2, this.$chart.height() / 2];
			this.collapsed.has(item.node_id) ? this.collapsed.delete(item.node_id) : this.collapsed.add(item.node_id);
			this.zoom = this.current_zoom();
			this.render({ keep: { id: card_id, offset: [pixel[0] - center[0], pixel[1] - center[1]] } });
		}
	}
}
