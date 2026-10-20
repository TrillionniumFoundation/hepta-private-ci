// Actual Rust gateway entry with task-owned missing state. No owner fixture server.
import {defineConfig,devices} from '@playwright/test';
export default defineConfig({
 testDir:'./e2e',testMatch:'robrix-product-status.spec.mjs',
 outputDir:'test-results/product-status',fullyParallel:false,workers:1,timeout:90000,
 reporter:[['line'],['json',{outputFile:'test-results/product-status-results.json'}]],
 use:{baseURL:'http://127.0.0.1:4175',trace:'off',screenshot:'only-on-failure'},
 projects:[{name:'chromium',use:{...devices['Desktop Chrome']}}],
 webServer:{command:'python3 tools/run-product-preview.py',url:'http://127.0.0.1:4175',reuseExistingServer:false,timeout:30000,gracefulShutdown:{signal:'SIGTERM',timeout:10000}},
});
