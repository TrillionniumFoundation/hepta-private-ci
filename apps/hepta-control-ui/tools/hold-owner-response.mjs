// Product-test fault injection. Only the owner response is paused; the runtime
// request and every asset retain their original, unintercepted network path.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';

export async function holdOwnerResponse(page, ownerUrl, observeRequest, name) {
  const session = await page.context().newCDPSession(page);
  let release, entered, rejectReady, completed;
  const gate = new Promise(resolve => { release = resolve; });
  const ready = new Promise((resolve, reject) => { entered = resolve; rejectReady = reject; });
  const done = new Promise(resolve => { completed = resolve; });
  const record = {name, mode: 'pause the original owner response only', continued: false};
  let paused = false, finishPromise;
  const request = page.waitForRequest(value => value.url() === ownerUrl, {timeout: 5000});
  // Attach a rejection handler immediately; ready remains the caller's failure.
  request.catch(error => { rejectReady(error); if (!paused) completed(); });
  session.on('Fetch.requestPaused', async event => {
    try {
      assert.equal(paused, false, 'More than one held owner response');
      paused = true;
      assert.equal(event.request.url, ownerUrl);
      assert.equal(event.request.method, 'GET');
      assert.equal(event.responseStatusCode, 200);
      const length = event.responseHeaders.find(header => header.name.toLowerCase() === 'content-length');
      assert.match(length?.value ?? '', /^[0-9]+$/);
      assert.ok(Number(length.value) > 0 && Number(length.value) <= 4096);
      const response = await session.send('Fetch.getResponseBody', {requestId: event.requestId});
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
        await session.send('Fetch.continueResponse', {requestId: event.requestId});
        record.continued = true;
      } catch (error) {
        // The real Rust timeout/navigation may already have cancelled this id.
        // The caller must still prove the exact cancellation and rendered state.
        record.lateContinueError = String(error).slice(0, 500);
      }
    } catch (error) {
      record.error = String(error).slice(0, 500);
      rejectReady(error);
    } finally {
      completed();
    }
  });
  await session.send('Fetch.enable', {
    patterns: [{urlPattern: ownerUrl, requestStage: 'Response'}],
  });
  return {
    ready,
    get requestId() { return record.requestId; },
    finish() {
      if (!finishPromise) finishPromise = (async () => {
        release();
        await done;
        try { await session.send('Fetch.disable'); } finally { await session.detach(); }
        return record;
      })();
      return finishPromise;
    },
  };
}
