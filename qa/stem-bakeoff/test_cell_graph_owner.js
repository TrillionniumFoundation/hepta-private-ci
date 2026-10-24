// Constructed adapter tests only; no native tools, remote hosts, or task data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, 'cell_graph_owner.js'), 'utf8');
const context = {Date, Promise, Error};
vm.createContext(context);
vm.runInContext(source, context);

async function test() {
  const graph = {graph_id: 'b0-C', block: 0, arm: 'C', requests: [0, 1].map(i => ({
    request_id: `s${i}`, host: i ? 'main' : 'pocket4', request_sha256: 'a'.repeat(64), idempotency_key: `id${i}`}))};
  let active = 0, maxActive = 0, submitted = 0, publication;
  const adapter = {
    async submit(request) {
      active++; submitted++; maxActive = Math.max(active, maxActive);
      await new Promise(resolve => setTimeout(resolve, 5)); active--;
      return {job_id: `job-${request.request_id}`, start_arguments_sha256: 'b'.repeat(64), start_disposition: 'created', native_receipt_sha256: 'c'.repeat(64)};
    },
    async collect(request, start, instrument) {
      await instrument('process_read', async () => ({native_receipt_sha256: 'd'.repeat(64)}));
      return {request_id: request.request_id, host: request.host, job_id: start.job_id,
        request_sha256: request.request_sha256, idempotency_key: request.idempotency_key,
        status: 'completed', exit_code: 0, stdout_complete: true, truncated: false, stdout_base64: 'eA==', stdout_sha256: 'e'.repeat(64)};
    },
    async reduce(collection) { return {status: collection.workers.every(w => w.status === 'completed') ? 'completed' : 'failed', receipt_sha256: 'f'.repeat(64)}; },
    async publish(g, collection, owner) { publication = {collection, owner}; },
    async reconcile() { return {status: 'reconciled'}; }
  };
  const ok = await context.executeCellGraph(graph, '0'.repeat(64), adapter);
  assert.equal(submitted, 2); assert.equal(maxActive, 2);
  assert.equal(ok.concurrent_start_calls_observed, true);
  assert.equal(ok.status, 'completed'); assert.equal(ok.events.length, 4);
  assert.equal(ok.no_cross_host_clock_subtraction, true);
  assert.equal(publication.collection.workers.length, 2);
  const failed = {...adapter, async submit(request) { if (request.request_id === 's0') throw new Error('constructed dispatch failure'); return adapter.submit(request); }};
  const rejected = await context.executeCellGraph(graph, '0'.repeat(64), failed);
  assert.equal(rejected.status, 'failed');
  assert.equal(publication.collection.workers[0].status, 'failed');
  assert.equal(publication.collection.workers[1].status, 'completed');
  assert.equal(publication.collection.workers.length, 2); // failed node is not removed.
  const cached = {...adapter, async submit(request) { return {...await adapter.submit(request), start_disposition: 'reused'}; }};
  assert.equal((await context.executeCellGraph(graph, '0'.repeat(64), cached)).status, 'failed');
  const reducerFailure = {...adapter, async reduce() { throw new Error('constructed reducer failure'); }};
  assert.equal((await context.executeCellGraph(graph, '0'.repeat(64), reducerFailure)).status, 'failed');
  let recoveryPublished;
  const original = {job_id: 'original-job', original_start_arguments_sha256: 'b'.repeat(64), stdout_sha256: 'e'.repeat(64), stdout_base64: 'eA=='};
  const replay = {...adapter,
    async replayOriginalStart() { return {job_id: 'different-job', start_arguments_sha256: 'b'.repeat(64), start_disposition: 'created', native_receipt_sha256: 'c'.repeat(64)}; },
    async publishRecovery(req, record) { recoveryPublished = record; }};
  const recovery = await context.recoverCellGraphNode(graph.requests[0], original, '0'.repeat(64), replay);
  assert.equal(recovery.status, 'failed');
  assert.equal(recoveryPublished.api_events.length, 1); // no new-job collection fallback.
  let clock = 100;
  context.Date = {now: () => clock};
  const one = {...graph, graph_id: 'b0-A', arm: 'A', requests: [graph.requests[0]]};
  const immediateStart = async () => ({job_id: 'original-job', start_arguments_sha256: 'b'.repeat(64),
    start_disposition: 'created', native_receipt_sha256: 'c'.repeat(64)});
  const late = {...adapter, submit: immediateStart,
    async collect(request, submitted, instrument) {
      await instrument('process_read', async () => { clock = 60101; return {native_receipt_sha256: 'd'.repeat(64)}; });
      throw new Error('late call must already have been rejected');
    },
    async reconcile(request, job, instrument) {
      await instrument('process_status', async () => ({native_receipt_sha256: 'c'.repeat(64)}));
      return {status: 'already_completed'};
    }};
  const lateResult = await context.executeCellGraph(one, '0'.repeat(64), late);
  assert.equal(lateResult.status, 'failed');
  assert.equal(lateResult.events.at(-1).status, 'completed'); // native work/cost retained.
  assert.equal(publication.collection.workers[0].collection_deadline_exceeded, true);
  assert.equal(lateResult.cleanup_events.length, 1);
  clock = 100;
  const lateRecovery = {...late,
    async replayOriginalStart() { return {...await immediateStart(), start_disposition: 'reused'}; },
    async publishRecovery(req, record) { recoveryPublished = record; }};
  const lateReplay = await context.recoverCellGraphNode(one.requests[0], original, '0'.repeat(64), lateRecovery);
  assert.equal(lateReplay.status, 'failed'); assert.equal(lateReplay.api_events.length, 2);
  assert.equal(lateReplay.api_events[1].status, 'completed');
  clock = 100;
  const lateCleanup = {...late,
    async collect() { throw new Error('constructed collection failure'); },
    async reconcile(request, job, instrument) {
      await instrument('process_status', async () => {clock = 30101; return {native_receipt_sha256: 'c'.repeat(64)};});
    }};
  const cleanupFailure = await context.executeCellGraph(one, '0'.repeat(64), lateCleanup);
  assert.equal(cleanupFailure.status, 'failed');
  assert.equal(publication.collection.workers[0].cleanup.status, 'failed');
  assert.equal(cleanupFailure.cleanup_events[0].status, 'completed');
  process.stdout.write(JSON.stringify({tests: 8, passed: 8, scope: 'constructed owner adapter, no remote execution'}) + '\n');
}
test().catch(error => { console.error(error); process.exitCode = 1; });
