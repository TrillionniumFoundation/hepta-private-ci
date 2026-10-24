// Additional diagnostic matrix only. Primary acceptance imports neither this file nor this pin.
import product from './playwright.product.config.mjs';
import fixture from './playwright.robrix.config.mjs';
import {resolve} from 'node:path';
import {hashDiagnosticFile,FIXED_BINARY_SHA} from './tools/font-diagnostic-browser-identity.mjs';
const executablePath=process.env.HEPTA_FONT_DIAGNOSTIC_BROWSER;
const suite=process.env.HEPTA_FONT_DIAGNOSTIC_SUITE??'product';
if(!executablePath||!['product','fixture'].includes(suite))throw new Error('Select pinned diagnostic browser and suite');
if(await hashDiagnosticFile(executablePath)!==FIXED_BINARY_SHA)throw new Error('Diagnostic browser digest mismatch');
const source=suite==='product'?product:fixture;
// Preserve the original bundled comparison arm even when product acceptance
// supplies a reviewed executable through its own launch options.
const comparisonUse={...source.projects[0].use};delete comparisonUse.launchOptions;
const directory='test-results/font-diagnostic-'+suite;
export default {
 ...source,testDir:'./e2e',workers:1,fullyParallel:false,retries:0,
 testMatch:suite==='product'?['robrix-product-status.spec.mjs','robrix-font-transport.spec.mjs']:'robrix-host.spec.mjs',
 outputDir:directory,
 reporter:[['line'],['json',{outputFile:directory+'-results.json'}]],
 projects:['baseline','fixed'].flatMap(browser=>[false,true].map(instrumented=>({
  name:browser+(instrumented?'-sdk-observed':'-untouched'),
  metadata:{diagnosticOnly:true,fontDeliveryObserver:instrumented,expectedBrowser:browser==='fixed'?'157.0.8099.0':'153.0.8010.12'},
  use:{...comparisonUse,...(browser==='fixed'?{launchOptions:{executablePath:resolve(executablePath)}}:{})},
 }))),
};
