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

// A full load turns the query into route_options; set_route from a list that is still
// loading would lose them, because the list view clears route_options when it renders.
const openMap = (root) => {
	cy.visit(`/app/goal-map?root=${encodeURIComponent(root)}`);
	cy.get(`.dinext-goal-card[data-goal="${root}"]`).should("exist");
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
		cy.get(".dinext-goal-card[data-goal]").should("have.length", 4);
		cy.get(".dinext-goal-map-links path").should("have.length", 3);
		cy.get(".dinext-goal-card[data-goal]").each(($card) => {
			expect($card.attr("class")).to.match(/dinext-goal-rag-(green|yellow|red)/);
		});
	});

	it("Collapse a branch", () => {
		signIn(MANAGER);
		openMap(seed().root);
		const middle = `.dinext-goal-card[data-goal="${seed().middle}"]`;
		cy.get(`.dinext-goal-card[data-goal="${seed().history}"]`).should("exist");
		cy.get(`${middle} .dinext-goal-card-toggle`).should("have.text", "\u2212").click();
		cy.get(`.dinext-goal-card[data-goal="${seed().history}"]`).should("not.exist");
		cy.get(`${middle} .dinext-goal-card-toggle`).should("have.text", "+");
	});

	it("Linked documents card", () => {
		signIn(MANAGER);
		openMap(seed().root);
		cy.get(".page-form [data-fieldname='show_linked'] input[type='checkbox']").check({ force: true });
		cy.window().then((win) => {
			cy.get(".dinext-goal-card.is-linked-doc")
				.should("have.length", 1)
				.within(() => {
					cy.contains(".dinext-goal-card-title", win.__("Task"));
					cy.contains(".dinext-goal-card-row", String(seed().task_count));
					cy.get(".dinext-goal-linked-open").should("contain", "Анализ");
				});
		});
		cy.get(".dinext-goal-linked-open").click();
		cy.window().its("cur_list.doctype").should("eq", "Task");
		cy.window().should((win) => {
			const filters = win.cur_list.filter_area.get().map((filter) => [filter[1], filter[3]]);
			expect(filters).to.deep.include(["project", seed().project]);
		});
	});
});
