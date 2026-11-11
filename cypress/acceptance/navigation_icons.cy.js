describe("Goals navigation", () => {
	it("draws the same Goals arrow on the Dinext card and sidebar in both themes", () => {
		cy.request({
			method: "POST",
			url: "/api/method/login",
			body: { usr: "Administrator", pwd: Cypress.env("adminPassword") },
			log: false,
		});
		cy.visit("/app/dinext");
		const sidebarIcon = '.sidebar-item-container[item-name="Goals"] .sidebar-item-icon use';
		const cardIcon = '.dinext-workspace-hub__card[href="/app/goals"] .dinext-workspace-hub__card-icon use';

		for (const theme of ["light", "dark"]) {
			cy.window().then((win) => {
				win.document.documentElement.setAttribute("data-theme-mode", theme);
				win.frappe.ui.set_theme(theme);
			});
			cy.get("html").should("have.attr", "data-theme", theme);
			for (const selector of [sidebarIcon, cardIcon]) {
				cy.get(selector).should(($icon) => {
					expect($icon.attr("href")).to.match(/#icon-arrow-up-right$/);
					expect($icon[0].getBBox().width).to.be.greaterThan(0);
				});
			}
		}
	});
});
