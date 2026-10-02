import {defineConfig, devices} from '@playwright/test';
export default defineConfig({
 outputDir:process.env.HEPTA_ROBRIX_FIXTURES==='1'?'test-results/robrix-fixtures':'test-results/robrix-default',
 testDir:'./e2e',testMatch:'robrix-host.spec.mjs',timeout:90000,fullyParallel:false,
 reporter:[['line'],['json',{outputFile:'test-results/robrix-browser-results.json'}]],
 use:{baseURL:'http://127.0.0.1:4175',trace:'off',screenshot:'only-on-failure'},
 projects:[{name:'chromium',use:{...devices['Desktop Chrome']}},{name:'firefox',use:{...devices['Desktop Firefox']}},{name:'webkit',use:{...devices['Desktop Safari']}}],
 webServer:{command:'node tools/serve-robrix.mjs',url:'http://127.0.0.1:4175',reuseExistingServer:false,timeout:30000},
});
