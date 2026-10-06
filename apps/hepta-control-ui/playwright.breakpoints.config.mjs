import {defineConfig,devices} from '@playwright/test';
export default defineConfig({
 testDir:'./e2e',testMatch:'robrix-breakpoints.spec.mjs',outputDir:'test-results/robrix-breakpoints',
 fullyParallel:false,workers:1,retries:0,timeout:120000,
 reporter:[['line'],['json',{outputFile:'test-results/robrix-breakpoints-results.json'}]],
 use:{baseURL:'http://127.0.0.1:4175',trace:'off',screenshot:'only-on-failure'},
 projects:[{name:'chromium',use:{...devices['Desktop Chrome']}}],
 webServer:{command:'node tools/serve-robrix.mjs',url:'http://127.0.0.1:4175',reuseExistingServer:false,timeout:30000},
});
