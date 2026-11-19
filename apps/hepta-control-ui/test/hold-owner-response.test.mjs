// Data-only fake CDP sessions. Product/browser acceptance remains in the
// original six cloud cases; these tests exercise control failure and cleanup.
import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {holdOwnerResponse} from '../tools/hold-owner-response.mjs';

const ownerUrl = 'http://127.0.0.1:4175/api/hepta/owner-status';
const body = JSON.stringify({schema: 'hepta.owner-lease-observation.v1', observation: {status: 'not_attached'}});
const deadline = {code: 'HEPTA_OWNER_RESPONSE_CONTROL_TIMEOUT'};
const never = () => new Promise(() => {});
const flush = async () => { for (let index = 0; index < 20; index++) await Promise.resolve(); };
function fixture(overrides = {}) {
  const calls = [], records = [], session = new EventEmitter();
  session.send = async (method, params) => {
    calls.push({method, params});
    if (overrides[method]) return overrides[method](params);
    if (method === 'Fetch.getResponseBody') return {body, base64Encoded: false};
    return {};
  };
  session.detach = async () => { calls.push({method: 'detach'}); if (overrides.detach) return overrides.detach(); };
  const request = {url: () => ownerUrl};
  const page = {
    context: () => ({newCDPSession: async () => {
      calls.push({method: 'attach'});
      return overrides.attach ? overrides.attach() : session;
    }}),
    waitForRequest: (predicate, options) => {
      assert.equal(predicate(request), true);
      assert.equal(predicate({url: () => 'http://127.0.0.1:4175/api/hepta/runtime'}), false);
      assert.deepEqual(options, {timeout: 5000});
      return overrides.request ? overrides.request() : Promise.resolve(request);
    },
  };
  const paused = (changes = {}) => session.emit('Fetch.requestPaused', {
    requestId: 'owner-fetch-id', networkId: 'original-network-id',
    request: {url: ownerUrl, method: 'GET'}, responseStatusCode: 200,
    responseHeaders: [{name: 'content-length', value: String(Buffer.byteLength(body))}], ...changes,
  });
  return {calls, records, session, paused,
    start: () => holdOwnerResponse(page, ownerUrl, value => { assert.equal(value, request); return 3; }, 'timeout', {onRecord: value => records.push(value)}),
  };
}
function cleanupCalled(f) {
  assert.equal(f.calls.filter(x => x.method === 'Fetch.disable').length, 1);
  assert.equal(f.calls.filter(x => x.method === 'detach').length, 1);
  assert.equal(f.session.listenerCount('Fetch.requestPaused'), 0);
}
async function tick(t) { t.mock.timers.tick(5000); await flush(); }

test('only the original owner response is held; finish is idempotent', async () => {
  const f = fixture(), held = await f.start();
  assert.deepEqual(f.calls.find(x => x.method === 'Fetch.enable'), {
    method: 'Fetch.enable', params: {patterns: [{urlPattern: ownerUrl, requestStage: 'Response'}]},
  });
  f.paused(); await held.ready;
  assert.equal(held.requestId, 3);
  assert.equal(f.calls.some(x => x.method === 'Fetch.continueResponse'), false);
  const first = held.finish(); assert.equal(first, held.finish());
  const record = await first;
  assert.equal(record, f.records[0]);
  assert.equal(record.bodyBytes, 85);
  assert.equal(record.bodySha256, 'e680c9da35be4f88da3c641aadf957829f29fd430a9a9f873356f3f5dae4afc6');
  assert.equal(record.continued, true);
  assert.equal(record.error, undefined);
  assert.deepEqual(f.calls.find(x => x.method === 'Fetch.continueResponse'), {method: 'Fetch.continueResponse', params: {requestId: 'owner-fetch-id'}});
  cleanupCalled(f);
});

test('an original cancellation is recorded and still needs caller proof', async () => {
  const f = fixture({'Fetch.continueResponse': async () => { throw new Error('Invalid InterceptionId'); }});
  const held = await f.start(); f.paused(); await held.ready;
  const record = await held.finish();
  assert.equal(record.continued, false);
  assert.match(record.lateContinueError, /Invalid InterceptionId/);
  assert.equal(record.error, undefined);
  cleanupCalled(f);
});

test('an altered original body fails ready and finish while still detaching', async () => {
  const wrongBody = body.replace('not_attached', 'was_attached');
  const f = fixture({'Fetch.getResponseBody': async () => ({body: wrongBody, base64Encoded: false})});
  const held = await f.start(); const rejected = assert.rejects(held.ready); f.paused(); await rejected;
  await assert.rejects(held.finish());
  assert.equal(f.records[0].continued, false);
  cleanupCalled(f);
});

test('a missing response pause cannot leave ready or cleanup pending', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const f = fixture(), held = await f.start();
  const rejected = assert.rejects(held.ready, deadline);
  await tick(t); await rejected;
  await assert.rejects(held.finish(), deadline);
  assert.equal(f.records[0].stages.find(x => x.phase === 'owner-response.ready').state, 'deadline');
  cleanupCalled(f);
});

test('a stalled body read keeps phase evidence and cannot suppress finally', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const f = fixture({'Fetch.getResponseBody': never}), held = await f.start();
  const rejected = assert.rejects(held.ready, deadline); f.paused(); await flush();
  await tick(t); await rejected;
  await assert.rejects(held.finish(), deadline);
  assert.equal(f.records[0].stages.find(x => x.phase === 'Fetch.getResponseBody').state, 'deadline');
  cleanupCalled(f);
});

test('stalled Fetch.enable rejects setup and still disables and detaches', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const f = fixture({'Fetch.enable': never}), rejected = assert.rejects(f.start(), deadline);
  await flush(); await tick(t); await rejected;
  assert.equal(f.records[0].stages.find(x => x.phase === 'Fetch.enable').state, 'deadline');
  cleanupCalled(f);
});

test('a stalled continue is fatal, not an accepted late cancellation', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const f = fixture({'Fetch.continueResponse': never}), held = await f.start();
  f.paused(); await held.ready;
  const rejected = assert.rejects(held.finish(), deadline); await flush();
  await tick(t); await rejected;
  assert.equal(f.records[0].continued, false);
  assert.equal(f.records[0].stages.find(x => x.phase === 'Fetch.continueResponse').state, 'deadline');
  cleanupCalled(f);
});

for (const method of ['Fetch.disable', 'detach']) test(`stalled ${method} remains a failure and cleanup is bounded`, async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const f = fixture({[method]: never}), held = await f.start();
  f.paused(); await held.ready;
  const rejected = assert.rejects(held.finish(), deadline); await flush();
  await tick(t); await rejected;
  assert.match(f.records[0].error, /Owner response control deadline/);
  cleanupCalled(f);
});

test('late session acquisition is detached without enabling interception', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  let acquired;
  const f = fixture({attach: () => new Promise(resolve => { acquired = resolve; })});
  const rejected = assert.rejects(f.start(), deadline); await flush();
  await tick(t); await rejected;
  assert.equal(f.records[0].stages[0].state, 'deadline');
  acquired(f.session); await flush();
  assert.deepEqual(f.calls.map(x => x.method), ['attach', 'detach']);
});

test('the original request wait rejection remains fatal and detached', async () => {
  const original = new Error('original request timeout');
  const f = fixture({request: () => Promise.reject(original)}), held = await f.start();
  await assert.rejects(held.ready, error => error === original);
  await assert.rejects(held.finish(), error => error === original);
  cleanupCalled(f);
});
