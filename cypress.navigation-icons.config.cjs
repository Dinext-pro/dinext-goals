module.exports = {
	video: false,
	trashAssetsBeforeRuns: false,
	defaultCommandTimeout: 30000,
	includeShadowDom: true,
	e2e: {
		baseUrl: "http://127.0.0.1:8000",
		specPattern: "cypress/acceptance/navigation_icons.cy.js",
		supportFile: false,
	},
};
