const { execFileSync } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const HELPERS = "dinext_goals.tests.ui_test_helpers";

// run-ui-tests starts Cypress from the app source, which may live outside the bench;
// it already requires ../frappe there, so that path leads back to the bench.
function benchRoot() {
	const frappeApp = path.resolve(process.cwd(), "..", "frappe");
	const starts = [
		process.env.DINEXT_BENCH_PATH,
		fs.existsSync(frappeApp) ? fs.realpathSync(frappeApp) : null,
		process.env.PWD,
		process.cwd(),
	].filter(Boolean);
	for (const start of starts) {
		let dir = path.resolve(start);
		for (;;) {
			if (fs.existsSync(path.join(dir, "sites", "apps.txt"))) {
				return dir;
			}
			const parent = path.dirname(dir);
			if (parent === dir) {
				break;
			}
			dir = parent;
		}
	}
	throw new Error("Bench directory not found; set DINEXT_BENCH_PATH");
}

function benchExecute(site, method, env = {}) {
	execFileSync("bench", ["--site", site, "execute", `${HELPERS}.${method}`], {
		cwd: benchRoot(),
		env: { ...process.env, ...env },
		stdio: "inherit",
	});
}

module.exports = {
	defaultCommandTimeout: 60000,
	pageLoadTimeout: 120000,
	requestTimeout: 120000,
	video: false,
	viewportHeight: 960,
	viewportWidth: 1400,
	retries: {
		runMode: 0,
		openMode: 0,
	},
	e2e: {
		setupNodeEvents(on, config) {
			const site = config.env.site || new URL(config.baseUrl).hostname;
			// Users get a fresh password per run; it is never stored in the repository.
			const password = `${crypto.randomBytes(18).toString("base64url")}-Aa1`;
			benchExecute(site, "bootstrap_users", { DINEXT_GOALS_CYPRESS_PASSWORD: password });
			on("after:run", () => benchExecute(site, "teardown_users"));			config.env.goalsPassword = password;
			return config;
		},
		baseUrl: "http://localhost:8000",
		specPattern: "cypress/integration/**/*.js",
		supportFile: "cypress/support/e2e.js",
		includeShadowDom: true,
		testIsolation: false,
	},
};
