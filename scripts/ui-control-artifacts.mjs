#!/usr/bin/env node
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const manifestPath = resolve(root, "qualification/ui-control/UI_CONTROL_MANIFEST.json");
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
const mode = process.argv[2] ?? "--write";
if (!["--write", "--check"].includes(mode)) {
  throw new Error("usage: node scripts/ui-control-artifacts.mjs [--write|--check]");
}

const q = value => `\`${value}\``;
const statusRows = Object.entries(manifest.status)
  .map(([key, value]) => `| ${q(key)} | ${q(value)} |`)
  .join("\n");
const invariantLines = manifest.invariants.map(value => `1. ${value}`).join("\n");
const commandLines = manifest.verification.commands.map(value => `- ${q(value)}`).join("\n");
const gateLines = manifest.externalEvidenceGates.map(value => `- ${value}`).join("\n");
const receiptSchemaLines = Object.entries(manifest.receiptSchemas)
  .map(([key, value]) => `- ${q(key)}: ${q(value)}`)
  .join("\n");

const technical = `# ui.control technical development guide

> Generated from ${q("qualification/ui-control/UI_CONTROL_MANIFEST.json")}. Edit the manifest or generator, not this file.

## 1. Scope and current truth

${q("ui.control")} is an authority-free runtime-control client and browser console. It owns presentation state, authenticated session metadata, bounded local recovery records, and user interaction. Runtime owners retain authorization, durable operation identity, mutation authority, and terminal facts.

The active convergence branch is ${q(manifest.authoritativeDevelopmentBranch)}. The repository baseline used to start this convergence is ${q(manifest.baseline.commit)} / tree ${q(manifest.baseline.tree)}. Tracked documentation never self-certifies its own final commit; exact-head identity and outcomes are emitted by CI in ${q(manifest.receiptSchemas.repositoryReceipts)}.

| Dimension | Current state |
|---|---|
${statusRows}

## 2. Repository layout

- ${q("apps/hepta-control-ui/src/")}: framework-free ESM client core, HTTP transport, session provider, and browser controller.
- ${q("apps/hepta-control-ui/web/")}: semantic HTML/CSS browser shell.
- ${q("apps/hepta-control-ui/test/")}: unit, hostile-input, concurrency, recovery, package, and transport tests.
- ${q("apps/hepta-control-ui/e2e/")}: Chromium, Firefox, and WebKit product-path tests with axe-core.
- ${q("docs/modules/ui.control/THREAT_MODEL.md")}: trust boundaries and mitigations.
- ${q("docs/modules/ui.control/SERVER_IDEMPOTENCY.md")}: normative backend operation ledger contract.
- ${q("docs/modules/ui.control/OPERATIONS.md")}: deployment, monitoring, incident, and rollback runbook.

## 3. Public boundaries

${manifest.publicApi.map(value => `- ${q(value)}`).join("\n")}

The package exposes explicit ${q("exports")} for the root/core, browser controller, and HTTP transport. Imports under ${q("@hepta/control-ui/src/*")} are deliberately blocked. The browser build uses the same source modules as Node tests and does not need a framework runtime or unsafe HTML injection.

## 4. State model

A usable view is a tuple:

${q("(sessionId, connectionGeneration, runtimeGeneration, revision, semanticDigest, modules)")}

The transition validator enforces:

${invariantLines}

The browser persists only bounded recovery metadata. It never persists credentials, CSRF tokens, backend responses containing secrets, or a claim that a mutation succeeded.

## 5. Mutation sequence

${"```mermaid"}
sequenceDiagram
  participant O as Operator
  participant UI as Browser shell
  participant C as RuntimeClient
  participant T as Same-origin transport
  participant L as Server operation ledger
  participant R as Runtime owner
  O->>UI: confirm action, target, reason
  UI->>C: submit operation intent
  C->>C: validate session/view and reserve operationId
  C->>T: one mutation request
  T->>L: INSERT operationId + semanticDigest (unique)
  alt new identity
    L->>R: enqueue authority-owned request
  else same identity and digest
    L-->>T: return existing record
  else same identity, different digest
    L-->>T: reject conflict
  end
  T-->>C: accepted acknowledgement or connection loss
  alt acknowledgement received
    C-->>UI: pending + auditTraceId
  else outcome ambiguous
    C-->>UI: indeterminate; require lookup
    UI->>T: lookup operationId + semanticDigest
    T->>L: read durable operation record
    L-->>UI: pending or terminal observation
  end
${"```"}

## 6. Digest and identity domains

| Value | Domain / authority | Purpose |
|---|---|---|
| Runtime projection digest | ${q("hepta.ui-control.runtime-projection.v1")} | Stable projection comparison |
| Snapshot digest | ${q("hepta.ui-control.runtime-snapshot.v1")} | Bind session/generation/revision/module bytes |
| Operation intent digest | ${q("hepta.ui-control.operation-intent.v1")} | Bind action/target/generation/revision/reason |
| Operation ID | Client-generated stable identifier; server unique index | Retry and audit identity |
| Audit trace ID | Server-generated | Cross-service observation and incident correlation |

Canonicalization accepts only bounded plain JSON values, safe integers, NFC strings without control/bidi-invisible characters, and keys other than ${q("__proto__")}, ${q("constructor")}, and ${q("prototype")}.

## 7. Authentication, permissions, and transport

The client requires an authenticated session with an exact protocol version, expiry, permission revision, connection generation, stable identity, and explicit permissions. Session refresh may increase permission revision or connection generation; a changed connection generation invalidates the displayed snapshot. Revocation and expiry disable control operations.

${q("SameOriginHttpTransport")} enforces same-origin API paths, credentials-included requests, no-store caching, redirect rejection, 64 KiB canonical JSON requests, one-megabyte JSON responses, explicit pre-dispatch failure classification, request IDs, CSRF on mutations, timeout/abort typing, and no automatic mutation retries. A network error after dispatch is ambiguous, not failed.

## 8. Browser interaction and accessibility

The browser shell provides:

- visible stale, disconnected, pending, terminal, failure, and indeterminate states;
- full runtime generation and revision display plus deterministic redaction of session, operation, audit-trace, snapshot, semantic, and outcome correlation identifiers; exact full identifiers remain in typed client state and transport objects and are not copied into DOM text or attributes;
- modal confirmation for start, reconcile, and stop requests;
- duplicate-activation suppression before network dispatch;
- semantic tables, labels, alerts, live regions, skip navigation, visible focus, reduced-motion support, and focus restoration;
- axe-core scans and keyboard assertions in real Chromium, Firefox, and WebKit engines.

Automated checks do not replace manual screen-reader/operator acceptance; that remains an external signed gate.

## 9. Typed failures

Stable error codes include ${q("UI_CONTROL_SESSION_EXPIRED")}, ${q("UI_CONTROL_PERMISSION_DENIED")}, ${q("UI_CONTROL_STALE_GENERATION")}, ${q("UI_CONTROL_STALE_REVISION")}, ${q("UI_CONTROL_SNAPSHOT_DRIFT")}, ${q("UI_CONTROL_PENDING_LIMIT")}, ${q("UI_CONTROL_OPERATION_CONFLICT")}, ${q("UI_CONTROL_BACKEND_REJECTED")}, ${q("UI_CONTROL_ACK_MISMATCH")}, and ${q("UI_CONTROL_AMBIGUOUS_SUBMISSION")}.

Callers branch on ${q("code")} and ${q("retryable")}; parsing message text is unsupported. The console renders only known error codes with fixed operator messages. Detailed messages, backend validation labels, details and causes remain outside DOM text and live regions.

## 10. Evidence semantics

- **Observed outcome:** ${manifest.evidenceSemantics.observedOutcome}
- **Accepted evidence:** ${manifest.evidenceSemantics.acceptedEvidence}
- **Overall acceptance:** ${manifest.evidenceSemantics.overallAcceptance}

Receipt schemas are sourced from the same manifest:

${receiptSchemaLines}

## 11. Qualification

Repository checks:

${commandLines}

The dedicated workflow binds checkout SHA and tree, runs unit/contract/build/browser/axe/Lane-B/document checks, verifies a clean tracked tree, and uploads the generated receipt and browser build manifest. A passing mock/protocol-equivalent E2E proves repository composition, not a production deployment.

## 12. Remaining external evidence gates

${gateLines}

## 13. Definition of done

The repository portion is complete when the authoritative branch is merged, generated projections are current, exact-head and synthetic-merge checks pass, all three browser engines and axe pass, Lane B truth passes, and a receipt is uploaded. Production completion additionally requires every external gate above and an independent acceptance signature.
`;

const map = {
  schema: "hepta.module-implementation-map.v3",
  schemaVersion: 3,
  sourceBase: manifest.historicalSourceBase,
  sourceIdentityPolicy: "candidate_or_exact_observation_v1",
  mappingSourceIdentityMode: "exact_blob",
  observedAtHead: manifest.sourceObservation,
  observedSourcePaths: manifest.sourceRoots,
  sourceObjects: manifest.sourceObjects,
  laneId: manifest.laneId,
  module: manifest.module,
  sourceMaturity: "browser_console_candidate",
  declaredRoots: manifest.sourceRoots,
  resolvedRoots: manifest.sourceRoots,
  statusManifest: "qualification/ui-control/UI_CONTROL_MANIFEST.json",
  currentStatus: manifest.status,
  evidenceSemantics: manifest.evidenceSemantics,
  verificationStages: manifest.verificationStages,
  receiptSchemas: manifest.receiptSchemas,
  stateOwnerDisposition:
    "Owns presentation/session state and bounded pending/recovery identities only; backend modules retain authority, durable operation uniqueness, and terminal facts.",
  terminalObserverDisposition:
    "A durable authenticated backend observation establishes terminal state; local acknowledgement, timeout, disconnect, or browser persistence never does.",
  operations: manifest.operations.map(operation => ({
    designOperation: operation.id,
    mappingClass: "owner_boundary",
    ownerEntrypoint: {
      role: "owner_entrypoint",
      path: "apps/hepta-control-ui/src/runtime-client.js",
      symbol: operation.symbol,
      buildTarget: "hepta-control-ui",
    },
    delegatedCallees: [],
    tests: [
      {
        path: "apps/hepta-control-ui/test/runtime-client.test.js",
        kind: "node_product_boundary",
        command: "node --test apps/hepta-control-ui/test/runtime-client.test.js",
      },
    ],
    sourceSemantics: operation.semantics,
    operation: operation.id,
    nativeSymbol: operation.symbol,
    sourcePath: "apps/hepta-control-ui/src/runtime-client.js",
    sourceBlob: manifest.sourceObjects.find(item =>
      item.path === "apps/hepta-control-ui/src/runtime-client.js").object,
    sourcePathExists: true,
  })),
  repositoryControlledGaps: [],
  externalEvidenceGates: manifest.externalEvidenceGates,
  claimBoundary: {
    nativeSourceMappingComplete: true,
    repositoryControlledDocumentationGapsClosed: true,
    repositoryControlledMappingGapsClosed: true,
    repositoryControlledSourceBoundaryGapsClosed: true,
    clientCoreSubstantiallyImplemented: true,
    repositoryBrowserShellImplemented: true,
    repositoryAuthTransportAdaptersImplemented: true,
    browserCorrelationIdentifiersRedacted: true,
    dependencyLockCommitted: true,
    serverIdempotencyContractDefined: true,
    exactHeadQualificationWorkflowPresent: true,
    exactHeadQualificationDerivedByWorkflow: false,
    productExecutionComplete: false,
    deploymentQualificationComplete: false,
    independentAcceptanceComplete: false,
    sourceRootPresent: true,
    productionImplementation: false,
    productExecutionProved: false,
    independentAcceptance: false,
    activation: false,
    release: false,
    implementedOperationMappingComplete: true,
  },
  sourceRootPresent: true,
  productionImplementation: false,
  productCallerState: "repository_browser_shell_fixture_composed_deployment_unbound",
  productCallers: manifest.productCallers,
  productionWriterState: "backend_contract_defined_writer_unobserved",
  owner: manifest.owner,
  deputy: manifest.deputy,
  technicalGuide: "docs/modules/ui.control/TECHNICAL.md",
  sourceRoot: manifest.sourceRoots,
};

const dossier = `# ui.control execution dossier

> Generated from ${q("qualification/ui-control/UI_CONTROL_MANIFEST.json")}.

## Candidate identity

- authoritative development branch: ${q(manifest.authoritativeDevelopmentBranch)}
- convergence baseline: ${q(manifest.baseline.commit)} / ${q(manifest.baseline.tree)}
- exact candidate SHA/tree: derived by the qualification workflow
- release authorization: absent

## Implemented repository boundary

- framework-free ESM client core and explicit package exports;
- typed session, permission, transport, stale-view, snapshot-drift, and ambiguity failures;
- atomic pending reservation and concurrent duplicate promise sharing;
- durable recovery-state export/restore without authority claims;
- same-origin CSRF-protected HTTP adapter with no mutation retry;
- semantic HTML browser shell with start/reconcile/stop confirmation, operator identity visibility, and deterministic DOM redaction for correlation identifiers;
- Chromium, Firefox, WebKit, axe-core, keyboard, focus, stale-revision, duplicate-activation, accepted-timeout, storage-denial, and privacy-redaction tests;
- single-manifest generated technical guide, implementation map, status/gate projections, and this dossier.

## Evidence matrix

| Case | Repository evidence | Expected result |
|---|---|---|
| UI-01 coherent view | ${q("runtime-client.test.js")} | generation/revision/digest projection accepted |
| UI-02 same-revision drift | ${q("runtime-client.test.js")} | ${q("UI_CONTROL_SNAPSHOT_DRIFT")} |
| UI-03 concurrent duplicate | ${q("runtime-client.test.js")} | one transport call, shared result |
| UI-04 pending capacity race | ${q("runtime-client.test.js")} | reservation prevents oversubscription |
| UI-05 accepted-timeout | unit and browser E2E | indeterminate, then operation lookup |
| UI-06 semantic conflict | unit and server fixture | fail closed / HTTP 409 |
| UI-07 stale confirmation | browser E2E | backend 412 surfaced, no operation created |
| UI-08 accessibility | Playwright + axe-core | zero automated violations; focus restored |
| UI-09 package boundary | ${q("api-surface.test.js")} | explicit exports; deep imports rejected |
| UI-10 Lane B cross-owner | ${q("test_hepta_lane_b_path_guard.py")} | canonical cross-lane map accepted; escapes rejected |
| UI-11 browser privacy | ${q("control-console.spec.mjs")} | full session/operation/audit/digest material and unknown exception text remain absent from the DOM |

## Qualification commands

${commandLines}

## Evidence and receipt semantics

- **Observed outcome:** ${manifest.evidenceSemantics.observedOutcome}
- **Accepted evidence:** ${manifest.evidenceSemantics.acceptedEvidence}
- **Overall acceptance:** ${manifest.evidenceSemantics.overallAcceptance}

${receiptSchemaLines}

The CI repository receipt records exact SHA/tree, runner/Node identity, check outcomes, and browser build-manifest digest. It sets production deployment, identity-provider, deployed CSP, independent acceptance, and release authorization to false unless separately observed and accepted. The tracked repository does not pre-claim those facts.

## Remaining non-repository evidence

${gateLines}
`;

const outputs = new Map([
  ["docs/modules/ui.control/TECHNICAL.md", `${technical.trimEnd()}\n`],
  ["docs/modules/ui.control/IMPLEMENTATION_MAP.json", `${JSON.stringify(map, null, 2)}\n`],
  ["qualification/module-execution-dossiers/detail/ui.control.md", `${dossier.trimEnd()}\n`],
]);

let changed = false;
for (const [relativePath, expected] of outputs) {
  const path = resolve(root, relativePath);
  if (mode === "--write") {
    await writeFile(path, expected);
    console.log(`wrote ${relativePath}`);
  } else {
    const actual = await readFile(path, "utf8");
    if (actual !== expected) {
      changed = true;
      console.error(`stale generated artifact: ${relativePath}`);
    }
  }
}
if (changed) process.exitCode = 1;
