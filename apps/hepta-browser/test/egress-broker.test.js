import assert from "node:assert/strict";
import http from "node:http";
import { PassThrough } from "node:stream";
import test from "node:test";

import { GrantScopedEgressBroker } from "../src/egress-broker.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);

function encode(value) {
  const body = Buffer.from(JSON.stringify(value), "utf8");
  const frame = Buffer.alloc(body.length + 4);
  frame.writeUInt32BE(body.length, 0);
  body.copy(frame, 4);
  return frame;
}

function readFrame(stream) {
  return new Promise((resolve, reject) => {
    let buffer = Buffer.alloc(0);
    const onError = (error) => {
      cleanup();
      reject(error);
    };
    const onData = (chunk) => {
      buffer = Buffer.concat([buffer, Buffer.from(chunk)]);
      if (buffer.length < 4) return;
      const length = buffer.readUInt32BE(0);
      if (buffer.length < length + 4) return;
      cleanup();
      resolve(JSON.parse(buffer.subarray(4, length + 4).toString("utf8")));
    };
    const cleanup = () => {
      stream.off("data", onData);
      stream.off("error", onError);
    };
    stream.on("data", onData);
    stream.on("error", onError);
  });
}

function request({
  port,
  path = "/ok",
  method = "GET",
  isRedirect = false,
  sequence = 1,
  operationId = "operation.1",
}) {
  return {
    schema: "hepta.browser.egress-request.v1",
    sequence,
    operationId,
    profileGrantDigest: D1,
    effectGrantDigest: D2,
    authorityEpoch: 7,
    url: `http://authorized.test:${port}${path}`,
    method,
    headers: [["accept", "text/html"]],
    isRedirect,
  };
}

async function server() {
  const instance = http.createServer((req, res) => {
    if (req.url === "/redirect-escape") {
      res.writeHead(302, { location: "http://forbidden.test/escape" });
      res.end();
      return;
    }
    if (req.url === "/redirect-ok") {
      res.writeHead(302, { location: "/ok" });
      res.end();
      return;
    }
    res.writeHead(200, { "content-type": "text/html" });
    res.end("<html><body><button id=\"ok\">OK</button></body></html>");
  });
  await new Promise((resolve) => instance.listen(0, "127.0.0.1", resolve));
  return instance;
}

test("grant-scoped broker binds origin DNS IP and bodyless request", async () => {
  const instance = await server();
  const port = instance.address().port;
  const requests = new PassThrough();
  const responses = new PassThrough();
  const broker = new GrantScopedEgressBroker({
    requestStream: requests,
    responseStream: responses,
    profileGrantDigest: D1,
    allowedOrigins: [`http://authorized.test:${port}`],
    allowedNetworkAddresses: ["127.0.0.1"],
    dnsLookup: (_host, options, callback) => {
      assert.equal(options.all, true);
      callback(null, [{ address: "127.0.0.1", family: 4 }]);
    },
  });
  broker.authorizeEffect({
    operationId: "operation.1",
    profileGrantDigest: D1,
    effectGrantDigest: D2,
    authorityEpoch: 7,
    destinationOrigin: `http://authorized.test:${port}`,
    deadlineMs: Date.now() + 30_000,
  });
  const responsePromise = readFrame(responses);
  requests.write(encode(request({ port })));
  const response = await responsePromise;
  assert.equal(response.ok, true);
  assert.equal(response.statusCode, 200);
  assert.equal(response.remoteAddress, "127.0.0.1");
  assert.deepEqual(response.dnsAnswers, ["127.0.0.1"]);
  assert.match(Buffer.from(response.bodyBase64, "base64").toString("utf8"), /button/);
  assert.match(response.egressReceiptDigest, /^[0-9a-f]{64}$/);
  broker.close();
  await new Promise((resolve) => instance.close(resolve));
});

test("broker rejects private DNS answers unless the profile grant names the address", async () => {
  const requests = new PassThrough();
  const responses = new PassThrough();
  const broker = new GrantScopedEgressBroker({
    requestStream: requests,
    responseStream: responses,
    profileGrantDigest: D1,
    allowedOrigins: ["http://authorized.test:8080"],
    dnsLookup: (_host, _options, callback) => {
      callback(null, [{ address: "127.0.0.1", family: 4 }]);
    },
  });
  broker.authorizeEffect({
    operationId: "operation.1",
    profileGrantDigest: D1,
    effectGrantDigest: D2,
    authorityEpoch: 7,
    destinationOrigin: "http://authorized.test:8080",
    deadlineMs: Date.now() + 30_000,
  });
  const responsePromise = readFrame(responses);
  requests.write(encode(request({ port: 8080 })));
  const response = await responsePromise;
  assert.equal(response.ok, false);
  assert.match(response.error, /outside the grant/);
  broker.close();
});

test("redirect admission is scoped to the exact browser operation", async () => {
  const instance = await server();
  const port = instance.address().port;
  const requests = new PassThrough();
  const responses = new PassThrough();
  const broker = new GrantScopedEgressBroker({
    requestStream: requests,
    responseStream: responses,
    profileGrantDigest: D1,
    allowedOrigins: [`http://authorized.test:${port}`],
    allowedNetworkAddresses: ["127.0.0.1"],
    dnsLookup: (_host, _options, callback) => {
      callback(null, [{ address: "127.0.0.1", family: 4 }]);
    },
  });
  for (const operationId of ["operation.1", "operation.2"]) {
    broker.authorizeEffect({
      operationId,
      profileGrantDigest: D1,
      effectGrantDigest: D2,
      authorityEpoch: 7,
      destinationOrigin: `http://authorized.test:${port}`,
      deadlineMs: Date.now() + 30_000,
    });
  }

  let responsePromise = readFrame(responses);
  requests.write(encode(request({ port, path: "/redirect-ok", operationId: "operation.1" })));
  let response = await responsePromise;
  assert.equal(response.ok, true);
  assert.equal(response.statusCode, 302);

  responsePromise = readFrame(responses);
  requests.write(encode(request({
    port,
    path: "/ok",
    isRedirect: true,
    sequence: 2,
    operationId: "operation.2",
  })));
  response = await responsePromise;
  assert.equal(response.ok, false);
  assert.match(response.error, /for this operation/);

  responsePromise = readFrame(responses);
  requests.write(encode(request({
    port,
    path: "/ok",
    isRedirect: true,
    sequence: 3,
    operationId: "operation.1",
  })));
  response = await responsePromise;
  assert.equal(response.ok, true);
  assert.equal(response.statusCode, 200);

  broker.close();
  await new Promise((resolve) => instance.close(resolve));
});

test("broker rejects redirect escape before Servo follows it and rejects POST", async () => {
  const instance = await server();
  const port = instance.address().port;
  const requests = new PassThrough();
  const responses = new PassThrough();
  const broker = new GrantScopedEgressBroker({
    requestStream: requests,
    responseStream: responses,
    profileGrantDigest: D1,
    allowedOrigins: [`http://authorized.test:${port}`],
    allowedNetworkAddresses: ["127.0.0.1"],
    dnsLookup: (_host, _options, callback) => {
      callback(null, [{ address: "127.0.0.1", family: 4 }]);
    },
  });
  broker.authorizeEffect({
    operationId: "operation.1",
    profileGrantDigest: D1,
    effectGrantDigest: D2,
    authorityEpoch: 7,
    destinationOrigin: `http://authorized.test:${port}`,
    deadlineMs: Date.now() + 30_000,
  });
  let responsePromise = readFrame(responses);
  requests.write(encode(request({ port, path: "/redirect-escape" })));
  let response = await responsePromise;
  assert.equal(response.ok, false);
  assert.match(response.error, /redirect escaped/);

  responsePromise = readFrame(responses);
  requests.write(encode(request({ port, method: "POST", sequence: 2 })));
  response = await responsePromise;
  assert.equal(response.ok, false);
  assert.match(response.error, /GET\/HEAD/);
  broker.close();
  await new Promise((resolve) => instance.close(resolve));
});
