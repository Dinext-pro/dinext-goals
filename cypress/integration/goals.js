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
const mapItems = (win, kind) => mapChart(win).getOption().series[0].data.filter((item) => item.kind === kind);
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

// Centers the item first: the toolbar, legend and minimap overlay the chart edges.
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

const createDialog = (win) => win.frappe.ui.open_dialogs.find((dialog) => dialog.fields_dict.param__projects);

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
				expect(card.label.formatter, "avatar").to.match(/^\{img_\d+\|\}/m);
				expect(card.label.formatter, "actual value").to.include(`{v_${card.rag}|`);
			});
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
		cy.window().should((win) => expect(mapChart(win).getOption().series[0].label.show, "labels below the readable zoom").to.eq(false));
	});

	it("Map layout and filters", () => {
		signIn(MANAGER);
		openMap(seed().root);
		setMapFilter("orient", "LR");
		cy.window().should((win) => {
			const x = (name) => mapItem(win, "goal", (card) => card.goal === name).x;
			expect(x(seed().root), "left to right").to.be.lessThan(x(seed().middle));
			expect(win.localStorage.getItem("dinext_goal_map_orient")).to.eq("LR");
		});
		setMapFilter("orient", "TB");
		setMapFilter("status", "Draft");
		cy.get(".dinext-goal-map-empty").should("be.visible");
		setMapFilter("status", "");
		cy.window().should((win) => expect(mapItems(win, "goal")).to.have.length(4));
		cy.window().then((win) => setMapFilter("year", String(win.moment().year() - 2)));
		cy.get(".dinext-goal-map-empty").should("be.visible");
		cy.window().then((win) => {
			setMapFilter("year", String(win.moment().year()));
			setMapFilter("month", String(win.moment().month() + 1));
		});
		cy.window().should((win) => expect(mapItems(win, "goal")).to.have.length(4));
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
		clickMapItem("goal", (card) => card.goal === seed().middle);
		cy.window().its("cur_frm.doc.name").should("eq", seed().middle);
	});

	it("Linked documents card", () => {
		signIn(MANAGER);
		openMap(seed().root);
		cy.get(".page-form [data-fieldname='show_linked'] input[type='checkbox']").check({ force: true });
		cy.window().should((win) => {
			const linked = mapItems(win, "linked");
			expect(linked).to.have.length(1);
			expect(linked[0].card.doctype).to.eq("Task");
			expect(linked[0].label.formatter).to.include(win.__("Task"));
			expect(linked[0].label.formatter).to.include(`{v_none|${win.format_number(seed().task_count, null, 0)}}`);
			expect(linked[0].label.formatter).to.include("Анализ");
			expect(overflowingCards(win), "text inside cards").to.be.empty;
		});
		clickMapItem("linked", () => true);
		cy.window().its("cur_list.doctype").should("eq", "Task");
		cy.window().should((win) => {
			const filters = win.cur_list.filter_area.get().map((filter) => [filter[1], filter[3]]);
			expect(filters).to.deep.include(["project", seed().project]);
		});
	});
});
