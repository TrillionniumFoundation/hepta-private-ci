# MEM15: native A-exit → fresh C, capture-only process diagnostic

Status: source proposal, **not compiled or executed** at protocol creation.
Base source: `7f6b5b80cf4528aabd44ad2df1a93d7f70e7590d`, tree
`491484a45e05d05d2b72fec472f96405c37decac` (PR #6211).
This new entry does not rescore or modify any MEM12/MEM14 episode, actor, parser,
profile, denominator or budget. It does not reinterpret old MEM13 observations.

## Fixed scope and interventions

This is a process/data-path diagnostic, not a benefit cohort. For each explicitly
scheduled arm, use a new retained run directory, one fixed request ID, a new
fixture owner and one fresh random 128-bit nonce. The owner, its real native
SQLite writer and its live source verifier remain alive across A and C.
The arm names and expected source-read deltas are fixed before any capture:

| Arm | C query | Delivery | Reads before claim | Total C source checks | Expected HTTP requests |
| --- | --- | --- | ---: | ---: | ---: |
| `attach` | `fixture nonce` | Attach | 2 | 4 | 1 capture |
| `reader-off` | absent | no explicit owner context | 0 | 0 | 1 capture |
| `withhold` | `fixture nonce` | Withhold | 2 | 4 | 1 capture |
| `tombstone` | `fixture nonce` | Attach, then rejected | 2 | 3 | 0 |

For tombstone, the parent identifies the target through the original owner before
the baseline read counter is recorded. The fixture issuer commits the existing
native tombstone after C's two retrieval checks and before C's final owner check.
The unchanged bridge must reject the canonical-head mismatch before turn/start.
The owner recovery anchor must advance. Other arms require the anchor unchanged.

`reader-off` does not erase retained A records. Retention-off, replacement and
all other causal contrasts remain unimplemented in this entry. No arm is called
full memory-off: ExplicitContextOnly disables the known Hepta memory/write paths,
but all native file/tool/history bypasses have not been proven closed.

## A and C process contract

1. Parent creates the original native owner/source fixture and source admission.
   No model produces A's record. The random nonce is absent from the fixed prompt,
   query, request ID and filenames.
2. Parent launches a separate copy of its test executable, selecting exactly the
   ignored `episodic_mem15_import_child` entry. A receives only the bounded original
   snapshot on stdin and the owner socket/agent/generation/explicit child-role in
   its cleared environment. It invokes `AgentdClient.import_episodic_snapshot`
   exactly once. The existing RPC/import fences and 2-second control-I/O boundary
   are unchanged. A prints one ack with input SHA-256, PID and native import result.
3. Parent retains stdin, executable hash before/after, stdout/stderr, PID/proc
   identity, start and OS-exit timestamps. Only exit code 0, no supervisor timeout,
   exactly one ack with matching PID/input hash and one active record permit C.
   The returned owner authority/namespace/generation/snapshot digest must match
   the original snapshot envelope and its independently recomputed canonical hash.
   A's 10-second outer process limit does not extend the import RPC boundary.
   An uncertain/lost ack never causes reimport, a new A identity or C dispatch.
   On early supervisor errors, an owned child guard kills only that child and
   attempts background OS reaping; missing terminal evidence still stays UNKNOWN.
4. Only after the OS wait returns does parent start the real `hepta-infer-worker`
   CLI. C has a cleared environment and separate empty process work/home/cache
   directories; it is not in an independent mount/user/network namespace. C's
   stdin is the unchanged public prompt. A's snapshot/ack and evaluator fact are
   not C arguments, environment or stdin. The App Server still uses the retained
   original Agent home; this is explicitly not a proof of model filesystem closure.
5. C receives only the public final-use config: Unix endpoint/UID, verifying key,
   epoch/revocation head and existing 2000-ms issuer timeout. The parent does not
   open C's authority-state owner. The signer remains the existing **public fixture
   key**, whose source bytes are not secret; no production/private-key custody is
   claimed. No production verifier or issuer condition is relaxed.
6. C creates a fresh durable journal and fresh native thread. Withhold calls the
   existing delivery-bound driver; changing delivery under a retained request ID
   remains an admission-digest conflict. The CLI rejects Withhold without a
   nonempty query or together with any intelligence-binding argument before it
   opens an authority/journal. Default Attach behavior is preserved.

The importer, C and root run directories are exclusive-create no-reissue fences.
No child attempts are retried. Child timeout/signal, absent ack, missing adapter
receipt or interrupted supervisor remains unresolved; retain original owner,
native journal, PID/start identity and operation identity for readback. Killing an
owned child on timeout is not rollback. Physical calls are never inferred as zero
from an error or missing generation response.

## Capture binding and budgets

Only `HEPTA_MEM_NATIVE_PHASE=capture` is accepted by this entry. The independent
wrapper must freeze and retain the Python adapter PLAN, SERVER endpoint, exact
source/profile/request pins and intent **before** starting the Rust entry. The
adapter must be in capture mode; Rust's phase flag alone is not a zero-model proof.
All HTTP bytes, the complete JSON-body → single-user-input mapping and capture
receipt must be joined to this request identity. For the three HTTP arms, only an
observed complete request and adapter `CAPTURED_WITHOUT_GENERATION` support zero
model generation. For tombstone, retain adapter no-request termination, native
revocation rejection and original journal. Missing cross-process evidence is
UNKNOWN, never a scored success or an excuse to repeat the request.

Keep native full body unchanged: no deletion of instructions/tools/metadata and
no nonce extraction. The existing provider 1024 input-token / 32 output-token
caps remain untouched. Token-only preflight, if separately scheduled, must use
the pinned tokenizer and exact existing chat template without model weights or
`generate`. An over-budget request is an admission failure, not a memory-benefit
negative. A different budget would require another frozen protocol.

Original timing limits remain: owner-control 2 seconds, fixture issuer 2-second
client timeout and 30-second only-claim task, worker driver 180 seconds and current
nextest watchdog (normally 60 seconds). The outer C supervisor is 180 seconds;
the nextest watchdog can therefore stop the harness first. Such interruption is
not a terminal result and does not authorize retry. Precompile before starting
the bounded single-connection adapter so compile time cannot consume its window.

## Commands and evidence

Build the existing `codex` and `hepta-infer-worker` executables and precompile the
Agentd lib tests through repository `just` recipes before binding the adapter.
The new test filter is:

```text
production_composition::tests::episodic_control::provider::process::episodic_native_a_exit_capture
```

The wrapper supplies the existing retained native environment:
`HEPTA_LOCAL_PROVIDER_BASE_URL`, `HEPTA_LOCAL_PROVIDER_MODEL`,
`HEPTA_MEM_NATIVE_SOURCE_SHA`, `HEPTA_MEM_CONTEXT_REQUEST_ID`,
`HEPTA_MEM_CONTEXT_RUN_ROOT`, plus phase `capture` and one fixed intervention name.
Each arm gets a different predeclared request ID and exclusive output directory.
Execute exactly one ignored test through `just test` with the exact filter, using
the frozen source. Do not select all ignored tests: A's child entry is parent-only.

Retain root INTENT/DISPATCH_INPUT/RESULT/FIXTURE_AUTHORITY, public config, A_ACK,
A/C INTENT/STARTED/EXIT, raw stdin/stdout/stderr, native C.journal and thread,
original SQLite owner/WAL, source admission and recovery cuts, adapter PLAN/SERVER,
raw request/header/body/mapping/capture receipt and supervisor terminal records.
The process result deliberately leaves physical request/generation counts null
until those independent originals are joined. Do not publish private owner data
in an unreviewed public archive.

Software controls added: CLI rejects ambiguous Withhold combinations; A exact
input/PID/OS-exit binding rejects changed input, wrong process, timeout and failed
exit; missing or duplicate ack cannot start C. These are software checks, not
model episodes. Rust compilation/execution and final formatting are delegated to
the single native qualification checkout and must be reported on its exact final
source bytes. Scientific acceptance stays **HOLD** for natural tasks, deployment
authority, complete bypass isolation, causal memory benefit and weight changes.
