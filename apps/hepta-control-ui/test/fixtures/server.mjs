import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../dist/", import.meta.url));
const port = Number(process.env.PORT ?? 4173);
const csrfToken = "csrf-fixture-token";
const digests = {
  a: "a".repeat(64),
  b: "b".repeat(64),
  c: "c".repeat(64),
};

const state = {
  snapshotRevision: 11,
  snapshotGeneration: 7,
  requestCount: 0,
  operations: new Map(),
};

function reset() {
  state.snapshotRevision = 11;
  state.snapshotGeneration = 7;
  state.requestCount = 0;
  state.operations.clear();
}

function json(response, status, payload, headers = {}) {
  const body = `${JSON.stringify(payload)}\n`;
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
    "cache-control": "no-store",
    ...headers,
  });
  response.end(body);
}

async function bodyJson(request) {
  const chunks = [];
  let bytes = 0;
  for await (const chunk of request) {
    bytes += chunk.length;
    if (bytes > 1024 * 1024) throw new Error("body too large");
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
}

function session() {
  return {
    authenticated: true,
    protocolVersion: "hepta.ui-control.v1",
    sessionId: "session-1",
    connectionGeneration: 1,
    permissionRevision: 1,
    expiresAt: Date.now() + 60 * 60 * 1000,
    revoked: false,
    identityId: "operator-1",
    permissions: [
      "hepta://ui.control/runtime.read",
      "hepta://ui.control/runtime.request",
      "hepta://ui.control/runtime.start",
      "hepta://ui.control/runtime.stop",
    ],
  };
}

function snapshot() {
  return {
    sessionId: "session-1",
    connectionGeneration: 1,
    generation: state.snapshotGeneration,
    revision: state.snapshotRevision,
    observedAt: new Date().toISOString(),
    modules: [
      {
        id: "runtime.agentd",
        status: "ready",
        revision: state.snapshotRevision,
        semanticDigest: state.snapshotRevision === 11 ? digests.a : digests.c,
      },
      {
        id: "runtime.fleet",
        status: "degraded",
        revision: 9,
        semanticDigest: digests.b,
      },
    ],
  };
}

async function api(request, response, url) {
  const path = url.pathname.slice("/api/ui-control/v1/".length);
  if (path === "session/connect" && request.method === "POST") {
    await bodyJson(request);
    return json(response, 200, session());
  }
  if (path === "session/refresh" && request.method === "POST") {
    await bodyJson(request);
    return json(response, 200, { ...session(), permissionRevision: 2 });
  }
  if (path === "session/revoke" && request.method === "POST") {
    if (request.headers["x-hepta-csrf-token"] !== csrfToken) {
      return json(response, 403, { errorCode: "CSRF", message: "invalid CSRF token" });
    }
    await bodyJson(request);
    return json(response, 200, { revoked: true });
  }
  if (path === "session/close" && request.method === "POST") {
    await bodyJson(request);
    return json(response, 200, { closed: true });
  }
  if (path === "view" && request.method === "POST") {
    await bodyJson(request);
    return json(response, 200, snapshot());
  }
  if (path === "operations" && request.method === "POST") {
    if (request.headers["x-hepta-csrf-token"] !== csrfToken) {
      return json(response, 403, { errorCode: "CSRF", message: "invalid CSRF token" });
    }
    const input = await bodyJson(request);
    if (input.displayedRevision !== state.snapshotRevision) {
      return json(response, 412, {
        errorCode: "STALE_REVISION",
        message: "displayed revision is stale",
      });
    }
    const prior = state.operations.get(input.operationId);
    if (prior && prior.semanticDigest !== input.semanticDigest) {
      return json(response, 409, {
        errorCode: "OPERATION_ID_CONFLICT",
        message: "operation id is bound to different semantics",
      });
    }
    state.requestCount += prior ? 0 : 1;
    const observation = prior ?? {
      found: true,
      operationId: input.operationId,
      semanticDigest: input.semanticDigest,
      status: "pending",
      auditTraceId: `audit-${input.operationId}`,
    };
    state.operations.set(input.operationId, observation);
    if (input.reason.includes("AMBIGUOUS")) {
      request.socket.destroy();
      return;
    }
    return json(response, 202, {
      accepted: true,
      operationId: input.operationId,
      semanticDigest: input.semanticDigest,
      status: "accepted",
      auditTraceId: observation.auditTraceId,
    });
  }
  if (path.startsWith("operations/") && request.method === "GET") {
    const operationId = decodeURIComponent(path.slice("operations/".length));
    return json(response, 200, state.operations.get(operationId) ?? { found: false });
  }
  return json(response, 404, { errorCode: "NOT_FOUND", message: "unknown API path" });
}

async function testApi(request, response, url) {
  if (url.pathname === "/__test__/reset") {
    reset();
    return json(response, 200, { reset: true });
  }
  if (url.pathname === "/__test__/state") {
    return json(response, 200, {
      snapshotRevision: state.snapshotRevision,
      requestCount: state.requestCount,
      operations: [...state.operations.values()],
    });
  }
  if (url.pathname === "/__test__/bump") {
    state.snapshotRevision += 1;
    return json(response, 200, { snapshotRevision: state.snapshotRevision });
  }
  if (url.pathname === "/__test__/complete") {
    const operationId = url.searchParams.get("operationId");
    const operation = operationId ? state.operations.get(operationId) : null;
    if (!operation) return json(response, 404, { message: "operation not found" });
    operation.status = "succeeded";
    operation.outcomeDigest = digests.c;
    return json(response, 200, operation);
  }
  return json(response, 404, { message: "unknown test endpoint" });
}

const types = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
};

async function staticFile(request, response, url) {
  let pathname = decodeURIComponent(url.pathname);
  if (pathname === "/") pathname = "/index.html";
  const candidate = normalize(join(root, pathname));
  if (!candidate.startsWith(root)) return json(response, 403, { message: "forbidden" });
  try {
    const info = await stat(candidate);
    if (!info.isFile()) throw new Error("not a file");
    let content = await readFile(candidate);
    if (pathname === "/index.html") {
      content = Buffer.from(
        content.toString("utf8").replace(
          '<meta name="csrf-token" content="">',
          `<meta name="csrf-token" content="${csrfToken}">`,
        ),
      );
    }
    response.writeHead(200, {
      "content-type": types[extname(candidate)] ?? "application/octet-stream",
      "content-length": content.byteLength,
      "cache-control": "no-store",
      "content-security-policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
      "cross-origin-opener-policy": "same-origin",
      "cross-origin-resource-policy": "same-origin",
      "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=()",
      "referrer-policy": "no-referrer",
      "x-content-type-options": "nosniff",
      "x-frame-options": "DENY",
    });
    response.end(content);
  } catch {
    json(response, 404, { message: "not found" });
  }
}

const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url, `http://${request.headers.host}`);
    if (url.pathname.startsWith("/api/ui-control/v1/")) {
      await api(request, response, url);
    } else if (url.pathname.startsWith("/__test__/")) {
      await testApi(request, response, url);
    } else {
      await staticFile(request, response, url);
    }
  } catch (error) {
    json(response, 500, { message: error.message });
  }
});

server.listen(port, "127.0.0.1", () => {
  console.log(`ui.control fixture server listening on http://127.0.0.1:${port}`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
