// Product-test fault injection. Only the owner response is paused; the runtime
// request and every asset retain their original, unintercepted network path.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';

export async function holdOwnerResponse(page, ownerUrl, observeRequest, name, onProgress = () => {}) {
  // Passive diagnostic callback only; it adds no await or control outcome.
  const progress = (event, details = {}) => {
    try { onProgress(event, {name, ...details}); } catch {}
  };
  progress('session.start');
  const session = await page.context().newCDPSession(page);
  progress('session.done');
  let release, entered, rejectReady, completed;
  const gate = new Promise(resolve => { release = resolve; });
  const ready = new Promise((resolve, reject) => { entered = resolve; rejectReady = reject; });
  const done = new Promise(resolve => { completed = resolve; });
  const record = {name, mode: 'pause the original owner response only', continued: false};
  let paused = false, finishPromise;
  progress('request.wait.start');
  const request = page.waitForRequest(value => value.url() === ownerUrl, {timeout: 5000});
  void request.then(() => progress('request.wait.done'), () => {});
  // Attach a rejection handler immediately; ready remains the caller's failure.
  request.catch(error => { progress('request.wait.failed'); rejectReady(error); if (!paused) completed(); });
  session.on('Fetch.requestPaused', async event => {
    progress('response.paused', {fetchRequestId: event.requestId, networkId: event.networkId, status: event.responseStatusCode});
    try {
      assert.equal(paused, false, 'More than one held owner response');
      paused = true;
      assert.equal(event.request.url, ownerUrl);
      assert.equal(event.request.method, 'GET');
      assert.equal(event.responseStatusCode, 200);
      const length = event.responseHeaders.find(header => header.name.toLowerCase() === 'content-length');
      assert.match(length?.value ?? '', /^[0-9]+$/);
      assert.ok(Number(length.value) > 0 && Number(length.value) <= 4096);
      progress('response.body.start', {fetchRequestId: event.requestId});
      const response = await session.send('Fetch.getResponseBody', {requestId: event.requestId});
      progress('response.body.done', {fetchRequestId: event.requestId});
      const body = Buffer.from(response.body, response.base64Encoded ? 'base64' : 'utf8');
      assert.equal(body.length, Number(length.value));
      assert.deepEqual(JSON.parse(body.toString('utf8')), {
        schema: 'hepta.owner-lease-observation.v1', observation: {status: 'not_attached'},
      });
      progress('request.bind.start');
      record.requestId = observeRequest(await request);
      progress('request.bind.done', {requestId: record.requestId});
      record.networkId = event.networkId;
      record.status = event.responseStatusCode;
      record.bodyBytes = body.length;
      record.bodySha256 = createHash('sha256').update(body).digest('hex');
      entered();
      progress('ready.resolved', {requestId: record.requestId});
      progress('gate.wait.start');
      await gate;
      progress('gate.wait.done');
      try {
        // No status, header or body replacement: release the original response.
        progress('response.continue.start', {fetchRequestId: event.requestId});
        await session.send('Fetch.continueResponse', {requestId: event.requestId});
        record.continued = true;
        progress('response.continue.done', {fetchRequestId: event.requestId});
      } catch (error) {
        // The real Rust timeout/navigation may already have cancelled this id.
        // The caller must still prove the exact cancellation and rendered state.
        progress('response.continue.failed');
        record.lateContinueError = String(error).slice(0, 500);
      }
    } catch (error) {
      progress('response.handler.failed');
      record.error = String(error).slice(0, 500);
      rejectReady(error);
    } finally {
      completed();
      progress('response.handler.complete');
    }
  });
  progress('fetch.enable.start');
  await session.send('Fetch.enable', {
    patterns: [{urlPattern: ownerUrl, requestStage: 'Response'}],
  });
  progress('fetch.enable.done');
  return {
    ready,
    get requestId() { return record.requestId; },
    finish() {
      if (!finishPromise) finishPromise = (async () => {
        progress('finish.begin');
        release();
        progress('gate.released');
        progress('finish.done.wait');
        await done;
        progress('finish.done.observed');
        try {
          progress('fetch.disable.start');
          await session.send('Fetch.disable');
          progress('fetch.disable.done');
        } finally {
          progress('session.detach.start');
          await session.detach();
          progress('session.detach.done');
        }
        progress('finish.return');
        return record;
      })();
      return finishPromise;
    },
  };
}
