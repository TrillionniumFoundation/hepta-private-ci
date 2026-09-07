# Hepta vNext Migration Contract

Hepta vNext uses upstream Codex as its only execution spine. The old Hepta
implementation is an oracle and evidence source, not a merge target.

## Frozen baselines

- Candidate spine: `upstream/main` frozen at cutoff
  `74004b5397b24662a87a5264a6ae80664168c7f3`.
- Read-only Hepta oracle: `2f704dc7c1172cefca908852456beccf4d02a5d1`.
- The old raw-U evidence run, its receipts, and its verification semantics stay
  isolated from vNext work.

## Non-negotiable invariants

1. Codex owns `ThreadManager`, `CodexThread`, session/turn execution,
   `ToolRegistry`/`ToolRouter`, state, rollout, and thread storage.
2. Hepta adds typed extensions; it does not add a second session, router,
   scheduler, or generic state store.
3. Hepta product behavior is enabled explicitly and remains disabled for the
   `codex` binary by default.
4. Governance decisions and terminal lifecycle observations cross crate
   boundaries as typed contracts, not route-specific JSON builders. External
   effect acknowledgements remain separate typed material and must never be
   inferred from handler completion.
5. Old route/report/script families migrate only through parameter tables,
   state machines, manifests, or generated projections.
6. Every migrated family must pass an old-vs-vNext canonical oracle before the
   old implementation can be retired.
7. Every new public Hepta surface must have a named product caller in
   `CALLERS.toml`. Caller-zero work remains outside the promotion stack.
   Qualification and acceptance gate binaries do not count as product callers;
   their library crates remain explicit `[[excluded]]` entries.

## Migration waves

1. Product shell: one CLI parser, `codex` and `hepta` product entries, isolated
   product configuration, and upstream-compatible release targets.
2. Governance: typed admission, authorization, effect acknowledgement,
   terminal receipt, and reconciliation hooks around the Codex lifecycle.
3. Memory: Memory, Intelligence, and KG become context/state contributors.
   Mutation authority is a separate, explicitly feature-gated product slice;
   exact-head qualification and operator acceptance remain mandatory before
   any promotion claim.
4. Channels: Telegram, Matrix, and native clients become app-server/thread
   adapters and never enter the governance kernel.
5. Evidence: persist typed receipts and project stable historical selectors
   without recreating direct compatibility routes.
6. Control UI: generate one protocol/schema projection from Rust types and
   route all mutations back through the Codex lifecycle.
7. Retirement: prove caller zero, complete shadow soak and operator acceptance,
   then remove old report, controlled, route, facade, and script families.

## Transplant whitelist

- Stable identities, capability descriptors, frozen context, decisions, and
  terminal receipt shapes.
- Authority, egress, durable-store, and evidence boundary semantics.
- Memory, Intelligence, and KG domain algorithms after dependency audit.
- Channel protocol adapters after kernel-specific code is removed.
- Historical evidence IDs, selectors, and canonical fixtures needed as oracles.

## Never transplant wholesale

- The report surface and per-state JSON builder families.
- `controlled_*` and status-canary module forests.
- Retired direct route dispatch.
- Recursive `include!` closures and hand-written re-export facades.
- Gate scripts that duplicate timeout, SHA, canonical JSON, stderr, receipt,
  lock, or `jq` behavior.
- Telegram-specific kernel policy.

## Acceptance gates per family

1. Typed contract and owner are explicit.
2. vNext output matches the canonical old-Hepta oracle byte-for-byte where the
   external contract is retained.
3. Shadow evaluation preserves upstream handler behavior and records durable
   observations when the evidence backend is available; it does not itself
   authorize new Hepta mutations. A shadow backend failure is warn-and-allow
   and must not be reported as durable evidence.
4. Static callers and persistent telemetry show the replacement is complete.
   A caller-zero writer is reported as `writer_not_composed`; it must never be
   collapsed into a zero-event observation. S2 persistent/OTel hit, failure,
   and latency telemetry remains ineligible until a product writer is named in
   `CALLERS.toml`. S5 has a feature-gated App Server reader that opens only an
   existing integrity-checked evidence store in read-only mode. An empty S5
   result therefore describes that store at read time; it is not proof of
   writer coverage, authority, or promotion readiness.
5. Operator acceptance is required before retirement. The current
   qualification-evidence receipt does not itself authorize retirement.
6. Exact-SHA local, Nix, and hosted receipts are refreshed only after the
   candidate SHA is clean and frozen.

## Current vertical slice

- The `hepta` and `codex` binaries compile the same CLI parser.
- `hepta` forces the private `hepta_governance` feature; `codex` leaves it off.
- App-server and MCP thread registries install a feature-gated governance
  extension.
- Codex Extension API exposes one generic two-phase `ToolPolicyContributor`:
  admission sees the original payload, authorization sees the effective payload
  after trusted hook rewrites, and both execute on the only ToolRegistry path.
- Governed threads currently reject configured `mcp_tool` hooks before MCP
  runtime lookup or transport. The rejection is an ordinary hook failure, so
  the outer hook flow keeps its upstream fail-open behavior; it does not invent
  a ToolPolicy attempt or terminal. Upstream `mcp_tool` hook behavior remains
  available only when Hepta governance is disabled and no active tool-policy
  contributor is installed. Trusted command hooks remain a separate host
  authority boundary; this slice does not claim that their side effects pass
  through ToolPolicy.
- Tool identities use a versioned, length-delimited digest. Decisions bind a
  versioned policy stamp and payload digest while preserving direct versus Code
  Mode call identity; raw tool arguments are never written to governance rows.
  Both bootstrap phase records are explicitly `NotEvaluated`. The
  Authorization phase name identifies the lifecycle boundary only; it is not
  capability-policy authorization, fresh approval, or an execution credential.
- `codex-hepta-evidence` owns an append-only `hepta_evidence_2.sqlite` lineage with WAL,
  `synchronous=FULL`, immutable rows, foreign-key-bound decisions/receipts,
  exact-replay idempotency, and hard conflict detection. It is opened lazily
  only for feature-enabled threads and is not a rebuildable Codex state index.
  Open validates SQLite `quick_check`, SQLx migration checksums, a required
  table/index/immutable-trigger schema-object manifest, and
  `foreign_key_check`. This is a required-object and SQL-fragment ratchet, not
  a cryptographic proof against complete database replacement.
- The App Server and MCP installations currently use Shadow mode until
  canonical oracle soak and an operator acceptance receipt. In Enforce mode, a
  pre-handler decision-write failure blocks the handler. A terminal-write
  failure occurs after the handler, returns a fatal error, and preserves an
  authorized pending action so replay of that same action is blocked; it does
  not prove exactly-once delivery or lock unrelated later effects.
- An opaque per-dispatch attempt ID scopes the in-process claim. Only the
  attempt that wins the first durable admission insert may finalize the
  original receipt. Enforce blocks an existing action before the handler.
  Shadow deliberately allows the replay to run, but the replay attempt cannot
  borrow the original claim or mint or complete its receipt. The attempt ID is
  not itself a durable execution credential.
- An observed abort terminal after durable authorization is recorded as
  `Indeterminate`. If the outer tool runtime observes a handler-task panic or
  `JoinError` before another terminal commits, it records one stable
  `Indeterminate` terminal for the same attempt. Dropping the outer future can
  still leave an authorized action pending; no asynchronous `Drop` path invents
  evidence. Enforce blocks a later replay. Shadow performs no automatic
  reconciliation, but an explicit retry is still allowed and cannot finalize
  the original receipt.
- Active policy dispatches use a monotonic, attempt-scoped terminal state for
  pre-handler and handler outcomes. Once a handler result starts its terminal
  write, cancellation cannot relabel it as `Aborted`. A bounded terminal-write
  timeout becomes unconfirmed and fatal. Once the policy terminal commits,
  cancellation may stop the PostToolUse/lifecycle tail and returns a
  result-withheld, do-not-retry response without exposing the raw tool result.
  Feature-disabled dispatch keeps the upstream legacy cancellation ordering.
- Provider invocation types, a generic Hepta-neutral Extension API pre-send
  contributor/opaque lease, and separate immutable provider intent/terminal
  tables now exist. Hepta registers a provider-policy implementation that can
  atomically claim one retry-stable host request binding, persist its exact
  terminal, and block pending, completed, or indeterminate retries in Enforce
  mode. Raw host attempt/request identities, endpoint contents, and provider
  material cross the evidence boundary only as SHA-256 digests. Unary remote
  compaction success has its own items-only terminal; missing response IDs,
  token usage, or end-turn fields are never synthesized. Core HTTP, websocket,
  compact, prewarm, detached-memory, and physical-send paths now use the shared
  provider attempt/terminal lifecycle. This does not prove exactly-once external
  delivery.
- The R2 execution-substrate candidate adds feature-gated, explicit
  `turn/recover` on the existing App Server/Core turn spine. A cold candidate
  requires one exact durable turn identity, generation, provider-request
  fingerprint, annotated-history boundary, turn context, lineage, and
  nonempty thread-owned environment selection. Recovery consumes that
  authority once, persists a newer `Unready` plus a bounded replay-applied
  hand-off, reopens the same logical turn, and rejects context, environment,
  epoch, generation, or payload drift before another provider send. Agentd
  enables the feature on each Agent's private App Server UDS and binds the
  manifest queue capacity to that Agent's private SQLite queue. Within the
  queue service's serialized, observed queue set, reconciliation binds a stable
  client message ID to a versioned canonical payload digest: equal replays join
  once and observed conflicting payloads fail closed before Core submission.
  A raw cross-process `QueueStore` insert after that preflight is not covered;
  stronger cross-process guarantees require a transactional SQLite binding.
- R2 does not claim provider sampling or provider-output arrival exactly-once.
  The background transport mapper may record provider-policy evidence, tracing,
  or diagnostic telemetry before the outer turn gate. For durable and cold
  threads, model-visible response persistence, tool dispatch, hooks, commands,
  and other product effects require a durable local recovery revocation first.
  Ephemeral threads require an in-process revocation instead and cannot carry
  recovery authority across process exit. In the current process, observed
  persistence failures poison authority and attempt a newer `Unready`. If a
  positive marker may already be durable while its successor `Unready` fails,
  or a crash separates the append-only filesystem syscalls, the current process
  fail-stops; restart authority is unknown and unqualified rather than
  exactly-once.
  The current `turn/recover` invocation callers are qualification harnesses, not
  product callers, so this slice remains ineligible for promotion until a later
  ordered product stage names its caller and refreshes exact-head/operator
  receipts.
- R2 G2 independent-dual-Agent qualification composes two real `agentd`
  processes under the existing Unix supervisor in an isolated test fleet.
  Supervisor spawn overrides inherited `CODEX_SQLITE_HOME` with each Agent's
  `SpawnSpec.home_root`. Each Agent connects through its own App Server UDS and
  retains its own durable thread and queue state. The qualification rejects
  Agent B attempts to resume or recover Agent A's private thread, kills and
  restarts Agent A while Agent B remains ready at the same PID and generation
  with its in-progress turn and queued payload unchanged, then cold-resumes and
  explicitly recovers Agent A's same interrupted turn. Each Agent dispatches
  its local queued item only after its preceding turn reaches terminal state.
- G2 is a qualification topology, not a named product invocation path. Its
  lifecycle operations are test-harness actions and add no fleet lifecycle
  product authority. G2 does not enable Intelligence/KG, cross-Agent memory
  federation, Matrix/Robrix, automation, promotion, deployment, or provider
  physical exactly-once semantics.
- R2 G3 names the Agent-local Cognitive product caller. `agentd` explicitly
  enables `hepta_cognitive_write` for its private App Server; ordinary Codex
  keeps the feature off. Governance, Memory, and the dedicated write feature
  must all be enabled before remember, correct, or forget tools are registered.
  The read-only attachment feature alone grants no mutation authority.
- A G3 mutation validates bounded structured entity/relation facts and uses one
  SQLite `BEGIN IMMEDIATE` transaction for the exact source ledger revision,
  versioned Memory revision/citation/head CAS, immutable KG fact-set header and
  facts, a complete bounded projection of the scope's current verified active
  heads, an immutable generation receipt, and publication of the new current
  generation. Empty extraction still has a fact-set header. Any validation,
  citation, CAS, projection, or persistence failure rolls the whole mutation
  back; stale correction cannot leave an orphan source, and a tombstoned Memory
  identity cannot be resurrected.
- Projection nodes remain revision-local occurrences and retain every exact
  Memory/source provenance. A stable canonical entity identity links matching
  occurrences for one-hop traversal without selecting a representative
  provenance. Correction and forget retain historical immutable facts while
  excluding superseded or tombstoned heads and advancing the projection
  generation.
- Automatic retrieval performs Memory FTS, entity FTS, graph one-hop, recency,
  explanation, and revalidation binding reads in one SQLite snapshot. The
  provider attachment's internal schema binds each selected Memory to its exact
  retrieval channels; every physical send revalidates the Memory head,
  citations, scope, validity, and KG generation before optional context is
  attached. Retrieval/storage failure removes optional context rather than
  widening authority.
- The Responses WebSocket path does not yet implement exact ephemeral-input
  conformance. A turn with an active ephemeral contributor therefore skips
  WebSocket prewarm/dispatch and uses the existing sensitive HTTP path that
  resolves and binds the attachment for that physical attempt. Turns without
  an active contributor retain ordinary WebSocket eligibility; G3 makes no
  claim of WebSocket ephemeral-input conformance.
- The final SQLite revalidation snapshot ends before the provider network
  dispatch. G3 therefore does not claim that provider send is linearizable
  with a concurrent Cognitive mutation in that final local-check-to-network
  window. A drift detected during revalidation removes the attachment; closing
  the remaining window would require a provider-visible transactional binding
  or equivalent acknowledgement protocol.
- Migration `0003` preserves prior Memory and citation rows but revokes the
  unqualified, test-only pre-G3 projection. Pre-G3 revisions receive an
  explicit legacy zero-fact header; this is not a claim of legacy persistent-KG
  compatibility. A G2 binary is not qualified to reopen the migrated database.
  Rollback therefore requires restoring both the old binary and a consistent
  pre-migration database snapshot. Reopen integrity verification currently
  scans all historical fact sets; G3 qualifies correctness for the bounded
  product tests, not large historical-archive reopen performance. That scale
  qualification remains a later fleet/operations gate.
- The G3-qualified product path remains Agent/workspace local. G3 neither
  qualifies nor adds authority for cross-Agent Memory federation,
  Matrix/Robrix, fleet lifecycle mutation, automation, deployment, or provider
  physical exactly-once semantics. The exact head still contains pre-existing
  later-stage candidate implementations, including federation and automation;
  their callers and tests are explicitly excluded from the three named G3
  qualification tests. Their presence is not G3 qualification, activation,
  operator acceptance, or promotion authority. The G3 receipt is only the
  sequence gate for G4.
- The G3-qualified subset of the current candidate stack governs ToolRegistry
  dispatch and the listed provider send paths and composes the bounded
  Agent-local Cognitive writer and revalidated retrieval path described above.
  Cross-Agent federation, external channel transport, outbound delivery,
  effect ACK, retirement, and automatic reconciliation stay outside the G3
  qualification scope; this is not a claim that their pre-existing candidate
  code is absent from the exact-head tree. `HandlerCompleted` is
  handler-reported status, not
  proof of an external effect or exactly-once execution.
- The Hepta product resolves its process home as
  `HEPTA_HOME > CODEX_HOME > ~/.hepta` before the shared Codex loader starts.
  Ordinary `codex` keeps its upstream home behavior. Explicit `HEPTA_HOME` and
  `CODEX_HOME` values must already name a directory, and non-UTF-8 values fail
  rather than silently falling back. The resolved home is bound once within a
  process and cannot be rebound. Across launches, changing `HEPTA_HOME` selects
  a different evidence path; current code neither detects nor migrates the
  prior store. No implicit merge or fallback occurs, so store-instance binding
  and a checked migration gate remain future work.
- `hepta --version` embeds an unbound identity for ordinary local builds.
  Release automation may declare an exact identity only with a 40- or 64-hex
  `CODEX_RELEASE_SOURCE_SHA` and `CODEX_BUILD_SOURCE_DIRTY=false`. The resolver
  does not inspect Git or cryptographically bind the artifact to that checkout,
  so this is declared build metadata, not verified exact-SHA provenance.
  Readback, Nix, hosted, signing, and promotion receipts remain acceptance work.

## Signed final-use implementation

[Final-use authority and independent issuer](FINAL_USE.md) specifies the host-pinned Ed25519 verifier, durable nonce/revocation store, private verified token, final callback fence and separate supervisor signing command used by the Bao consumer. It documents the concrete API and local Unix storage limits independently of the migration baselines above.
