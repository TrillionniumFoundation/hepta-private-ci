# Executable frozen-model confirmation plumbing — HOLD

This package implements request/usage accounting, real local tools, four baseline
interfaces and the conservative acceptance calculation in
[the preceding confirmation design](../ndu_walltime/CONFIRMATION_PROTOCOL.md).
**No real LLM was executed. No untouched confirmation bank or actual billing
reconciliation is available. There is no net-benefit or new-RL result here.**
The existing `ndu_walltime` code and its evidence are unchanged.

## Components and evidence boundaries

| Component | Implemented behavior | Qualification boundary |
| --- | --- | --- |
| `transport.py` | Local JSON worker; native HTTP or OpenAI-compatible chat wire format; supervised timeout; private request ledger; final-invoice join | Loopback HTTP and scripted processes only |
| `confirmation.py` | Source-cluster pairing, complete costs, Bonferroni-Hoeffding and adoption gate | Synthetic arithmetic/adversarial records are tests, not observations |
| `tasks.py` | Hashed file and read-only SQLite acquisition, independent exact verifier, four acquisition policies | Executable local tasks; no claim that synthetic fixtures are external evaluation |
| `external_smoke/` | Separately documented Chinook/CPython source snapshots and actual subprocess tools | Two source clusters; disclosed engineering smoke, not confirmation |

The implementation is split into small request, ledger, schema-contract, callback
binding, task and gate modules. The four independent-review repairs are separate
behavioral changes, not one small patch. `evidence/qualification.json` binds the
current checks to exact source hashes. `qualification-original.json` preserves
the superseded 19-test receipt: it predates four substantive blockers and is not
acceptance evidence for the repaired implementation. The intermediate 37-test
receipt is retained in `qualification-before-clock-review.json`; it precedes
the final request-interval and verification-order repairs.
`status.json` lists inputs still missing. `schema.json` describes the evidence
bundle and provider/receipt definitions. Runtime semantic checks use the standard
library: `contracts.py` enforces the finite keyword subset actually used by the
checked-in schema, including required fields and strict scalar types. External
JSON Schema tooling remains an optional independent cross-check.

## Request interface and private ledger

A local provider is `{"kind":"local","argv":[...],"identity":{...}}`. Commands
receive one JSON object on stdin and return one JSON object on stdout, without a
shell. The model response contract is:

```json
{"model_id":"immutable-id","revision":"immutable-revision",
 "text":"{\"answer\": 42}",
 "usage":{"input_tokens":120,"output_tokens":8,"cached_input_tokens":0},
 "provider_request_id":"provider-job-id"}
```

Every model response must echo the frozen identity. Missing/mismatched identity
cannot be silently filled from the request. Some providers return an immutable
snapshot identifier in `model`; mapping both identity fields to that response
field is acceptable only if the frozen revision evidence establishes this
binding. A mutable alias alone does not establish immutable weights.

For HTTP, fill `provider.example.json`. `url_env` and `key_env` are environment
variable **names**; credentials are read only in the child HTTP worker. The
response map contains JSON key/index paths. `wire_format:"openai_chat"` sends
`model`, `messages` and the frozen decoding object; map `text` to
`["choices",0,"message","content"]` and token fields to the actual provider
usage fields. API compatibility is not a claim of provider/model access.
HTTP is restricted to HTTPS except loopback fixtures; redirects are rejected.
A client request ID is sent in `X-Client-Request-Id` (header name configurable)
to support reconciliation of admitted work whose response is later lost.

Before a worker or HTTP request can start, `call` appends and fsyncs a private
`ndu.request.v2` **intent**, including request ID, frozen hashes and task context;
the directory entry is fsynced too. An unwritable ledger prevents dispatch. It
then appends a terminal record bound to the exact intent hash. A crash or failed
terminal write leaves the intent on disk. Supply the complete raw ledger to the
gate: missing/duplicate phases, changed context, an orphan or an unfinished
intent produce HOLD even if a zero bill is supplied. Completed pairs count as
one attempt and receive one invoice line. Raw completed order must match the
episode request list. Successful delivery ends with successful model inference,
then successful verification, then its host meter. An undispatched attempt cannot
claim a response or success; dispatch must lie inside its recorded interval and
success must finish by the request deadline. A host envelope is a separate meter.

The call entry fixes an absolute monotonic deadline, bounded by the episode
deadline. Hashing, intent construction and fsync consume this allowance. After
fsync the remaining allowance is recomputed; if exhausted, an undispatched
timeout terminal is written and no worker starts. The invocation checks again
after request encoding. The request duration includes intent overhead; its
terminal append and all other host work remain inside the episode envelope.
Admission is checked before the process-launch call; POSIX scheduling and cleanup
are not a hard real-time OS guarantee.

The ledger records UTC timestamps, monotonic start/end, timeout, exit/parse
status, expected/observed identity digests, input/output digests, input/output
and optional cached-input tokens, and hashed provider request IDs. It never
stores headers, endpoint URLs, credentials, prompts, model response text or
exception messages. Parsed final answers are retained in episode records for
verifier replay; use appropriate access controls for those task artifacts.
The endpoint value is hashed into `transport_hash(config)` so a changed endpoint
cannot masquerade as the frozen transport.

Unknown usage is `null`, never a guessed token count. Reported provider prices
are retained as estimates, with `actual_amount:null` and `pending` reconciliation.
A final invoice line must join to every attempt, including timeout, failed launch,
retry, cancellation and an authoritative zero-charge attempt. Invoice lines need
`request_id`, `status:"final"`, `amount`, `currency`, `invoice_sha256`, `line_id`,
and the known hashed provider request ID. Later authoritative usage can resolve
previously unknown usage; contradictory or malformed counts remain HOLD. An
`ok` model terminal must have `response_received:true`, `identity_status:"match"`
and an observed digest for the frozen model ID and revision. Copying the expected
digest into an invoice cannot repair a successful response missing this evidence.
An explicit mismatch is never repairable.

Only a `failure` or `timeout` with no response and unobserved identity can use an
invoice supplement. It needs `identity_sha256` plus `identity_evidence_sha256`
resolving to actual material with schema `ndu.provider.identity_receipt.v1`,
`issuer`, `request_id`, `invoice_sha256`, `model_id` and `revision`. All bindings
must match. The extra material must be authentic provider/accounting evidence;
software checks its bytes and bindings, not the truth of an unsigned attestation.

`host_envelope` is a separate resource-meter record for each episode. Its final
cost allocation covers host computation, including the planner and adapter;
it is not silently free. Avoid overlapping host charges in tool/provider bill
lines. Delay disutility `time_price * envelope_wall` is charged once and is not
a sum of stage durations. A host meter overlaps every stage and is excluded
from the serial stage-duration subtotal. Final episode/host-meter serialization
is outside the measured service envelope and belongs in lifecycle reporting
costs; per-request ledger writes are inside the service envelope.

Workers run in their own POSIX process group and are cleaned up after return or
timeout. No guarantee is made for detached descendants or cancellation of work
already admitted remotely; the latter still needs its eventual bill. Captured
output is bounded before interpretation, not by a streaming memory sandbox.
Cancellation is checked at boundaries; in-flight calls end at timeout. No
automatic retries or paid external requests were made for this qualification.

## Baselines and task adapter

`select_action` exposes direct STOP, a frozen fixed budget, one-step VOI and an
exact finite-model planner. The planner uses the same supplied prior, deterministic
observation likelihoods, predicted durations and predicted prices as the myopic
policy. It optimizes expected MAP terminal accuracy over feasible query sequences
(each query at most once), can exploit complementary queries, and checks the
real planning-time allowance. Limits are ten tools and 256 hypotheses.
The predictions can be wrong; an unpredicted observation causes STOP rather than
an invented posterior. The actual final model answer is independently scored.
This is model-based planning, not learned optimal stopping or new model-free RL.
Its surrogate class is limited: broad superiority still requires a frozen,
externally reviewable strong-baseline qualification artifact.

A task has `id`, `prompt`, `expected_answer`, `tools` and `planning_model`.
Each tool has `kind:"file"|"sqlite"`, `path`, raw-file `sha256`,
`predicted_seconds`, `predicted_currency`, and either a line range or frozen SQL
query. SQL uses read-only immutable mode, an authorizer and a 1000-row limit.
The model sees public task information and actual observations, not verifier
answers or tool filesystem paths. A planning hypothesis has a nonnegative
`weight`, a candidate `answer` and `signals:{tool_name:sha256(canonical(value))}`.
Candidate answers/priors are public model inputs shared by every arm; they must
come from an admissible frozen development model, not the confirmation labels.

`run_episode` measures setup, planning, tools, final model call and verification
on one monotonic clock. Only verified STOP completed by the deadline earns
quality. For baselines, call `method_digest(arm,settings)` before freezing the
source/config manifest. A full/candidate arm always requires an explicit callback,
even with no tools or zero acquisition budget. A registered baseline cannot be
replaced by a callback. The full candidate is **not invented here**.

For an auditable callback, freeze and execute it with:

```python
from .policy import policy_binding
settings["policy_binding"] = policy_binding(candidate)
method = method_digest("full", settings, candidate)
record = run_episode(task, "full", provider, settings, ledger, protocol_hash,
                     method, policy=candidate)
```

The callback signature is `candidate(public_task,history,settings,remaining,
request_model)`. It must be an undecorated top-level Python function with exactly
five positional inputs, no defaults and no closure, exported by its source
module. The entire source file, module/qualified name, actual runtime code and
referenced immutable globals are hashed. Compiling the source must reproduce the
actual code; the runtime then compares the descriptor with the required frozen
settings before/after decisions. Different executable callbacks cannot reuse a
self-declared source hash. Mutable globals, imports and executable dependencies
are rejected; constants and a narrow set of ordinary builtins are supported.
Callbacks needing libraries must first expose their decision logic within this
audited contract rather than silently extending its dependency claims.

Public task/history/settings are copied before callback entry. Use the provided
`request_model(payload)` hook for every internal model call; every such call has
its own durable intent and receipt. This is a trusted research-code audit, not a
Python security sandbox: concurrent runtime tampering, dynamic introspection and
hidden external calls violate the method contract. Interpreter, environment and
other shared-state assumptions still need the frozen experimental review.

One baseline episode, after filling and freezing its real inputs:

```bash
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_llm_confirmation.tasks \
  --task task.json --provider provider.json --settings settings.json \
  --arm strong_planner --ledger requests.jsonl --output episode.json
```

Settings include deadline/call timeout, model-time reserve, max tools, fixed
budget, currency conversion, delay price, protocol hash and method hash. The
paired schedule, repetitions, retry rules, hardware/cache state, independent
source split and full candidate must be fixed before confirmation. This CLI does
not quietly choose those experimental decisions or promote smoke tasks.

## Confirmation calculation

Supply `protocol`, all paired `records`, all `events`, final service `invoices`,
`lifecycle_invoices`, and `evidence`. Each evidence digest must resolve to exact
inline `{"text":...}`, canonical `{"json":...}`, or raw `{"path":...}` material.
A hash with no material, wrong material, unsupported version, pending bill or
missing arm produces HOLD. The files and hashes make an audit possible; they do
not prove an unsigned provider attestation is authentic or establish causal
independence. Those substantive assumptions still require external review.

The protocol must freeze all five required arms, at least two families, task
identities/source groups/clusters/weights, repeat count, all contrasts and `M`,
alpha=.05, `C_max`, gain threshold, precision and positive-integer deployment
volume. Boolean values cannot substitute for costs, quality, repeat indexes or
`N_deploy`; failure episodes still require the complete structural contract. Duplicate
content is rejected; sharing a source group across clusters/families is rejected.
Repeats average within task, frozen task weights average within cluster, and
clusters receive equal weight. Failures remain in the paired analysis. Every
registered contrast is retained; one cannot select two winning families from a
larger failed registry.

For each paired family contrast with `n` clusters, the lower bound is
`mean(D) - (1+C_max)*sqrt(2*log(M/.05)/n)`. The absolute utility radius is half
as large. The predeclared precision rule must hold for every paired family:
`n >= ceil(2*(1+C_max)^2*log(M/.05)/h^2)`. No bootstrap replaces this primary bound.
Cap breaches invalidate qualification; values are not clipped.

Lifecycle costs cover preparation, fitting, allocation search, validation,
provisioning and reporting for every arm, with explicit shared allocations.
Actual costs require final proofs. Future estimates require frozen lower/upper
bounds. The conservative paired penalty is
`(K_full_upper - K_baseline_lower)/N_deploy`, never a favorable subtraction of
an uncertain baseline upper bound. Absolute utility subtracts `K_full_upper/N`.
Every registered paired lifecycle lower bound must exceed the frozen gain, and
every family absolute lifecycle lower bound must exceed zero. Claimed mechanisms
require the registered `no_paid_identification`, `no_timing_posterior` and/or
`fixed_step_clock` contrasts. Without those contrasts there is no mechanism claim.

```bash
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_llm_confirmation.confirmation \
  protocol.draft.json --freeze --output protocol.frozen.json
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_llm_confirmation.confirmation \
  complete-evidence-bundle.json --output gate.json
```

Freeze creates a new file exclusively and reports its hash/time. It is a local
freeze, not an externally timestamped preregistration. Publish the full protocol
and hash before viewing outcomes. Do not use the deliberately synthetic positive
unit-test bundle as a study result. No actual provider/model, billing, independent
confirmation or scaling claim follows from successful software tests.


## Reproduce the repaired engineering qualification

```bash
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_llm_confirmation.qualify
```

This runs 39 scoped behavioral tests, the optional reference-schema cross-check,
and one CLI scripted fixture, then writes a source-bound qualification receipt.
The tests include all required-field omissions, successful-response identity
stripping, invoice-bound failure supplementation, duplicate/missing/orphan
intents, one-time charging, unwritable/slow ledgers preventing marker workers,
runtime callback replacement, closure rejection and metered internal model calls.
The raw log protocol is v2; old terminal-only v1 ledgers are not promoted into
confirmation evidence. Neither the tests nor their synthetic positive control
constitute real LLM evidence or an independence/cost qualification.
