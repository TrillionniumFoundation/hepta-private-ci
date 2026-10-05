import {defineConfig, devices} from '@playwright/test';
export default defineConfig({
 outputDir:process.env.HEPTA_ROBRIX_FIXTURES==='1'?'test-results/robrix-fixtures':'test-results/robrix-default',
 // Isolate the additional fixture capture workload without changing per-case
 // deadlines, retries, scenarios, pixels or ordinary default-run scheduling.
 workers:process.env.HEPTA_ROBRIX_FIXTURES==='1'?1:undefined,
 testDir:'./e2e',testMatch:process.env.HEPTA_ROBRIX_DIAGNOSTICS==='1'?'robrix-buffer-diagnostic.spec.mjs':process.env.HEPTA_ROBRIX_FIXTURES==='1'?['robrix-host.spec.mjs','robrix-sidebar.spec.mjs']:'robrix-host.spec.mjs',timeout:90000,fullyParallel:false,
 reporter:[['line'],['json',{outputFile:process.env.HEPTA_ROBRIX_DIAGNOSTICS==='1'?'test-results/robrix-buffer-results.json':process.env.HEPTA_ROBRIX_FIXTURES==='1'?'test-results/robrix-fixtures-results.json':'test-results/robrix-default-results.json'}]],
 use:{baseURL:'http://127.0.0.1:4175',trace:'off',screenshot:'only-on-failure'},
 projects:[{name:'chromium',use:{...devices['Desktop Chrome']}},{name:'firefox',use:{...devices['Desktop Firefox'],headless:false}},{name:'webkit',use:{...devices['Desktop Safari'],headless:false}}],
 webServer:{command:'node tools/serve-robrix.mjs',url:'http://127.0.0.1:4175',reuseExistingServer:false,timeout:30000},
});
