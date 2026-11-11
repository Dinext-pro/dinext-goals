module.exports = {
	video: false,
	defaultCommandTimeout: 30000,
	includeShadowDom: true,
	e2e: {
		baseUrl: "http://127.0.0.1:8000",
		specPattern: "cypress/integration/navigation_icons.js",
		supportFile: false,
	},
};
