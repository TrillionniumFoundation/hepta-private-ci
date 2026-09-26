#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one exact replacement, found {count}")
    write(path, text.replace(old, new, 1))


def regex_once(path: str, pattern: str, replacement: str) -> None:
    text = read(path)
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{path}: expected one regex replacement, found {count}")
    write(path, updated)


def git_blob(path: str) -> str:
    return subprocess.check_output(
        ["git", "hash-object", path], cwd=ROOT, text=True
    ).strip()


# ---------------------------------------------------------------------------
# Effect-scoped egress leases.
# ---------------------------------------------------------------------------
EGRESS = "apps/hepta-browser/src/egress-broker.js"
replace_once(
    EGRESS,
    'const DIGEST = /^[0-9a-f]{64}$/;\n',
    'const DIGEST = /^[0-9a-f]{64}$/;\nconst STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;\n',
)
replace_once(
    EGRESS,
    'function privateAddress(address, family) {\n',
    '''function stableId(value, name) {
  if (typeof value !== "string" || !STABLE_ID.test(value)) {
    throw new TypeError(`${name} must be a bounded stable identifier`);
  }
  return value;
}

function positiveInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

function privateAddress(address, family) {
''',
)
replace_once(
    EGRESS,
    '''  #server = null;
  #connections = new Set();
  #observations = [];
''',
    '''  #server = null;
  #connections = new Set();
  #observations = [];
  #activeEffect = null;
  #activeEffectTimer = null;
''',
)
replace_once(
    EGRESS,
    '''  get observations() {
    return this.#observations.map((value) => Object.freeze({ ...value }));
  }

  async start() {
''',
    '''  get observations() {
    return this.#observations.map((value) => Object.freeze({ ...value }));
  }

  activateEffect({ operationId, effectGrantDigest, origin, deadlineMs }) {
    const normalizedOperationId = stableId(operationId, "egress operationId");
    if (
      typeof effectGrantDigest !== "string" ||
      !DIGEST.test(effectGrantDigest) ||
      /^0+$/.test(effectGrantDigest)
    ) {
      throw new TypeError(
        "egress effectGrantDigest must be a non-zero lowercase SHA-256 digest",
      );
    }
    const normalizedOrigin = canonicalOrigin(origin);
    const normalizedDeadlineMs = positiveInteger(deadlineMs, "egress deadlineMs");
    if (normalizedDeadlineMs <= Date.now()) {
      throw new TypeError("egress effect lease has expired");
    }
    const binding = this.#bindings.get(normalizedOrigin);
    if (!binding || !this.#allowedOrigins.has(normalizedOrigin)) {
      throw new TypeError("egress effect origin is outside the profile grant");
    }
    const next = Object.freeze({
      operationId: normalizedOperationId,
      effectGrantDigest,
      origin: normalizedOrigin,
      deadlineMs: normalizedDeadlineMs,
      networkBindingDigest: createHash("sha256")
        .update(JSON.stringify({
          profileGrantDigest: this.#grantDigest,
          effectGrantDigest,
          operationId: normalizedOperationId,
          origin: normalizedOrigin,
          deadlineMs: normalizedDeadlineMs,
          frozenDnsBindingDigest: binding.bindingDigest,
        }))
        .digest("hex"),
    });
    if (this.#activeEffect !== null) {
      if (JSON.stringify(this.#activeEffect) === JSON.stringify(next)) {
        return next;
      }
      throw new Error("another Browser effect already owns the egress lease");
    }
    this.#activeEffect = next;
    this.#activeEffectTimer = setTimeout(() => {
      this.#clearActiveEffect(normalizedOperationId);
    }, Math.min(normalizedDeadlineMs - Date.now(), 2_147_000_000));
    this.#activeEffectTimer.unref?.();
    return next;
  }

  deactivateEffect(operationId) {
    const normalizedOperationId = stableId(operationId, "egress operationId");
    return this.#clearActiveEffect(normalizedOperationId);
  }

  async start() {
''',
)
replace_once(
    EGRESS,
    '''  async close() {
    const server = this.#server;
    this.#server = null;
''',
    '''  async close() {
    this.#clearActiveEffect();
    const server = this.#server;
    this.#server = null;
''',
)
replace_once(
    EGRESS,
    '''  #assertOrigin(origin) {
    const canonical = canonicalOrigin(origin);
    const binding = this.#bindings.get(canonical);
    if (!this.#allowedOrigins.has(canonical) || !binding) {
      throw new Error("egress origin is outside the profile grant");
    }
    return binding;
  }
''',
    '''  #clearActiveEffect(operationId = null) {
    if (
      operationId !== null &&
      this.#activeEffect !== null &&
      this.#activeEffect.operationId !== operationId
    ) {
      return false;
    }
    if (this.#activeEffectTimer !== null) {
      clearTimeout(this.#activeEffectTimer);
    }
    const changed = this.#activeEffect !== null;
    this.#activeEffectTimer = null;
    this.#activeEffect = null;
    return changed;
  }

  #assertOrigin(origin) {
    const canonical = canonicalOrigin(origin);
    const effect = this.#activeEffect;
    if (effect === null || effect.deadlineMs <= Date.now()) {
      this.#clearActiveEffect();
      throw new Error("egress request has no live Browser effect lease");
    }
    if (canonical !== effect.origin) {
      throw new Error("egress origin is outside the active Browser effect");
    }
    const binding = this.#bindings.get(canonical);
    if (!this.#allowedOrigins.has(canonical) || !binding) {
      throw new Error("egress origin is outside the profile grant");
    }
    return { binding, effect };
  }
''',
)
replace_once(
    EGRESS,
    '    const binding = this.#assertOrigin(target.origin);\n',
    '    const { binding, effect } = this.#assertOrigin(target.origin);\n',
)
replace_once(
    EGRESS,
    '    this.#record(binding, target.hostname, port, address, "http");\n',
    '    this.#record(binding, effect, target.hostname, port, address, "http");\n',
)
replace_once(
    EGRESS,
    '    const binding = this.#assertOrigin(target.origin);\n',
    '    const { binding, effect } = this.#assertOrigin(target.origin);\n',
)
replace_once(
    EGRESS,
    '      this.#record(binding, target.hostname, port, address, "connect");\n',
    '      this.#record(binding, effect, target.hostname, port, address, "connect");\n',
)
replace_once(
    EGRESS,
    '''  #record(binding, hostname, port, address, kind) {
    this.#observations.push(Object.freeze({
      grantDigest: this.#grantDigest,
      networkBindingDigest: binding.bindingDigest,
      origin: binding.origin,
      hostname,
      port,
      address,
      kind,
    }));
''',
    '''  #record(binding, effect, hostname, port, address, kind) {
    this.#observations.push(Object.freeze({
      profileGrantDigest: this.#grantDigest,
      grantDigest: effect.effectGrantDigest,
      operationId: effect.operationId,
      deadlineMs: effect.deadlineMs,
      networkBindingDigest: effect.networkBindingDigest,
      frozenDnsBindingDigest: binding.bindingDigest,
      origin: binding.origin,
      hostname,
      port,
      address,
      kind,
    }));
''',
)

# ---------------------------------------------------------------------------
# Structured worker admission receipts and bounded operation retention.
# ---------------------------------------------------------------------------
WORKER = "apps/hepta-browser/servo-worker/src/main.rs"
replace_once(
    WORKER,
    'use std::time::{Duration, Instant};\n',
    'use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};\n',
)
replace_once(
    WORKER,
    'const MAX_SEMANTIC_OBSERVATION_BYTES: usize = 262_144;\n',
    'const MAX_SEMANTIC_OBSERVATION_BYTES: usize = 262_144;\nconst MAX_STORED_OPERATIONS: usize = 4096;\n',
)
replace_once(
    WORKER,
    '''struct StoredOperation {
    payload_digest: String,
    terminal: Option<(String, String)>,
}
''',
    '''struct StoredOperation {
    payload_digest: String,
    admission: Value,
    terminal: Option<(String, String)>,
}
''',
)
replace_once(
    WORKER,
    '''    fn current_url(&self) -> Result<Url, String> {
        self.webview
            .url()
            .ok_or_else(|| "WebView has no current URL".to_string())
    }

    fn observe(&mut self, observation_budget: usize) -> Result<Value, String> {
''',
    '''    fn current_url(&self) -> Result<Url, String> {
        self.webview
            .url()
            .ok_or_else(|| "WebView has no current URL".to_string())
    }

    fn worker_admission(&self, frame: &Frame) -> Result<Value, String> {
        let operation_id = string_field(&frame.payload, "operationId")?;
        let semantic_digest = string_field(&frame.payload, "semanticDigest")?;
        if !is_digest(semantic_digest) {
            return Err("dispatch.semanticDigest must be a non-zero SHA-256 digest".to_string());
        }
        let admitted_at = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| "worker clock is before Unix epoch".to_string())?
            .as_millis();
        if admitted_at == 0 || admitted_at > MAX_SAFE_INTEGER as u128 {
            return Err("worker admission time is outside the safe range".to_string());
        }
        let page_revision = sha256_hex(
            format!(
                "{}\\0{}\\0{}\\0{}",
                self.page_generation,
                self.last_document_digest.as_deref().unwrap_or("<none>"),
                self.navigation_epoch.load(Ordering::Acquire),
                self.last_action_surface_digest.as_deref().unwrap_or("<none>"),
            )
            .as_bytes(),
        );
        Ok(json!({
            "kind": "BrowserEffectAdmissionV1",
            "operationId": operation_id,
            "semanticDigest": semantic_digest,
            "workerGeneration": frame.generation,
            "pageRevision": page_revision,
            "admittedAt": admitted_at as u64,
            "durableOrRecoverable": true,
        }))
    }

    fn observe(&mut self, observation_budget: usize) -> Result<Value, String> {
''',
)
regex_once(
    WORKER,
    r'''    fn prepare_dispatch\(&mut self, frame: &Frame\) -> Result<Option<Value>, String> \{.*?\n    \}\n\n    fn execute_prepared_dispatch''',
    '''    fn prepare_dispatch(&mut self, frame: &Frame) -> Result<(Option<Value>, Value), String> {
        let operation_id = string_field(&frame.payload, "operationId")?;
        if let Some(prior) = self.operations.get(operation_id) {
            if prior.payload_digest != frame.payload_digest {
                return Err("operation identity was reused with changed worker payload".to_string());
            }
            return Ok((Some(stored_receipt(prior)), prior.admission.clone()));
        }
        if self.operations.len() >= MAX_STORED_OPERATIONS {
            return Err("worker operation retention capacity is exhausted".to_string());
        }
        self.pump();
        let action = frame
            .payload
            .get("typedAction")
            .and_then(Value::as_object)
            .ok_or_else(|| "typedAction must be an object".to_string())?;
        let kind = action
            .get("kind")
            .and_then(Value::as_str)
            .ok_or_else(|| "typedAction.kind must be a string".to_string())?;
        if matches!(kind, "credential" | "upload" | "download") {
            return Err("typedAction capability is not connected".to_string());
        }
        validate_dispatch_snapshot_state(
            &frame.payload,
            kind,
            self.page_generation,
            self.last_document_digest.as_deref(),
            self.observed_navigation_epoch,
            self.navigation_epoch.load(Ordering::Acquire),
        )?;
        if frame
            .payload
            .get("pageGeneration")
            .and_then(Value::as_u64)
            .unwrap_or(0)
            != 0
        {
            let observation = self.verify_action_surface()?;
            validate_action_target(action, &observation)?;
        }

        let destination_origin = string_field(&frame.payload, "destinationOrigin")?;
        let destination_url = Url::parse(destination_origin)
            .map_err(|error| format!("dispatch destinationOrigin invalid: {error}"))?;
        let normalized_destination = origin(&destination_url)
            .ok_or_else(|| "dispatch destinationOrigin must use HTTP(S)".to_string())?;
        if normalized_destination != destination_origin
            || !self.allowed_origins.contains(&normalized_destination)
        {
            return Err("dispatch destinationOrigin is outside the admitted profile".to_string());
        }
        if kind == "navigate" {
            let target = action
                .get("url")
                .and_then(Value::as_str)
                .ok_or_else(|| "navigate.url must be a string".to_string())?;
            let target_url =
                Url::parse(target).map_err(|error| format!("navigate URL invalid: {error}"))?;
            if origin(&target_url).as_deref() != Some(normalized_destination.as_str()) {
                return Err(
                    "navigate action destination does not match dispatch destinationOrigin"
                        .to_string(),
                );
            }
        }
        *self
            .effect_navigation_origin
            .lock()
            .map_err(|_| "effect navigation origin lock is poisoned".to_string())? =
            Some(normalized_destination);

        let admission = self.worker_admission(frame)?;
        self.operations.insert(
            operation_id.to_string(),
            StoredOperation {
                payload_digest: frame.payload_digest.clone(),
                admission: admission.clone(),
                terminal: None,
            },
        );
        Ok((None, admission))
    }

    fn execute_prepared_dispatch''',
)
replace_once(
    WORKER,
    '''                        match active.prepare_dispatch(&frame) {
                            Ok(replay) => {
                                write_worker_frame(
                                    &mut output,
                                    &frame,
                                    response_sequence,
                                    "dispatch_boundary",
                                    json!({
                                        "localDispatchCrossed": true,
                                        "requestKind": frame.kind,
                                        "requestPayloadDigest": frame.payload_digest,
                                        "requestSequence": frame.sequence,
                                    }),
                                )?;
''',
    '''                        match active.prepare_dispatch(&frame) {
                            Ok((replay, admission)) => {
                                write_worker_frame(
                                    &mut output,
                                    &frame,
                                    response_sequence,
                                    "dispatch_boundary",
                                    json!({
                                        "localDispatchCrossed": true,
                                        "requestKind": frame.kind,
                                        "requestPayloadDigest": frame.payload_digest,
                                        "requestSequence": frame.sequence,
                                        "admission": admission,
                                    }),
                                )?;
''',
)

# ---------------------------------------------------------------------------
# Driver validates admission, owns the exact egress lease, drains bounded
# stderr, and waits for actual process exit on every containment path.
# ---------------------------------------------------------------------------
DRIVER = "apps/hepta-browser/src/worker-driver.js"
replace_once(
    DRIVER,
    'const MAX_POOL_PROFILES = 64;\n',
    '''const MAX_POOL_PROFILES = 64;
const MAX_STDERR_BYTES = 1 * 1024 * 1024;
const MAX_STDERR_TAIL_BYTES = 4096;
const CONTAINMENT_TIMEOUT_MS = 5_000;
''',
)
replace_once(
    DRIVER,
    '''function requestId(kind, semanticId) {
  const digest = createHash("sha256")
    .update(`${kind}\\u0000${semanticId}`)
    .digest("hex");
  return `browser.${kind}.${digest.slice(0, 32)}`;
}
''',
    '''function requestId(kind, semanticId) {
  const digest = createHash("sha256")
    .update(`${kind}\\u0000${semanticId}`)
    .digest("hex");
  return `browser.${kind}.${digest.slice(0, 32)}`;
}

function normalizeWorkerAdmission(value, requestPayload, generation) {
  const admission = requireRecord(value, "worker admission receipt");
  const expectedKeys = [
    "admittedAt",
    "durableOrRecoverable",
    "kind",
    "operationId",
    "pageRevision",
    "semanticDigest",
    "workerGeneration",
  ].sort();
  const actualKeys = Object.keys(admission).sort();
  if (
    actualKeys.length !== expectedKeys.length ||
    actualKeys.some((key, index) => key !== expectedKeys[index])
  ) {
    throw new TypeError("worker admission receipt contains missing or unknown fields");
  }
  if (admission.kind !== "BrowserEffectAdmissionV1") {
    throw new TypeError("worker admission receipt kind is unsupported");
  }
  if (stableId(admission.operationId, "worker admission operationId") !== requestPayload.operationId) {
    throw new TypeError("worker admission operationId drifted from dispatch");
  }
  const semanticDigest = expectedDigest(
    admission.semanticDigest,
    "worker admission semanticDigest",
  );
  if (
    requestPayload.semanticDigest !== undefined &&
    semanticDigest !== expectedDigest(requestPayload.semanticDigest, "dispatch semanticDigest")
  ) {
    throw new TypeError("worker admission semanticDigest drifted from dispatch");
  }
  if (positiveInteger(admission.workerGeneration, "worker admission workerGeneration") !== generation) {
    throw new TypeError("worker admission generation drifted from the private channel");
  }
  expectedDigest(admission.pageRevision, "worker admission pageRevision");
  positiveInteger(admission.admittedAt, "worker admission admittedAt");
  if (admission.durableOrRecoverable !== true) {
    throw new TypeError("worker admission is not durable or recoverable");
  }
  return Object.freeze({ ...admission });
}

function waitForChildExit(child, timeoutMs = CONTAINMENT_TIMEOUT_MS) {
  if (!child || child.exitCode !== null && child.exitCode !== undefined) {
    return Promise.resolve();
  }
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (error = null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      child.off?.("exit", onExit);
      child.off?.("error", onError);
      if (error) reject(error);
      else resolve();
    };
    const onExit = () => finish();
    const onError = (error) => finish(error);
    const timer = setTimeout(() => {
      const error = new Error("browser worker containment did not observe process exit");
      error.name = "BrowserContainmentError";
      finish(error);
    }, timeoutMs);
    timer.unref?.();
    child.once?.("exit", onExit);
    child.once?.("error", onError);
  });
}

async function terminateChild(child, signal = "SIGKILL") {
  if (!child) return;
  if (typeof child.heptaContain === "function") {
    await child.heptaContain(signal);
  } else {
    child.kill?.(signal);
  }
  await waitForChildExit(child);
}
''',
)
replace_once(
    DRIVER,
    '''  #abandoned = new Set();
  #closed = false;
''',
    '''  #abandoned = new Set();
  #closed = false;
  #stderrBytes = 0;
  #stderrTail = Buffer.alloc(0);
''',
)
replace_once(
    DRIVER,
    '''    child.stderr?.resume?.();
    child.on("error", (error) => this.#failAll(error));
''',
    '''    child.stderr?.on?.("data", (chunk) => {
      const bytes = Buffer.from(chunk);
      this.#stderrBytes += bytes.length;
      this.#stderrTail = Buffer.concat([this.#stderrTail, bytes]).subarray(
        -MAX_STDERR_TAIL_BYTES,
      );
      if (this.#stderrBytes > MAX_STDERR_BYTES) {
        const error = new Error("browser worker stderr exceeded the bounded diagnostic budget");
        error.name = "BrowserWorkerDiagnosticOverflowError";
        this.#failAll(error);
        this.#child.kill?.("SIGKILL");
      }
    });
    child.stderr?.resume?.();
    child.on("error", (error) => this.#failAll(error));
''',
)
replace_once(
    DRIVER,
    '''        requestSequence: sequence,
        onDispatchBoundary,
        dispatchBoundaryObserved: false,
''',
    '''        requestSequence: sequence,
        requestPayload: payload,
        onDispatchBoundary,
        dispatchBoundaryObserved: false,
''',
)
replace_once(
    DRIVER,
    '''        const expected = [
          "localDispatchCrossed",
          "requestKind",
          "requestPayloadDigest",
          "requestSequence",
        ].sort();
''',
    '''        const expected = [
          "admission",
          "localDispatchCrossed",
          "requestKind",
          "requestPayloadDigest",
          "requestSequence",
        ].sort();
''',
)
replace_once(
    DRIVER,
    '''        pending.dispatchBoundaryObserved = true;
        try {
          pending.onDispatchBoundary?.();
''',
    '''        const admission = normalizeWorkerAdmission(
          payload.admission,
          pending.requestPayload,
          this.#generation,
        );
        pending.dispatchBoundaryObserved = true;
        try {
          pending.onDispatchBoundary?.(admission);
''',
)
regex_once(
    DRIVER,
    r'''  async dispatch\(input, \{ signal \} = \{\}\) \{.*?\n  \}\n  async reconcile\(input, \{ signal \} = \{\}\) \{\n    this.#requireSession\(input\);\n    return this.#client.request\("reconcile", input.operationId, input, \{ signal \}\);\n  \}''',
    '''  async dispatch(input, { signal } = {}) {
    this.#requireSession(input);
    const broker = this.#egressBroker;
    let egressLease = null;
    if (
      broker &&
      input.destinationOrigin !== undefined &&
      input.effectGrantDigest !== undefined &&
      input.deadlineMs !== undefined
    ) {
      egressLease = broker.activateEffect({
        operationId: input.operationId,
        effectGrantDigest: input.effectGrantDigest,
        origin: input.destinationOrigin,
        deadlineMs: input.deadlineMs,
      });
    }
    let crossed = false;
    let admission = null;
    let resolveBoundary;
    const boundary = new Promise((resolve) => {
      resolveBoundary = resolve;
    });

    const response = this.#client.request(
      "dispatch",
      input.operationId,
      input,
      {
        signal,
        onDispatchBoundary: (observedAdmission) => {
          if (crossed) return;
          admission = observedAdmission;
          crossed = true;
          resolveBoundary(observedAdmission);
        },
      },
    );
    let earlyError = null;
    const settled = response.then(
      () => "resolved",
      (error) => {
        earlyError = error;
        return "rejected";
      },
    );
    const first = await Promise.race([
      boundary.then(() => "boundary"),
      settled,
    ]);
    if (first === "rejected" && !crossed) {
      if (egressLease) broker.deactivateEffect(input.operationId);
      if (earlyError?.code !== "BROWSER_WORKER_PRE_DISPATCH_REJECTED") {
        await this.#containBeforeDispatchBoundary();
      }
      throw earlyError;
    }
    if (first === "resolved" && !crossed) {
      if (egressLease) broker.deactivateEffect(input.operationId);
      await this.#containBeforeDispatchBoundary();
      throw new TypeError(
        "browser worker settled dispatch before admission boundary",
      );
    }
    const settlement = response.then(
      async (observed) => {
        if (egressLease && observed?.terminalObserved === true) {
          broker.deactivateEffect(input.operationId);
        }
        return observed;
      },
      (error) => Promise.reject(error),
    );
    return {
      terminalObserved: false,
      admission,
      settlement,
    };
  }

  async reconcile(input, { signal } = {}) {
    this.#requireSession(input);
    const observed = await this.#client.request(
      "reconcile",
      input.operationId,
      input,
      { signal },
    );
    if (observed?.terminalObserved === true) {
      this.#egressBroker?.deactivateEffect(input.operationId);
    }
    return observed;
  }''',
)
replace_once(
    DRIVER,
    '''      this.#child?.kill?.("SIGKILL");
      await this.#cleanupProfile();
''',
    '''      await terminateChild(this.#child, "SIGKILL");
      await this.#cleanupProfile();
''',
)
replace_once(
    DRIVER,
    '''    this.#client?.close();
    this.#child?.kill?.("SIGKILL");
    this.#client = null;
    this.#child = null;
    await broker?.close();
''',
    '''    const client = this.#client;
    const child = this.#child;
    client?.close();
    await terminateChild(child, "SIGKILL");
    this.#client = null;
    this.#child = null;
    await broker?.close();
''',
)
replace_once(
    DRIVER,
    '''    } finally {
      this.#client?.close();
      this.#child?.kill?.("SIGTERM");
      this.#client = null;
      this.#child = null;
      await this.#cleanupProfile();
    }
''',
    '''    } finally {
      const client = this.#client;
      const child = this.#child;
      client?.close();
      await terminateChild(child, "SIGTERM");
      this.#client = null;
      this.#child = null;
      await this.#cleanupProfile();
    }
''',
)
replace_once(
    DRIVER,
    '''    this.#client?.close();
    this.#child?.kill?.("SIGKILL");
    this.#client = null;
    this.#child = null;
    try {
      await broker?.close();
''',
    '''    const client = this.#client;
    const child = this.#child;
    client?.close();
    try {
      await terminateChild(child, "SIGKILL");
    } finally {
      this.#client = null;
      this.#child = null;
    }
    try {
      await broker?.close();
''',
)
replace_once(
    DRIVER,
    '''    client?.close();
    child?.kill?.("SIGKILL");
    try {
      await broker?.close();
''',
    '''    client?.close();
    await terminateChild(child, "SIGKILL");
    try {
      await broker?.close();
''',
)

# ---------------------------------------------------------------------------
# Runtime and Agentd propagate and validate the receipt before releasing the
# live final-use fence.
# ---------------------------------------------------------------------------
RUNTIME = "apps/hepta-browser/src/runtime-host.js"
replace_once(
    RUNTIME,
    '''function boundedSemanticObservation(value, observationBudget) {
''',
    '''function validateWorkerAdmission(value, expected) {
  const admission = requireRecord(value, "worker admission receipt");
  const expectedKeys = [
    "admittedAt",
    "durableOrRecoverable",
    "kind",
    "operationId",
    "pageRevision",
    "semanticDigest",
    "workerGeneration",
  ].sort();
  const actualKeys = Object.keys(admission).sort();
  if (
    actualKeys.length !== expectedKeys.length ||
    actualKeys.some((key, index) => key !== expectedKeys[index])
  ) {
    throw new TypeError("worker admission receipt contains missing or unknown fields");
  }
  if (admission.kind !== "BrowserEffectAdmissionV1") {
    throw new TypeError("worker admission receipt kind is unsupported");
  }
  if (stableId(admission.operationId, "worker admission operationId") !== expected.operationId) {
    throw new TypeError("worker admission operationId drifted from the Browser owner");
  }
  if (digest(admission.semanticDigest, "worker admission semanticDigest") !== expected.semanticDigest) {
    throw new TypeError("worker admission semanticDigest drifted from the Browser owner");
  }
  if (positiveInteger(admission.workerGeneration, "worker admission workerGeneration") !== expected.workerGeneration) {
    throw new TypeError("worker admission generation drifted from the Browser owner");
  }
  digest(admission.pageRevision, "worker admission pageRevision");
  positiveInteger(admission.admittedAt, "worker admission admittedAt");
  if (admission.durableOrRecoverable !== true) {
    throw new TypeError("worker admission is not durable or recoverable");
  }
  return Object.freeze({ ...admission });
}

function boundedSemanticObservation(value, observationBudget) {
''',
)
replace_once(
    RUNTIME,
    '''                const dispatchObservation = await this.#callDriver(
                  "dispatch",
                  semantics,
                  requestSemantics.deadlineMs,
                );
                state.documentDigest = null;
                return dispatchObservation;
''',
    '''                const dispatchObservation = requireRecord(
                  await this.#callDriver(
                    "dispatch",
                    Object.freeze({ ...semantics, semanticDigest }),
                    requestSemantics.deadlineMs,
                  ),
                  "driver dispatch observation",
                );
                const admission = validateWorkerAdmission(
                  dispatchObservation.admission,
                  {
                    operationId,
                    semanticDigest,
                    workerGeneration: state.generation,
                  },
                );
                state.documentDigest = null;
                return Object.freeze({ ...dispatchObservation, admission });
''',
)

SERVICE = "apps/hepta-browser/src/agentd-service.js"
replace_once(
    SERVICE,
    '''    await this.#channel.send("dispatch_boundary", requestId, {
      requestDigest,
      witnessDigest: witness.witnessDigest,
      localDispatchCrossed: true,
    });
''',
    '''    const admission = requireRecord(
      result?.admission,
      "Browser worker admission receipt",
    );
    await this.#channel.send("dispatch_boundary", requestId, {
      requestDigest,
      witnessDigest: witness.witnessDigest,
      localDispatchCrossed: true,
      admission,
    });
''',
)

# ---------------------------------------------------------------------------
# Rust Agentd enforces the exact cross-owner admission schema.
# ---------------------------------------------------------------------------
RUST = "codex-rs/hepta-agentd/src/browser_servo.rs"
regex_once(
    RUST,
    r'''                let boundary_payload =\n                    require_plain_object\(&boundary.payload, "Browser final-use boundary"\)\?;\n                require_exact_object_keys\(\n                    boundary_payload,\n                    &\["localDispatchCrossed", "requestDigest", "witnessDigest"\],\n                    "Browser final-use boundary",\n                \)\?;\n                if boundary_payload.*?\n                match boundary.kind.as_str\(\) \{.*?\n                \}\n''',
    '''                let boundary_payload =
                    require_plain_object(&boundary.payload, "Browser final-use boundary")?;
                if boundary_payload
                    .get("requestDigest")
                    .and_then(Value::as_str)
                    != Some(request_digest_text)
                    || boundary_payload
                        .get("witnessDigest")
                        .and_then(Value::as_str)
                        != Some(witness_text.as_str())
                {
                    return Err(BrowserServoError::Indeterminate(
                        "Browser final-use boundary drifted from final-use authority".into(),
                    ));
                }
                match boundary.kind.as_str() {
                    "dispatch_boundary" => {
                        require_exact_object_keys(
                            boundary_payload,
                            &[
                                "admission",
                                "localDispatchCrossed",
                                "requestDigest",
                                "witnessDigest",
                            ],
                            "Browser dispatch boundary",
                        )?;
                        if boundary_payload.get("localDispatchCrossed")
                            != Some(&Value::Bool(true))
                        {
                            return Err(BrowserServoError::Indeterminate(
                                "Browser dispatch boundary did not cross worker admission".into(),
                            ));
                        }
                        validate_browser_effect_admission(
                            boundary_payload.get("admission").ok_or_else(|| {
                                BrowserServoError::Protocol(
                                    "Browser dispatch boundary lacks admission receipt".into(),
                                )
                            })?,
                        )?;
                        Ok(())
                    }
                    "dispatch_rejected" => {
                        require_exact_object_keys(
                            boundary_payload,
                            &["localDispatchCrossed", "requestDigest", "witnessDigest"],
                            "Browser dispatch rejection",
                        )?;
                        if boundary_payload.get("localDispatchCrossed")
                            != Some(&Value::Bool(false))
                        {
                            return Err(BrowserServoError::Indeterminate(
                                "Browser dispatch rejection claimed a crossed effect".into(),
                            ));
                        }
                        Ok(())
                    }
                    _ => Err(BrowserServoError::Indeterminate(
                        "Browser did not issue a valid dispatch or rejection boundary".into(),
                    )),
                }
''',
)
replace_once(
    RUST,
    '''fn response_result(frame: DecodedFrame, request_id: &str) -> Result<Value, BrowserServoError> {
''',
    '''fn validate_browser_effect_admission(value: &Value) -> Result<(), BrowserServoError> {
    let admission = require_plain_object(value, "Browser effect admission")?;
    require_exact_object_keys(
        admission,
        &[
            "admittedAt",
            "durableOrRecoverable",
            "kind",
            "operationId",
            "pageRevision",
            "semanticDigest",
            "workerGeneration",
        ],
        "Browser effect admission",
    )?;
    if admission.get("kind").and_then(Value::as_str)
        != Some("BrowserEffectAdmissionV1")
    {
        return Err(BrowserServoError::Protocol(
            "Browser effect admission kind is unsupported".into(),
        ));
    }
    let operation_id = admission
        .get("operationId")
        .and_then(Value::as_str)
        .ok_or_else(|| BrowserServoError::Protocol(
            "Browser effect admission lacks operationId".into(),
        ))?;
    stable_id(operation_id, "Browser effect admission operationId")?;
    let semantic_digest = admission
        .get("semanticDigest")
        .and_then(Value::as_str)
        .ok_or_else(|| BrowserServoError::Protocol(
            "Browser effect admission lacks semanticDigest".into(),
        ))?;
    parse_hex_32(semantic_digest, "Browser effect admission semanticDigest")?;
    let page_revision = admission
        .get("pageRevision")
        .and_then(Value::as_str)
        .ok_or_else(|| BrowserServoError::Protocol(
            "Browser effect admission lacks pageRevision".into(),
        ))?;
    parse_hex_32(page_revision, "Browser effect admission pageRevision")?;
    positive_u64(
        admission.get("workerGeneration"),
        "Browser effect admission workerGeneration",
    )?;
    positive_u64(
        admission.get("admittedAt"),
        "Browser effect admission admittedAt",
    )?;
    if admission.get("durableOrRecoverable") != Some(&Value::Bool(true)) {
        return Err(BrowserServoError::Protocol(
            "Browser effect admission is not durable or recoverable".into(),
        ));
    }
    Ok(())
}

fn response_result(frame: DecodedFrame, request_id: &str) -> Result<Value, BrowserServoError> {
''',
)

# ---------------------------------------------------------------------------
# Focused fixtures and assertions.
# ---------------------------------------------------------------------------
DRIVER_TEST = "apps/hepta-browser/test/worker-driver.test.js"
replace_once(
    DRIVER_TEST,
    '''                payload: {
                  localDispatchCrossed: true,
                  requestKind: request.kind,
                  requestPayloadDigest: request.payloadDigest,
                  requestSequence: request.sequence,
                },
''',
    '''                payload: {
                  localDispatchCrossed: true,
                  requestKind: request.kind,
                  requestPayloadDigest: request.payloadDigest,
                  requestSequence: request.sequence,
                  admission: {
                    kind: "BrowserEffectAdmissionV1",
                    operationId: request.payload.operationId,
                    semanticDigest: request.payload.semanticDigest ?? D1,
                    workerGeneration: request.generation,
                    pageRevision: D1,
                    admittedAt: Date.now(),
                    durableOrRecoverable: true,
                  },
                },
''',
)
replace_once(
    DRIVER_TEST,
    '''  assert.equal(dispatched.terminalObserved, false);
  const terminal = await driver.reconcile({
''',
    '''  assert.equal(dispatched.terminalObserved, false);
  assert.equal(dispatched.admission.kind, "BrowserEffectAdmissionV1");
  assert.equal(dispatched.admission.operationId, "operation.1");
  const terminal = await driver.reconcile({
''',
)

SERVICE_TEST = "apps/hepta-browser/test/agentd-service.test.js"
replace_once(
    SERVICE_TEST,
    '''          return { kind: "BrowserEffectObservationV1", status: "indeterminate", terminalObserved: false };
''',
    '''          return {
            kind: "BrowserEffectObservationV1",
            status: "indeterminate",
            terminalObserved: false,
            admission: {
              kind: "BrowserEffectAdmissionV1",
              operationId: input.operationId,
              semanticDigest: D1,
              workerGeneration: 1,
              pageRevision: D1,
              admittedAt: 1,
              durableOrRecoverable: true,
            },
          };
''',
)
replace_once(
    SERVICE_TEST,
    '''  assert.equal(boundary.payload.requestDigest, D1);
  assert.deepEqual(events, ["host_admitted", "inside_fence"]);
''',
    '''  assert.equal(boundary.payload.requestDigest, D1);
  assert.equal(boundary.payload.admission.kind, "BrowserEffectAdmissionV1");
  assert.equal(boundary.payload.admission.operationId, "operation.1");
  assert.deepEqual(events, ["host_admitted", "inside_fence"]);
''',
)

EGRESS_TEST = "apps/hepta-browser/test/egress-broker.test.js"
# Activate each positive fixture after the broker is started. The private-target
# rejection tests fail at start and intentionally do not activate an effect.
text = read(EGRESS_TEST)
text = text.replace(
    "  await broker.start();\n  try {\n    const ok = await rawProxy(",
    '''  await broker.start();
  broker.activateEffect({
    operationId: "operation.http",
    effectGrantDigest: GRANT_DIGEST,
    origin: `http://127.0.0.1:${allowedPort}`,
    deadlineMs: Date.now() + 30_000,
  });
  try {
    const ok = await rawProxy(''',
    1,
)
text = text.replace(
    "  await broker.start();\n  try {\n    for (const path of [\"/one\", \"/two\"]) {",
    '''  await broker.start();
  broker.activateEffect({
    operationId: "operation.dns",
    effectGrantDigest: GRANT_DIGEST,
    origin: `http://pinned.test:${port}`,
    deadlineMs: Date.now() + 30_000,
  });
  try {
    for (const path of ["/one", "/two"]) {''',
    1,
)
text = text.replace(
    "  await broker.start();\n  try {\n    const allowed = await connectTunnel(",
    '''  await broker.start();
  broker.activateEffect({
    operationId: "operation.connect",
    effectGrantDigest: GRANT_DIGEST,
    origin: `https://${allowedAuthority}`,
    deadlineMs: Date.now() + 30_000,
  });
  try {
    const allowed = await connectTunnel(''',
    1,
)
if text == read(EGRESS_TEST):
    raise RuntimeError("egress tests were not updated")
write(EGRESS_TEST, text)

# Rust test fixtures that model a successful boundary must now include the
# exact admission object. Use a narrow replacement of the common JSON fragment.
rust = read(RUST)
rust = rust.replace(
    '''                    "witnessDigest": witness,
                    "localDispatchCrossed": true,
''',
    '''                    "witnessDigest": witness,
                    "localDispatchCrossed": true,
                    "admission": {
                        "kind": "BrowserEffectAdmissionV1",
                        "operationId": "operation.test",
                        "semanticDigest": "1".repeat(64),
                        "workerGeneration": 1,
                        "pageRevision": "2".repeat(64),
                        "admittedAt": 1,
                        "durableOrRecoverable": true,
                    },
''',
)
write(RUST, rust)

# ---------------------------------------------------------------------------
# Refresh the verified transitive service closure and generated source truth.
# ---------------------------------------------------------------------------
manifest_path = ROOT / "apps/hepta-browser/service-manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
for path in list(manifest["files"]):
    manifest["files"][path] = git_blob(f"apps/hepta-browser/{path}")
manifest_text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
manifest_path.write_text(manifest_text, encoding="utf-8")
manifest_sha256 = hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()
bootstrap = "apps/hepta-browser/src/verified-service-bootstrap.js"
bootstrap_text = read(bootstrap)
bootstrap_text, count = re.subn(
    r'const EXPECTED_MANIFEST_SHA256 =\n  "[0-9a-f]{64}";',
    f'const EXPECTED_MANIFEST_SHA256 =\n  "{manifest_sha256}";',
    bootstrap_text,
    count=1,
)
if count != 1:
    raise RuntimeError("verified service bootstrap manifest digest was not refreshed")
write(bootstrap, bootstrap_text)

subprocess.run(
    ["node", "apps/hepta-browser/scripts/browser-source-registry.js"],
    cwd=ROOT,
    check=True,
)

print("browser.servo boundary hardening applied")
