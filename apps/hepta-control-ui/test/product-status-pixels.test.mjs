import test from 'node:test';
import assert from 'node:assert/strict';
import {productStatusTextMatches} from '../tools/product-status-pixels.mjs';
const warning='This is not current write authority. Chat and commands remain unavailable.';
const state='Production owner: not attached. No lease observation is available. Read-only runtime unavailable (Transport).';
test('NotAttached requires exact visible owner, legacy transport and both authority limits',()=>{
 assert.equal(productStatusTextMatches(state+' '+warning,'notAttached'),true);
 for(const text of [state,state+' Chat and commands remain unavailable.',state+' This is not current write authority.',(state+' '+warning).replace('not attached','jot attached'),(state+' '+warning).replace('(Transport)','(NotConnected)'),(state+' '+warning).replace('No lease observation is available.','')])assert.equal(productStatusTextMatches(text,'notAttached'),false);
});
test('timeout and cancelled-state observations cannot substitute for each other',()=>{
 assert.equal(productStatusTextMatches('Production owner observation unavailable (TimedOut). Read-only runtime unavailable (Transport). '+warning,'timedOut'),true);
 assert.equal(productStatusTextMatches('No owner observation has been requested '+warning,'noObservation'),true);
 assert.equal(productStatusTextMatches(state+' '+warning,'timedOut'),false);
 assert.equal(productStatusTextMatches('Production owner observation unavailable (TimedOut). '+warning,'timedOut'),false);
 assert.equal(productStatusTextMatches('Production owner: not attached. No lease observation is available. Read-only runtime unavailable (TimedOut). '+warning,'timedOut'),false);
 assert.equal(productStatusTextMatches('TimedOut '+warning,'noObservation'),false);
 assert.throws(()=>productStatusTextMatches(state,'invented'),/Unknown/);
});
