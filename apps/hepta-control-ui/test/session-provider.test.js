import assert from "node:assert/strict";
import test from "node:test";
import {
  SessionProvider,
  UI_CONTROL_ERROR_CODES,
  UiControlError,
} from "../src/index.js";
import { deferred } from "./helpers.js";

function fakeClient(overrides = {}) {
  const state = {
    connected: false,
    connectCount: 0,
    refreshCount: 0,
    revokeCount: 0,
    closeCount: 0,
  };
  return {
    state,
    async connect() {
      state.connectCount += 1;
      state.connected = true;
    },
    async refreshSession() {
      state.refreshCount += 1;
    },
    async revokeSession() {
      state.revokeCount += 1;
      state.connected = false;
    },
    async close() {
      state.closeCount += 1;
      state.connected = false;
    },
    readView() {
      return Object.freeze({
        connected: state.connected,
        expiresAt: null,
      });
    },
    ...overrides,
  };
}

test("concurrent start callers share one connection attempt", async () => {
  const gate = deferred();
  const events = [];
  const client = fakeClient({
    async connect() {
      client.state.connectCount += 1;
      await gate.promise;
      client.state.connected = true;
    },
  });
  const provider = new SessionProvider({ client, endpointManifest: {} });
  provider.subscribe(event => events.push(event.type));

  const first = provider.start();
  const second = provider.start();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(client.state.connectCount, 1);
  gate.resolve();
  await Promise.all([first, second]);
  assert.equal(client.state.connectCount, 1);
  assert.deepEqual(events, ["connected"]);
  provider.stop();
});

test("stop fences an in-flight connection and closes local authority once", async () => {
  const gate = deferred();
  const events = [];
  const client = fakeClient({
    async connect() {
      client.state.connectCount += 1;
      await gate.promise;
      client.state.connected = true;
    },
  });
  const provider = new SessionProvider({ client, endpointManifest: {} });
  provider.subscribe(event => events.push(event.type));

  const starting = provider.start();
  await new Promise(resolve => setImmediate(resolve));
  provider.stop();
  gate.resolve();

  await assert.rejects(
    starting,
    error => error instanceof UiControlError && error.code === UI_CONTROL_ERROR_CODES.ABORTED,
  );
  assert.equal(client.state.closeCount, 1);
  assert.equal(client.state.connected, false);
  assert.deepEqual(events, []);
});

test("concurrent refresh callers share one in-flight refresh", async () => {
  const gate = deferred();
  const client = fakeClient({
    async refreshSession() {
      client.state.refreshCount += 1;
      await gate.promise;
    },
  });
  const provider = new SessionProvider({ client, endpointManifest: {} });
  await provider.start();

  const first = provider.refresh();
  const second = provider.refresh();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(client.state.refreshCount, 1);
  gate.resolve();
  await Promise.all([first, second]);
  assert.equal(client.state.refreshCount, 1);
  provider.stop();
});

test("stop fences an in-flight refresh from emitting success or rescheduling", async () => {
  const gate = deferred();
  const events = [];
  const client = fakeClient({
    async refreshSession() {
      client.state.refreshCount += 1;
      await gate.promise;
    },
  });
  const provider = new SessionProvider({ client, endpointManifest: {} });
  provider.subscribe(event => events.push(event.type));
  await provider.start();
  const refreshing = provider.refresh();
  await new Promise(resolve => setImmediate(resolve));
  provider.stop();
  gate.resolve();

  await assert.rejects(
    refreshing,
    error => error instanceof UiControlError && error.code === UI_CONTROL_ERROR_CODES.ABORTED,
  );
  assert.deepEqual(events, ["connected"]);
  await assert.rejects(
    provider.refresh(),
    error => error instanceof UiControlError && error.code === UI_CONTROL_ERROR_CODES.NOT_CONNECTED,
  );
});

test("session authority loss during refresh fails closed and emits revocation", async () => {
  const events = [];
  const client = fakeClient({
    async refreshSession() {
      client.state.refreshCount += 1;
      client.state.connected = false;
      throw new UiControlError(
        UI_CONTROL_ERROR_CODES.SESSION_EXPIRED,
        "session expired",
      );
    },
  });
  const provider = new SessionProvider({ client, endpointManifest: {} });
  provider.subscribe(event => events.push(event.type));
  await provider.start();

  await assert.rejects(
    provider.refresh(),
    error =>
      error instanceof UiControlError &&
      error.code === UI_CONTROL_ERROR_CODES.SESSION_EXPIRED,
  );
  assert.equal(client.state.closeCount, 1);
  assert.deepEqual(events, ["connected", "revoked"]);
  await assert.rejects(
    provider.refresh(),
    error => error instanceof UiControlError && error.code === UI_CONTROL_ERROR_CODES.NOT_CONNECTED,
  );
});

test("revoke emits local revocation even when transport cleanup fails", async () => {
  const events = [];
  const client = fakeClient({
    async revokeSession() {
      client.state.revokeCount += 1;
      client.state.connected = false;
      throw new Error("revoke acknowledgement lost");
    },
  });
  const provider = new SessionProvider({ client, endpointManifest: {} });
  provider.subscribe(event => events.push(event.type));
  await provider.start();
  await assert.rejects(provider.revoke());
  assert.deepEqual(events, ["connected", "revoked"]);
  await assert.rejects(
    provider.refresh(),
    error => error instanceof UiControlError && error.code === UI_CONTROL_ERROR_CODES.NOT_CONNECTED,
  );
});
