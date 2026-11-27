// Actual Rust gateway entry with task-owned missing state. No owner fixture server.
import {defineConfig,devices} from '@playwright/test';
import {resolve} from 'node:path';
import {hashDiagnosticFile,FIXED_BINARY_SHA,FIXED_BROWSER_VERSION} from './tools/font-diagnostic-browser-identity.mjs';
const executablePath=process.env.HEPTA_PRODUCT_BROWSER;
if(executablePath&&await hashDiagnosticFile(executablePath)!==FIXED_BINARY_SHA)throw new Error('Product browser digest mismatch');
// Missing configuration cannot silently qualify the bundled browser: every
// product test also verifies the running executable, version and revision.
export default defineConfig({
 testDir:'./e2e',testMatch:['robrix-product-status.spec.mjs','robrix-font-transport.spec.mjs'],
 outputDir:'test-results/product-status',fullyParallel:false,workers:1,timeout:90000,
 reporter:[['line'],['json',{outputFile:'test-results/product-status-results.json'}]],
 use:{baseURL:'http://127.0.0.1:4175',trace:'off',screenshot:'only-on-failure'},
 projects:[{name:'chromium',metadata:{productBrowserQualification:true,expectedBrowser:FIXED_BROWSER_VERSION},use:{...devices['Desktop Chrome'],...(executablePath?{launchOptions:{executablePath:resolve(executablePath)}}:{})}}],
 webServer:{command:'python3 tools/run-product-preview.py',url:'http://127.0.0.1:4175',reuseExistingServer:false,timeout:30000,gracefulShutdown:{signal:'SIGTERM',timeout:10000}},
});
