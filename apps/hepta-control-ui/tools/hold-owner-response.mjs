// Product-test fault injection. Only the owner response is paused; the runtime
// request and every asset retain their original, unintercepted network path.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';

// This bounds test-control calls, not the Rust owner's five-second deadline.
const CONTROL_TIMEOUT_MS = 5000;
const DEADLINE_CODE = 'HEPTA_OWNER_RESPONSE_CONTROL_TIMEOUT';

export async function holdOwnerResponse(page, ownerUrl, observeRequest, name, {onRecord = () => {}} = {}) {
  const record = {name, mode: 'pause the original owner response only', continued: false, stages: []};
  // Retain the same bounded record even if setup fails before a handle exists.
  onRecord(record);
  async function step(phase, operation) {
    const stage = {phase, state: 'pending'};
    record.stages.push(stage);
    let timer;
    try {
      const value = await Promise.race([
        Promise.resolve().then(operation),
        new Promise((_, reject) => {
          timer = setTimeout(() => {
            const error = new Error(`Owner response control deadline: ${phase}`);
            error.code = DEADLINE_CODE;
            reject(error);
          }, CONTROL_TIMEOUT_MS);
        }),
      ]);
      stage.state = 'completed';
      return value;
    } catch (error) {
      stage.state = error.code === DEADLINE_CODE ? 'deadline' : 'failed';
      stage.error = String(error).slice(0, 500);
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }
  let session, failure;
  function fail(error) {
    failure ??= error;
    record.error = String(failure).slice(0, 500);
  }
  const acquiring = Promise.resolve().then(() => page.context().newCDPSession(page));
  try {
    session = await step('CDP.attach', () => acquiring);
  } catch (error) {
    fail(error);
    // A late session was never enabled for interception, but still detach it.
    acquiring.then(late => step('CDP.detach-late', () => late.detach())).catch(() => {});
    throw error;
  }
  let release, entered, rejectReady, completed;
  const gate = new Promise(resolve => { release = resolve; });
  const readySignal = new Promise((resolve, reject) => { entered = resolve; rejectReady = reject; });
  const done = new Promise(resolve => { completed = resolve; });
  let paused = false, closed = false, finishPromise;
  const ready = step('owner-response.ready', () => readySignal);
  // Install handlers before setup/click can fail; the original promise still
  // rejects for the caller, and finish must not turn a deadline into success.
  ready.catch(error => { fail(error); if (!paused) completed(); });
  const request = page.waitForRequest(value => value.url() === ownerUrl, {timeout: 5000});
  request.catch(error => { rejectReady(error); if (!paused) completed(); });
  const onPaused = async event => {
    if (closed) return;
    try {
      assert.equal(paused, false, 'More than one held owner response');
      paused = true;
      assert.equal(event.request.url, ownerUrl);
      assert.equal(event.request.method, 'GET');
      assert.equal(event.responseStatusCode, 200);
      const length = event.responseHeaders.find(header => header.name.toLowerCase() === 'content-length');
      assert.match(length?.value ?? '', /^[0-9]+$/);
      assert.ok(Number(length.value) > 0 && Number(length.value) <= 4096);
      const response = await step('Fetch.getResponseBody', () => session.send('Fetch.getResponseBody', {requestId: event.requestId}));
      const body = Buffer.from(response.body, response.base64Encoded ? 'base64' : 'utf8');
      assert.equal(body.length, Number(length.value));
      assert.deepEqual(JSON.parse(body.toString('utf8')), {
        schema: 'hepta.owner-lease-observation.v1', observation: {status: 'not_attached'},
      });
      record.requestId = observeRequest(await request);
      record.networkId = event.networkId;
      record.status = event.responseStatusCode;
      record.bodyBytes = body.length;
      record.bodySha256 = createHash('sha256').update(body).digest('hex');
      entered();
      await gate;
      try {
        // No status, header or body replacement: release the original response.
        await step('Fetch.continueResponse', () => session.send('Fetch.continueResponse', {requestId: event.requestId}));
        record.continued = true;
      } catch (error) {
        // The real Rust timeout/navigation may already have cancelled this id.
        // The caller must still prove the exact cancellation and rendered state.
        record.lateContinueError = String(error).slice(0, 500);
        if (error.code === DEADLINE_CODE) throw error;
      }
    } catch (error) {
      fail(error);
      rejectReady(error);
    } finally {
      completed();
    }
  };
  session.on('Fetch.requestPaused', onPaused);
  function finish() {
    if (!finishPromise) finishPromise = (async () => {
      release();
      try { await step('owner-response.settle', () => done); } catch (error) { fail(error); }
      closed = true;
      session.off('Fetch.requestPaused', onPaused);
      // Always try detach even when a CDP send or the handler fails to settle.
      try { await step('Fetch.disable', () => session.send('Fetch.disable')); } catch (error) { fail(error); }
      try { await step('CDP.detach', () => session.detach()); } catch (error) { fail(error); }
      if (failure) throw failure;
      return record;
    })();
    return finishPromise;
  }
  try {
    await step('Fetch.enable', () => session.send('Fetch.enable', {
      patterns: [{urlPattern: ownerUrl, requestStage: 'Response'}],
    }));
  } catch (error) {
    fail(error);
    rejectReady(error);
    if (!paused) completed();
    await finish().catch(() => {});
    throw error;
  }
  return {ready, get requestId() { return record.requestId; }, finish};
}
