# MEM13: independent native path diagnostic

This protocol does not change MEM12's frozen 80-arm Python-store cohort. It
connects the existing native SQLite owner, episodic importer, owner revalidation,
final-use claim, native App Server driver, actual HTTP request, and isolated local
model provider. It is a synthetic path diagnostic, not a memory-benefit acceptance
test. Production owner custody and scientific acceptance remain **HOLD**.

## Fixed actor and scope

The Rust entry is the ignored test
`episodic_real_provider_native_intervention` in `codex-hepta-agentd`.
It reuses the retained fixture owner and fixture signing authority already used
by `episodic_real_provider_fresh_context_smoke`. The signing key is a public test
key; it does not authenticate a deployment owner. A is a deterministic snapshot
import in the harness. **The A harness process does not exit before C.** C uses a
fresh native App Server thread, and the actual local generation worker has fresh
mount, PID, network, IPC, UTS and user namespaces, HOME, work and cache.

The prompt and query remain the original fixture strings. The fact is a newly
random 32-hex nonce kept in the admitted source, native memory and local scorer.
The nonce is absent from the public prompt and config. Each invocation generates
its own nonce; separate invocations are **not paired benefit episodes**. The
fixture records incorrect answers and incomplete observations without replacing
the actor, adding a hint, or retrying under a fresh identity.

The adapter's fixed input mapping is
`exact-utf8-responses-json-in-single-user-message.v1`: the **complete original HTTP
JSON body**, preserving UTF-8 text, whitespace, instructions, messages, roles,
tool declarations and metadata, becomes the isolated worker's one user-message
content. The outer provider request uses the frozen model, greedy decoding,
`store=false`, and 32 output tokens. Serialized roles are not claimed to have the
same semantics as an ordinary hosted Responses implementation. Tools are retained
as text; this worker never executes them. Unsupported non-text/history items are
rejected, not silently discarded. No evaluator nonce is added by the adapter.

## Independent predeclared limits

| Quantity | Limit or behavior |
| --- | --- |
| Native HTTP body capture | 1,048,576 bytes |
| Native HTTP headers | 65,536 bytes total, 8,192 per line |
| HTTP receive deadline | 15 seconds for the complete request |
| Adapter listening window | 120 seconds, one connection |
| Mapped provider request | 65,536 bytes |
| Actual tokenizer input | 1,024 tokens, no truncation |
| Generated tokens | At most 32 |
| Model process deadline | 60 seconds; public asset inventory/setup is additional |
| Native driver deadline | 180 seconds, including waiting for the provider |
| Replay | A durable server/attempt journal refuses another launch |

The existing native App Server can send large instructions and tool declarations.
**Capture first.** A captured body may exceed the mapped byte or tokenizer limit;
that is an admission failure, not permission to shorten it. Before any separate
larger-budget experiment, read and retain the frozen model's actual `config.json`
and tokenizer configuration, verify their existing profile hashes, and preregister
the new input/output limits and actor source. This protocol does not enlarge the
MEM12 worker's cap or assume the model's maximum context length.

## Execution entry points

Build and run through the repository's `just test`/nextest workflow. Native
compilation and real model calls must be scheduled once by the parent execution
owner. Python controls do not run a model:

```bash
PYTHONPATH=scripts python3 -m unittest ndu_real_runtime.test_episodic_native_adapter -v
```

Create a **new** adapter directory for one authorized operation, using the already
frozen `LocalProviderProfile` JSON and exact final native source SHA:

```bash
PYTHONPATH=scripts python3 -m ndu_real_runtime.episodic_native_adapter \
  --prepare /absolute/mem13-capture-adapter \
  --profile /absolute/frozen-profile.json \
  --request-id mem13-capture-attach-001 \
  --native-source-sha EXACT_40_HEX_COMMIT \
  --mode capture

PYTHONPATH=scripts python3 -m ndu_real_runtime.episodic_native_adapter \
  --serve /absolute/mem13-capture-adapter
```

The server prints its `http://127.0.0.1:PORT/v1` address and writes `SERVER.json`.
Run the one Rust test in a separate supervised process with these environment
values. The output root must be a new absolute directory; the fixture creates it
exclusively. Preserve the exact command, environment values and supervisor logs.

```text
HEPTA_LOCAL_PROVIDER_BASE_URL=http://127.0.0.1:PORT/v1
HEPTA_LOCAL_PROVIDER_MODEL=<exact profile model_name>
HEPTA_MEM_NATIVE_SOURCE_SHA=<same final native source SHA>
HEPTA_MEM_CONTEXT_REQUEST_ID=mem13-capture-attach-001
HEPTA_MEM_CONTEXT_RUN_ROOT=/absolute/mem13-capture-native
HEPTA_MEM_NATIVE_INTERVENTION=attach
HEPTA_MEM_NATIVE_PHASE=capture
```

Select the exact test with the repository's nextest filter. No ignored real-model
test should be included accidentally in an ordinary control sweep:

```bash
just test --locked -p codex-hepta-agentd --lib --run-ignored only --no-capture --retries 0 \
  -E 'test(episodic_real_provider_native_intervention)'
```

Capture sends an explicit HTTP 409 and zero model calls. The native test checks
that a successful generation was not reported, while preserving the normal
retrieval/final-use observations. Its own result still requires comparison with
the adapter's original HTTP evidence; a native error alone is not proof of a
captured request.

The driver deadline does not replace other existing limits: the fixture issuer
claim remains limited to two seconds, the outer issuer task to 30 seconds, and
the default nextest watchdog remains in force. Retain any earlier timeout as its
own outcome; do not interpret the 180-second driver setting as extending those
limits or repeat the operation to obtain a different outcome.

Before dispatch, the execution wrapper must bind the Rust phase, request ID,
model, source SHA and loopback address to the matching Python plan and
`SERVER.json` hash. These are separate processes and the Rust phase flag alone
cannot establish the adapter mode. Only a matching Python
`CAPTURED_WITHOUT_GENERATION` receipt with its complete incoming HTTP evidence
supports a capture-only conclusion. Missing or mismatched evidence remains
UNKNOWN; a different provider error is not a zero-model proof.

After the captured input fits the declared frozen budgets, a separately prepared
operation may use adapter `--mode generate`, native phase `generate`, and one of:

| Intervention | Native operation | Expected physical provider behavior |
| --- | --- | --- |
| `attach` | Retrieve, authorize, revalidate, attach the owner snapshot | One logical local generation; answer may be wrong |
| `withhold` | Same retrieval/authorization/revalidation, suppress explicit attachment | One logical local generation; not full memory-off |
| `tombstone` | Retrieve, then the fixture issuer performs real native `forget_with_kg` before returning the grant | Final native revalidation must reject; zero HTTP requests |

Tombstone advances the original SQLite owner revision and recovery cut, leaving
the fixture source verifier unchanged. The original `ForgetMemoryDraft`, native
mutation receipt and before/after owner cuts are included in the fixture claim
receipt. This tests revocation after retrieval, before final use. The original
fixture outbox must produce zero unrelated effects. A tombstone adapter may time
out its idle listening window with zero connections; retain its `STOPPED.json`.

## Evidence and interpretation

Preserve all native fixture files: `INTENT.json`, `A_IMPORT.json`,
`DISPATCH_INPUT.json`, `OBSERVED.json`, `FIXTURE_AUTHORITY.json`, `RESULT.json`,
the original owner directory and SQLite files, and `native-context.journal`.
Native result files do not assert a physical provider count themselves.

Preserve adapter `PLAN.json`, `SERVER.json`, `ATTEMPT.json` when present,
`STOPPED.json`, and every `http-NNNN/` directory:

- `request.http.bin`: exact observed request line, headers and body bytes.
- `body.bin`: complete original body when framing completed.
- `MAPPING.json` and `provider-request.bin`: exact complete transformation.
- `response.http.bin`: exact SSE or diagnostic error response offered to native.
- `OBSERVED.json`: completion flag, advertised/observed body counts, timing,
  provider status and whether the socket write succeeded.

On partial-header/body timeouts the observed prefix is retained and
`capture_complete=false`; it must not be described as the whole native request.
For generation preserve `provider/<sha256(request_id)>/` with original
`ADMISSION.json`, `request.bin`, `combined.log`, `model-input.json`, and
`RECEIPT.json`. The adapter verifies the frozen profile/dependencies, namespace
bootstrap, rendered prompt, input tensors and result before producing successful
SSE. Completed generation is a physical-call lower bound; an interrupted or failed
provider can leave actual calls/cost unknown. Do not count missing cost as zero.

Public model assets stay in sealed memfds; the journal does not create one disk
copy of weights per request. Record their existing hashes and shared setup cost.
Socket delivery is not independently authenticated model/owner custody. Keep all
planned arms and failures in any report, and never reuse an uncertain request ID
or replace it with a fresh one to obtain a preferred outcome.
