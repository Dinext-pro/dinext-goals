const HELPERS = "dinext_goals.tests.ui_test_helpers";
const MANAGER = "goals.cy.manager@example.com";
const OWNER = "goals.cy.owner@example.com";

const seed = () => Cypress.env("goals");

const signIn = (email, path) => {
	cy.login(email);
	cy.openDesk(path || "/app/goal");
};

const openForm = (doctype, name) => {
	cy.visit(`/app/${doctype}/${encodeURIComponent(name)}`);
	cy.window().its("cur_frm.doc.name").should("eq", name);
};

const formButton = (label) =>
	cy
		.window()
		.its("cur_frm.custom_buttons")
		.its(label)
		.should(($button) => expect($button).to.have.length(1));

const goalMap = (win) => win.$('[data-page-route="goal-map"]')[0].goal_map;
const mapChart = (win) => win.$(".dinext-goal-map-chart").data("dinext-chart-instance");
// A cleared chart (no goals match) has no series.
const mapItems = (win, kind) =>
	((mapChart(win).getOption().series || [])[0] || { data: [] }).data.filter((item) => item.kind === kind);
const mapItem = (win, kind, test) => mapItems(win, kind).find(test);

// A full load turns the query into route_options; set_route from a list that is still
// loading would lose them, because the list view clears route_options when it renders.
const openMap = (root) => {
	cy.visit(`/app/goal-map?root=${encodeURIComponent(root)}`);
	cy.get(".dinext-goal-map-chart canvas").should("exist");
	cy.window().should((win) => {
		expect(mapItems(win, "goal").map((item) => item.goal)).to.include(root);
	});
};

const setMapFilter = (fieldname, value) =>
	cy.window().then((win) => goalMap(win).page.fields_dict[fieldname].set_value(value));

// Centers the item first: the toolbox, legend and minimap overlay the chart edges.
const clickMapItem = (kind, test) =>
	cy.window().then((win) => {
		const item = mapItem(win, kind, test);
		expect(item, `${kind} item`).to.exist;
		const chart = mapChart(win);
		chart.setOption({ series: [{ id: "goals", center: [item.x, item.y] }] });
		const [x, y] = chart.convertToPixel({ seriesIndex: 0 }, [item.x, item.y]);
		cy.get(".dinext-goal-map-chart").click(x, y);
	});

const globalBox = (el, x, y, width, height) => {
	const [a, b, c, d, e, f] = el.getComputedTransform() || [1, 0, 0, 1, 0, 0];
	const xs = [x, x + width].flatMap((px) => [y, y + height].map((py) => a * px + c * py + e));
	const ys = [x, x + width].flatMap((px) => [y, y + height].map((py) => b * px + d * py + f));
	return { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) };
};

// Card text is laid out at 1:1 and drawn at fontSize * zoom; every drawn token must stay inside
// its card. Images report a cached rect from an earlier layout, so their style box is used.
const overflowingCards = (win) => {
	const data = mapChart(win).getModel().getSeriesByIndex(0).getData();
	const options = mapChart(win).getOption().series[0].data;
	return options.filter((item, i) => {
		if (item.kind !== "goal" && item.kind !== "linked") return false;
		const symbol = data.getItemGraphicEl(i).childAt(0);
		const text = symbol.getTextContent();
		if (!text) return true;
		const rect = symbol.getBoundingRect();
		const card = globalBox(symbol, rect.x, rect.y, rect.width, rect.height);
		return text.childrenRef().some((token) => {
			const r = token.type === "image" ? token.style : token.getBoundingRect();
			const box = globalBox(text, r.x || 0, r.y || 0, r.width || 0, r.height || 0);
			return box.x0 < card.x0 - 0.5 || box.y0 < card.y0 - 0.5 || box.x1 > card.x1 + 0.5 || box.y1 > card.y1 + 0.5;
		});
	});
};

// Grouped buttons sit in closed dropdowns; labels are resolved through the desk translations.
const clickFormButton = (label) =>
	cy
		.window()
		.should((win) => expect(win.cur_frm.custom_buttons[win.__(label)], label).to.have.length(1))
		.then((win) => win.cur_frm.custom_buttons[win.__(label)][0].click());
const openDialog = (win, fieldname) => win.frappe.ui.open_dialogs.find((dialog) => dialog.fields_dict[fieldname]);
const providerOptions = (win, field) => (win.cur_frm.get_field(field).df.options || []).map((option) => option.value);

const createDialog = (win) => win.frappe.ui.open_dialogs.find((dialog) => dialog.fields_dict.param__projects);

const MINI = /^\{mini(_small)?_(green|yellow|red|none|link)\|[^{}|]+\}$/;
const drawnText = (win, item) => {
	const index = mapChart(win).getOption().series[0].data.findIndex((option) => option.id === item.id);
	const symbol = mapChart(win).getModel().getSeriesByIndex(0).getData().getItemGraphicEl(index).childAt(0);
	const text = symbol.getTextContent();
	return text && !text.ignore && !text.invisible ? text.style.text : "";
};

// The model box (tree plus margin) in chart pixels and the area free of the toolbox and the legend.
const fitBounds = (win) => {
	const map = goalMap(win);
	const { box } = map.model;
	const [x0, y0] = mapChart(win).convertToPixel({ seriesId: "goals" }, [box.x0, box.y0]);
	const [x1, y1] = mapChart(win).convertToPixel({ seriesId: "goals" }, [box.x1, box.y1]);
	const area = map.free_area();
	return { box: { x0, y0, x1, y1 }, free: { x0: area.left, y0: area.top, x1: area.left + area.free_w, y1: area.top + area.free_h } };
};

// Toolbox icons are drawn on the canvas: click the centre of the icon path of the feature.
const toolboxIcon = (win, feature) => {
	const chart = mapChart(win);
	const view = chart.getViewOfComponentModel(chart.getModel().getComponent("toolbox"));
	const path = view._features[feature].model.iconPaths[feature];
	const rect = path.getBoundingRect();
	const box = globalBox(path, rect.x, rect.y, rect.width, rect.height);
	return [(box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2];
};
const mapAction = (feature) =>
	cy.window().then((win) => {
		const [x, y] = toolboxIcon(win, feature);
		cy.get(".dinext-goal-map-chart").click(x, y);
	});
const MAP_ACTIONS = {
	myZoomIn: "Увеличить",
	myZoomOut: "Уменьшить",
	myFit: "По размеру экрана",
	myFitWidth: "Вписать по ширине",
	myFitHeight: "Вписать по высоте",
	myExpandAll: "Развернуть все",
	myCollapseAll: "Свернуть все",
	myShowLinked: "Показывать связанные документы",
	myOrientTB: "Сверху вниз",
	myOrientLR: "Слева направо",
	saveAsImage: "Сохранить как изображение",
};

// A chart pixel with no card, toggle or edge under it, inside the free area.
const emptyPoint = (win) => {
	const zr = mapChart(win).getZr();
	const { free } = fitBounds(win);
	for (let y = free.y0 + 10; y < free.y1; y += 10) {
		for (let x = free.x0 + 10; x < free.x1; x += 10) {
			if (!zr.handler.findHover(x, y).target) return [x, y];
		}
	}
	return null;
};

const monthValue = (moment) => moment.format("YYYY-MM");

// Other apps on the site may show permission messages on the Project form for this test user.
const closeDialogs = () => cy.window().then((win) => win.$(".modal:visible").modal("hide"));

context("goal analytics", () => {
	before(() => {
		signIn(MANAGER);
		cy.call(`${HELPERS}.seed_goals_cypress`).then((res) => {
			Cypress.env("goals", res.body.message);
		});
	});

	after(() => {
		signIn(MANAGER);
		cy.call(`${HELPERS}.cleanup_goals_cypress`);
	});

	it("Open the workspace", () => {
		signIn(OWNER, `/app/${encodeURIComponent("цели")}`);
		cy.get(".number-widget-box").should("have.length", 9);
		cy.get(".dashboard-widget-box").should("have.length", 4);
		cy.contains(".number-widget-box", "Мои цели")
			.find(".number")
			.should("have.text", String(seed().owner_goals));
		cy.noPermissionDialog();
	});

	it("Goal owner cannot open a goal outside their tree", () => {
		signIn(OWNER);
		cy.visit(`/app/goal/${encodeURIComponent(seed().root)}`, { failOnStatusCode: false });
		cy.get(".modal:visible").should(($modal) => {
			const denied = /Нет разрешения|не имеет доступа|Not permitted|no permission/i.test($modal.text());
			expect(denied, "permission error dialog").to.eq(true);
		});
		openForm("goal", seed().history);
	});

	it("Goal with history", () => {
		signIn(OWNER);
		openForm("goal", seed().history);
		cy.get("#dinext-goal-trend .dinext-goal-trend-chart canvas").should("exist");
		cy.window().should((win) => {
			const chart = win.$("#dinext-goal-trend").data("chart");
			expect(chart, "trend chart").to.exist;
			const [actual, planned] = chart.getOption().series;
			expect(actual.data, "actual progress").to.have.length(3);
			expect(planned.data.length, "planned line").to.be.greaterThan(1);
		});
		cy.get("[data-testid='goal-kpis'] .dinext-goal-kpi-card").should(($tiles) => {
			expect([...$tiles].map((tile) => tile.dataset.kpi)).to.deep.eq(["actual", "target", "achievement", "progress"]);
		});
		cy.get("[data-kpi='actual']").should("have.class", "is-rag").find(".dinext-goal-kpi-value").should("have.text", "30");
		cy.get("[data-kpi='target'] .dinext-goal-kpi-value").should("have.text", "100");
		cy.window().then((win) => {
			cy.get("[data-kpi='achievement'] .dinext-goal-kpi-value").should("have.text", `${win.format_number(30, null, 1)}%`);
		});
	});

	it("Recalculate from the form", () => {
		signIn(MANAGER);
		openForm("goal", seed().middle);
		cy.window().its("cur_frm.doc.progress").should("eq", 0);
		formButton("Рассчитать прогресс").click();
		cy.contains("#alert-container", "Пересчитано целей").should("exist");
		cy.window().its("cur_frm.doc.progress").should("eq", 30);
		cy.get("[data-testid='goal-kpis'] .dinext-goal-kpi-card").should(($tiles) => {
			expect([...$tiles].map((tile) => tile.dataset.kpi)).to.deep.eq(["progress", "planned", "deviation", "achievement"]);
		});
		cy.window().then((win) => {
			cy.get("[data-kpi='achievement'] .dinext-goal-kpi-value").should("have.text", `${win.format_number(30, null, 1)}%`);
		});
		cy.get("[data-kpi='deviation'] .dinext-goal-kpi-value")
			.invoke("text")
			.should("match", /^[-−]/, "behind the plan");
	});

	it("Effective parameters", () => {
		signIn(OWNER);
		openForm("goal", seed().history);
		cy.get(".dinext-goal-params")
			.contains("tr", "cost_center")
			.find(`a[href="/app/goal/${seed().middle}"]`)
			.should("contain", seed().middle_subject);
	});

	it("Ask-on-create parameters", () => {
		signIn(MANAGER);
		openForm("goal-template", seed().template);
		formButton("Создать цели").click();
		cy.get(".modal:visible [data-fieldname='param__projects']").should("be.visible");
		cy.window().should((win) => expect(createDialog(win), "create goals dialog").to.exist);
		cy.window().then((win) => {
			const dialog = createDialog(win);
			expect(dialog.fields_dict.param__projects.df.fieldtype).to.eq("MultiSelectList");
			return dialog.set_value("param__projects", [seed().project]);
		});
		cy.get(".modal:visible .btn-modal-primary").click();
		cy.window().its("cur_frm.doc.goal_template").should("eq", seed().template);
		cy.window().then((win) => {
			const doc = win.cur_frm.doc;
			expect(doc.doctype).to.eq("Goal");
			expect(doc.is_group).to.eq(1);
			const projects = (doc.parameters || []).find((row) => row.code === "projects");
			expect(projects, "projects parameter").to.exist;
			expect(projects.value_list).to.eq(seed().project);
		});
	});

	it("Open the map for a root goal", () => {
		signIn(MANAGER);
		openMap(seed().root);
		cy.window().should((win) => {
			const cards = mapItems(win, "goal");
			expect(cards.map((card) => card.goal)).to.have.members([seed().root, seed().middle, seed().history, seed().tasks]);
			cards.forEach((card) => {
				expect(card.rag, card.goal).to.match(/^(green|yellow|red)$/);
				expect(card.full, "avatar").to.match(/^\{img_\d+\|\}/m);
				expect(card.full, "actual value").to.include(`{v_${card.rag}|`);
				expect(card.mini, "actual value at a small zoom").to.match(MINI).and.include(`{mini`).and.include(`_${card.rag}|`);
			});
			const features = mapChart(win).getOption().toolbox[0].feature;
			expect(Object.keys(features), "map actions in the toolbox").to.deep.eq(Object.keys(MAP_ACTIONS));
			Object.entries(MAP_ACTIONS).forEach(([key, title]) => expect(features[key].title, key).to.eq(title));
			expect(win.$(".dinext-goal-map .btn"), "no button bar over the map").to.have.length(0);
			expect(mapItems(win, "toggle"), "toggles").to.have.length(2);
			const y = (name) => mapItem(win, "goal", (card) => card.goal === name).y;
			expect(y(seed().root), "top to bottom").to.be.lessThan(y(seed().middle));
			expect(y(seed().middle)).to.be.lessThan(y(seed().history));
			expect(mapChart(win).getModel().getComponent("thumbnail"), "minimap").to.exist;
			expect(overflowingCards(win).map((card) => card.goal), "text inside cards").to.be.empty;
		});
		cy.window().then((win) => goalMap(win).set_zoom(0.5));
		cy.window().should((win) => expect(overflowingCards(win), "text inside cards when zoomed out").to.be.empty);
		cy.window().then((win) => goalMap(win).set_zoom(0.3));
		cy.window().should((win) => {
			mapItems(win, "goal").forEach((card) => expect(drawnText(win, card), `${card.goal} at zoom 0.3`).to.eq(card.mini));
			expect(overflowingCards(win), "actual value inside cards").to.be.empty;
		});
	});

	it("Map layout and filters", () => {
		signIn(MANAGER);
		openMap(seed().root);
		cy.get("[data-page-route='goal-map'] .page-form.row > .col-md-2").should(($fields) => {
			const tops = [...$fields].map((el) => el.getBoundingClientRect().top);
			expect($fields, "map filters").to.have.length(8);
			expect(Math.max(...tops) - Math.min(...tops), "filters on one row").to.be.lessThan(2);
		});
		mapAction("myOrientLR");
		cy.window().should((win) => {
			const x = (name) => mapItem(win, "goal", (card) => card.goal === name).x;
			expect(x(seed().root), "left to right").to.be.lessThan(x(seed().middle));
			expect(win.localStorage.getItem("dinext_goal_map_orient")).to.eq("LR");
		});
		mapAction("myOrientLR");
		cy.window().should((win) => expect(goalMap(win).orient).to.eq("LR"));
		mapAction("myOrientTB");
		cy.window().should((win) => {
			expect(goalMap(win).orient).to.eq("TB");
			expect(goalMap(win).get_filters().status).to.deep.eq(["Active"]);
		});
		setMapFilter("status", ["Draft"]);
		cy.get(".dinext-goal-map-empty").should("be.visible");
		setMapFilter("status", ["Draft", "Active"]);
		cy.window().should((win) => expect(mapItems(win, "goal")).to.have.length(4));
		cy.window().then((win) => {
			setMapFilter("period_from", monthValue(win.moment().add(4, "months")));
		});
		cy.get(".dinext-goal-map-empty").should("be.visible");
		cy.window().then((win) => {
			const fields = goalMap(win).page.fields_dict;
			return fields.period_from
				.set_value(monthValue(win.moment()))
				.then(() => fields.period_to.set_value(monthValue(win.moment().subtract(1, "months"))));
		});
		cy.window().should((win) => {
			expect(goalMap(win).filters.period_from.get_value(), "the earlier bound follows").to.eq(monthValue(win.moment().subtract(1, "months")));
			expect(mapItems(win, "goal")).to.have.length(4);
		});
		cy.get(".page-form [data-fieldname='period_from'] select option")
			.eq(1)
			.should("have.text", `Январь ${new Date().getFullYear() - 2}`);

		// Without a root, types, owners and the project pick the trees.
		const drawn = (win) => mapItems(win, "goal").map((card) => card.goal);
		cy.window().then((win) => {
			const fields = goalMap(win).page.fields_dict;
			return fields.period_from
				.set_value("")
				.then(() => fields.period_to.set_value(""))
				.then(() => fields.project.set_value(seed().project))
				.then(() => fields.root.set_value(""));
		});
		cy.window().should((win) => expect(drawn(win)).to.include(seed().root));
		setMapFilter("goal_type", ["OKR"]);
		cy.window().should((win) => expect(drawn(win)).not.to.include(seed().root));
		setMapFilter("goal_type", ["OKR", "KPI"]);
		cy.window().should((win) => expect(drawn(win)).to.include(seed().root));
		setMapFilter("goal_owner", [OWNER]);
		cy.window().should((win) => {
			expect(drawn(win)).not.to.include(seed().root);
			expect(drawn(win)).to.include.members([seed().middle, seed().history]);
		});
		setMapFilter("goal_owner", [MANAGER, OWNER]);
		cy.window().should((win) => expect(drawn(win)).to.include(seed().root));
	});

	it("Fit and pan the map", () => {
		signIn(MANAGER);
		openMap(seed().root);
		const inside = (inner, outer) => {
			expect(inner.x0, "left").to.be.at.least(outer.x0 - 1);
			expect(inner.y0, "top").to.be.at.least(outer.y0 - 1);
			expect(inner.x1, "right").to.be.at.most(outer.x1 + 1);
			expect(inner.y1, "bottom").to.be.at.most(outer.y1 + 1);
		};
		cy.window().then((win) => goalMap(win).set_zoom(1));
		mapAction("myZoomIn");
		cy.window().should((win) => expect(goalMap(win).zoom).to.be.closeTo(1.25, 0.01));
		mapAction("myZoomOut");
		cy.window().should((win) => expect(goalMap(win).zoom).to.be.closeTo(1, 0.01));
		cy.window().then((win) => goalMap(win).set_zoom(2));
		mapAction("myFit");
		cy.window().should((win) => {
			const { box, free } = fitBounds(win);
			inside(box, free);
			const touches = Math.abs(box.x0 - free.x0) < 1.5 || Math.abs(box.y0 - free.y0) < 1.5 || goalMap(win).zoom === 1;
			expect(touches, "the tree fills the free area").to.eq(true);
		});
		mapAction("myFitWidth");
		cy.window().should((win) => {
			const { box, free } = fitBounds(win);
			expect(box.x0, "left edge").to.be.closeTo(free.x0, 1.5);
			expect(box.x1, "right edge").to.be.closeTo(free.x1, 1.5);
		});
		mapAction("myFitHeight");
		cy.window().should((win) => {
			const { box, free } = fitBounds(win);
			expect(box.y0, "top edge").to.be.closeTo(free.y0, 1.5);
			expect(box.y1, "bottom edge").to.be.closeTo(free.y1, 1.5);
		});
		cy.window().then((win) => {
			const point = emptyPoint(win);
			expect(point, "an empty point").to.exist;
			const [x, y] = point;
			const before = goalMap(win).current_center();
			const zoom = goalMap(win).current_zoom();
			cy.get(".dinext-goal-map-chart > div")
				.first()
				.trigger("mousedown", x, y, { button: 0, buttons: 1 })
				.trigger("mousemove", x + 30, y + 20, { button: 0, buttons: 1 })
				.trigger("mousemove", x + 60, y + 40, { button: 0, buttons: 1 })
				.trigger("mouseup", x + 60, y + 40, { button: 0 });
			cy.window().should((w) => {
				const after = goalMap(w).current_center();
				expect(before[0] - after[0], "pan x").to.be.closeTo(60 / zoom, 1);
				expect(before[1] - after[1], "pan y").to.be.closeTo(40 / zoom, 1);
			});
		});
	});

	it("Project goals", () => {
		signIn(MANAGER);
		openForm("project", seed().project);
		cy.call("frappe.client.get_list", {
			doctype: "Goal",
			filters: [["Goal Project", "project", "=", seed().project]],
			fields: ["name"],
			limit_page_length: 0,
		}).then((res) => Cypress.env("projectGoals", String(new Set(res.body.message.map((row) => row.name)).size)));
		cy.contains(".form-dashboard .form-link-title", "Цели")
			.parent()
			.find(".document-link[data-doctype='Goal'] .count")
			.should(($count) => expect($count.text()).to.eq(Cypress.env("projectGoals")));
		closeDialogs();
		formButton("Карта целей").click({ force: true });
		cy.location("pathname").should("eq", "/app/goal-map");
		cy.window().should((win) => {
			expect(goalMap(win).filters.project.get_value()).to.eq(seed().project);
			expect(mapItems(win, "goal").map((card) => card.goal)).to.include(seed().root);
		});
		openForm("project", seed().project);
		cy.get(".form-dashboard .document-link[data-doctype='Goal'] .count").should(($count) =>
			expect($count.text()).to.eq(Cypress.env("projectGoals"))
		);
		closeDialogs();
		cy.get(".form-dashboard .document-link[data-doctype='Goal'] .badge-link").click({ force: true });
		cy.window().its("cur_list.doctype").should("eq", "Goal");
		cy.window().should((win) => {
			const filters = win.cur_list.filter_area.get().map((filter) => [filter[1], filter[3]]);
			expect(filters).to.deep.include(["project", seed().project]);
			expect(win.cur_list.data, "goals of the project").not.to.be.empty;
		});
	});

	it("Collapse a branch", () => {
		signIn(MANAGER);
		openMap(seed().root);
		const middleToggle = (item) => item.goal === seed().middle;
		cy.window().should((win) => {
			expect(mapItems(win, "goal").map((card) => card.goal)).to.include(seed().history);
			expect(mapItem(win, "toggle", middleToggle).collapsed).to.eq(false);
		});
		clickMapItem("toggle", middleToggle);
		cy.window().should((win) => {
			expect(mapItems(win, "goal").map((card) => card.goal)).not.to.include(seed().history);
			expect(mapItem(win, "toggle", middleToggle).collapsed).to.eq(true);
		});
		mapAction("myExpandAll");
		cy.window().should((win) => {
			expect(mapItems(win, "goal").map((card) => card.goal)).to.include(seed().history);
			expect(mapItem(win, "toggle", middleToggle).collapsed).to.eq(false);
		});
		mapAction("myCollapseAll");
		cy.window().should((win) => {
			expect(mapItems(win, "goal").map((card) => card.goal)).not.to.include(seed().history);
			expect(mapItem(win, "toggle", middleToggle).collapsed).to.eq(true);
		});
		clickMapItem("goal", (card) => card.goal === seed().middle);
		cy.window().its("cur_frm.doc.name").should("eq", seed().middle);
	});

	it("Drill down from the actual tile", () => {
		signIn(MANAGER);
		openForm("goal", seed().tasks);
		cy.get("[data-kpi='actual']").should("have.attr", "data-drill", "1");
		cy.get("[data-kpi='achievement']").should("not.have.attr", "data-drill");
		cy.get("[data-kpi='achievement']").dblclick();
		cy.location("pathname").should("include", "/app/goal/");
		cy.get("[data-kpi='target']").dblclick();
		cy.get(".modal:visible").should("contain", "План введен на карточке цели");
		cy.window().then((win) => {
			win.$(".modal-backdrop").remove();
			win.$("body").removeClass("modal-open");
			win.$(".modal").remove();
		});
		cy.get(".modal").should("not.exist");
		cy.get("[data-kpi='actual']").dblclick();
		cy.window().its("cur_list.doctype").should("eq", "Task");
		cy.window().should((win) => {
			const filters = win.cur_list.filter_area.get().map((filter) => [filter[1], filter[3]]);
			expect(filters).to.deep.include(["project", seed().project]);
		});
	});

	it("Linked documents card", () => {
		signIn(MANAGER);
		openMap(seed().root);
		mapAction("myShowLinked");
		cy.window().should((win) => {
			const linked = mapItems(win, "linked");
			expect(linked).to.have.length(1);
			expect(linked[0].card.doctype).to.eq("Task");
			expect(linked[0].full).to.include(win.__("Task"));
			expect(linked[0].full).to.include(`{v_none|${win.format_number(seed().task_count, null, 0)}}`);
			expect(linked[0].full).to.include("Анализ");
			expect(linked[0].mini).to.match(MINI).and.include(win.format_number(seed().task_count, null, 0));
			expect(overflowingCards(win), "text inside cards").to.be.empty;
		});
		clickMapItem("linked", () => true);
		cy.window().its("cur_list.doctype").should("eq", "Task");
		cy.window().should((win) => {
			const filters = win.cur_list.filter_area.get().map((filter) => [filter[1], filter[3]]);
			expect(filters).to.deep.include(["project", seed().project]);
		});
	});

	it("Provider selection on a goal", () => {
		signIn(MANAGER);
		cy.visit("/app/goal/new");
		cy.window().its("cur_frm.doc.__islocal").should("eq", 1);
		cy.window().then((win) => win.cur_frm.set_value({ progress_method: "Auto", metric_source: "Provider" }));
		cy.window().should((win) => {
			const textOf = (option) =>
				option && typeof option === "object" ? String(option.label ?? "") : String(option ?? "");
			const metric = win.cur_frm.get_field("metric_provider").df.options || [];
			const target = win.cur_frm.get_field("target_provider").df.options || [];
			expect(metric.map(textOf).concat(target.map(textOf)).join("\n"), "option text").not.to.include(
				"[object Object]"
			);
			expect(providerOptions(win, "metric_provider")).to.include.members(["gl_profit", "timesheet_utilization"]);
			expect(providerOptions(win, "target_provider")).to.include("project_budget_profit").and.not.include("gl_profit");
		});
		cy.window().then((win) => win.cur_frm.set_value("metric_provider", "gl_profit"));
		cy.get("#goal-metric_tab-tab").click();
		cy.get("select[data-fieldname='metric_provider']").should("have.value", "gl_profit");
		cy.get("select[data-fieldname='metric_provider'] option").each(($option) => {
			expect($option.text(), "metric provider option").not.to.include("[object Object]");
		});
		cy.get("[data-testid='metric-provider-info'][data-provider='gl_profit']")
			.should("be.visible")
			.find(".dinext-goal-provider-details li")
			.should("have.length.greaterThan", 1);
		cy.get("[data-testid='metric-provider-info'] .dinext-goal-provider-params").should("contain", "cost_center");
		cy.window().then((win) => win.cur_frm.set_value("metric_provider", "timesheet_utilization"));
		cy.get("[data-testid='metric-provider-info']").should("have.attr", "data-provider", "timesheet_utilization");
	});

	it("Provider selection in a template row", () => {
		signIn(MANAGER);
		openForm("goal-template", seed().template);
		cy.window().then((win) => {
			const row = win.cur_frm.doc.items.find((item) => item.item_key === "PRJ");
			win.cur_frm.fields_dict.items.grid.grid_rows_by_docname[row.name].show_form();
			return win.frappe.model
				.set_value(row.doctype, row.name, { progress_method: "Auto", metric_source: "Provider" })
				.then(() => win.frappe.model.set_value(row.doctype, row.name, "metric_provider", "project_budget_profit"));
		});
		cy.get(".grid-row-open [data-testid='metric-provider-info']")
			.should("have.attr", "data-provider", "project_budget_profit")
			.and("contain", "projects");
		cy.get(".grid-row-open select[data-fieldname='metric_provider']").should("have.value", "project_budget_profit");
	});

	it("Goal campaign for a team", () => {
		signIn(MANAGER);
		cy.visit("/app/goal-campaign/new");
		cy.window().its("cur_frm.doc.period_label").should("not.be.empty");
		cy.window().then((win) => {
			const frm = win.cur_frm;
			expect(frm.doc.period_type).to.eq("Quarter");
			expect(win.moment(frm.doc.period_start).isAfter(win.moment())).to.eq(true, "next quarter");
			return frm.set_value({
				title: `CY Goals Campaign ${frm.doc.period_label}`,
				default_template: seed().template,
			});
		});
		clickFormButton("Users");
		cy.window().should((win) => expect(openDialog(win, "users"), "users dialog").to.exist);
		cy.window().then((win) => openDialog(win, "users").set_value("users", [MANAGER, OWNER]));
		cy.get(".modal:visible .btn-modal-primary").click();
		cy.window().should((win) => {
			const rows = win.cur_frm.doc.items || [];
			expect(rows.map((row) => [row.row_key, row.goal_owner, row.template])).to.deep.eq([
				["R1", MANAGER, seed().template],
				["R2", OWNER, seed().template],
			]);
		});
		cy.window().then((win) => {
			const [lead, member] = win.cur_frm.doc.items;
			win.frappe.model.set_value(member.doctype, member.name, "parent_row", lead.row_key);
			win.cur_frm.fields_dict.items.grid.grid_rows.forEach((row) => row.select(true));
		});
		clickFormButton("Set Parameters");
		cy.window().should((win) => expect(openDialog(win, "param__projects"), "parameters dialog").to.exist);
		cy.window().then((win) => openDialog(win, "param__projects").set_value("param__projects", [seed().project]));
		cy.get(".modal:visible .btn-modal-primary").click();
		cy.window().should((win) => {
			win.cur_frm.doc.items.forEach((row) => {
				expect(JSON.parse(row.parameter_values)).to.deep.eq({ projects: [seed().project] });
			});
		});
		cy.window().then((win) => win.cur_frm.save());
		cy.window().its("cur_frm.doc.__islocal").should("not.exist");

		clickFormButton("Preview");
		cy.get("[data-testid='campaign-preview'] tr[data-row]").should("have.length", 2);
		cy.get("[data-testid='campaign-preview'] tr[data-row='R2']").should("contain", "R1");

		clickFormButton("Create Goals");
		cy.get(".modal:visible .btn-modal-primary").click();
		cy.window().its("cur_frm.doc.status").should("eq", "Created");
		cy.window().then((win) => {
			const [lead, member] = win.cur_frm.doc.items;
			expect([lead.status, member.status]).to.deep.eq(["Created", "Created"]);
			return win.frappe.db.get_doc("Goal", member.root_goal).then((goal) => {
				expect(goal.goal_owner).to.eq(OWNER);
				expect(goal.parents.map((row) => row.parent_goal)).to.deep.eq([lead.root_goal]);
				expect(goal.exp_start_date).to.eq(win.cur_frm.doc.period_start);
				expect(goal.exp_end_date).to.eq(win.cur_frm.doc.period_end);
			});
		});
		cy.window().then((win) => expect(win.cur_frm.custom_buttons[win.__("Create Goals")]).to.not.exist);

		cy.window().then((win) => cy.wrap(win.cur_frm.doc.period_end).as("periodEnd"));
		clickFormButton("Next Period");
		cy.get("@periodEnd").then((end) => {
			cy.window().should((win) => {
				const doc = win.cur_frm.doc;
				expect(doc.period_start).to.eq(win.frappe.datetime.add_days(end, 1));
				expect(doc.status).to.eq("Draft");
				expect(doc.title).to.include(doc.period_label);
				expect(doc.items.map((row) => [row.status, row.parent_row || ""])).to.deep.eq([
					["Pending", ""],
					["Pending", "R1"],
				]);
			});
		});
	});

	it("Top goal in the navbar", () => {
		signIn(OWNER);
		cy.get(".navbar .dinext-goal-navbar-value")
			.should("have.attr", "data-goal", seed().middle)
			.and("have.attr", "class")
			.and("match", /dinext-goal-rag-(green|yellow|red)/);
		cy.get(".navbar .navbar-nav > li").first().should("have.class", "dinext-goal-navbar");
		cy.get(".navbar .dinext-goal-navbar").next().should("have.class", "dropdown-notifications");
		cy.get(".navbar .dinext-goal-navbar-unit").should("have.text", "%");
		cy.get(".navbar .dinext-goal-navbar-value").click();
		cy.location("pathname").should("eq", "/app/goal-map");
		cy.window().should((win) => {
			expect(goalMap(win).filters.root.get_value()).to.eq(seed().middle);
			expect(mapItems(win, "goal").map((item) => item.goal)).to.include.members([seed().middle, seed().history]);
		});
	});
});
