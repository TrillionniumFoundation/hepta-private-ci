# Guarded Cell owner and ordinary runtime: v8 publication record

This record accompanies the owner/runtime changes in `codex-hepta-agentd` and
`codex-app-server`. It records a bounded actual execution and targeted regressions.
It does not declare a generic Cell proof, consensus activation, production adoption,
external delivery, model-quality qualification, or work-cost qualification.

## Publication scope

A fresh GitHub API check reported `TrillionniumFoundation/hepta-private-ci` as
**public**, despite its repository name. Raw v7/v8 archives contain isolated
authority state and publication-grant material. They were retained on the operator
host and were **not included in this publication or its added Git ancestry**.

The public record contains reviewed summaries, changed-source hashes, and hash
commitments to the retained raw observations. A hash commitment permits comparison
with the original bytes; it does not let a reader independently inspect withheld
bytes. `RAW_COMMITMENTS.json` explicitly marks those archives as unavailable in Git.
Historical grant observations are not authorization for today's use.

Seven code commits are preserved, then integrated with upstream
`7380bddcf3d32046c2b698250a004586df5698de`. The integration tree before
this evidence directory was `f1d191c27206c72c3903908fa32eb17b58c60345`.
All other paths are byte-identical to the previously validated static tree.
The earlier local evidence commit and merges containing that commit are excluded
from the published ancestry, rather than merely deleting an archive in a later commit.

## What changed

- Ordinary generation settlement obtains expected context from its real journal
  owner before dispatch/readback/no-contact settlement and uses
  `commit_with_expected_context`. Guarded failures do not fall back to unguarded commit.
- Typed predecessor reopen reuses the existing identity, Linux boot witness, and
  retained owner state. The coordinator still enforces drain and CURRENT fencing.
- Detached plugin completion no longer retains a closed runtime owner through
  `ThreadManager` or a captured `ConfigRequestProcessor`. It upgrades a Weak owner
  only when actual refresh/exclusive-queue work starts. The lifecycle regression
  first failed against the old implementation and passed after the fix.
- Qualification runners enter through the real arg0/home/bootstrap path and keep
  the original request identity for uncertain readback. The example recovery branch
  has compilation and source review coverage; it was not entered by the successful
  v7/v8 executions.

## Executed source and static source

The v8 tests, example builds, descriptor assembly, and real model execution ran at
local commit `8c8a75c28c1d3f1080faa3b88cc9b06918f8c098`, tree
`f51488912db2470245e7098c703e97b58357adfb`.
Its recorded runtime checkout has 11,172 index entries: 10,196 materialized regular
files, one symlink, and 975 sparse-missing entries. Runtime-view manifest SHA256:
`031c2ae6f160917cf1bd56fe4215857a3bdde42098ed33f373f474b0e577a4bd`.

The later static-gate source was local commit
`b7ebd0491b0745cdbfa5f32824f2397f555a7bf2`, tree
`12e5c196e0c56f69da06d99702c2c3a4e48456f5`.
Only `qualification/module-execution-dossiers/NATIVE_BINDINGS.json` changed after
the runtime execution. Compiled source, scripts, all 21 changed owner/runtime
files, and all previously materialized runtime bytes remained identical.
The complete checkout had 11,171 regular files and one symlink, totaling
151,076,684 bytes. Full-view manifest SHA256:
`554a7cbf1c17534203522487d381b21ee1a5087f9b6f0074c296a4af6725a6f4`.

Those two original local commits are retained as historical source identities;
they are not public Git ancestors because they include the withheld evidence
commit. The public integration retains their actual compiled-source bytes.
`SOURCE_EQUIVALENCE.json` records the exact tree comparison. This is source
equivalence, not a claim that runtime tests ran after the publication commit.

## Actual two-task execution

Profile: `v13-minilm-task-proposal-linux-v1`. The ordinary App Server/Fleet path
executed a real MiniLM encoder plus trained adapter and deterministic admitted
skill worker on CPU. All 27 external asset hashes were checked against frozen
inputs. Task-owner inputs and expected results were fixed independently before
execution, rather than derived from the producer's result.

The fresh v8 isolated run exited 0 in **43.78139567375183 seconds**. Its two
delivered outputs exactly matched the independent owner goldens:

- `sort_numeric ["-23", "8", "42", "107", "107"]`
- `sort_numeric ["-37", "0", "4", "109", "109"]`

Each actual control journal had exactly one Admit, Dispatch, and Result.
Total dispatches were **two**. Reopening the first runtime instance read back
its original receipt/outbox/cost history without redispatch.

The raw FinalUse claims file was 80 bytes: two 40-byte epoch/nonce frames.
An independent audit compared each frame with its signed **publication grant**,
in order and byte for byte. These are not claimed to be per-inference grants.

Both local receiver files were fsynced; both delivery ACKs were committed; both
drained checkpoints had `pending_request_digest = null` and `pending_output = null`.
The checkpoint schema has no `draining` field: drain was asserted through the
actual runner API. The next task used distinct task/run/generation/writer-epoch
identities, advanced CURRENT, and fenced the predecessor.

## Validation and retained failures

| Validation scope | Actual observation |
| --- | --- |
| New v8 agentd integration regressions | Exactly 10 selected, 10 passed |
| New v8 App Server lifecycle regression | Exactly 1 selected, 1 passed |
| Both V13 acceptance examples | Built successfully before actual execution |
| Actual v8 model workflow | Two tasks, exit 0, original-state audit passed |
| Development documentation gate | Exit 0 on the complete static source view |
| Scoped `just fix` | Exit 0; two existing dependency lifetime warnings retained |
| `just fmt`, diff check | Exit 0; zero source-byte changes |
| Post-fix/fmt tests | None |

The earlier generation campaign had 76 unique tests: 71 passed initially and five
Joint helper tests failed because helper metadata was missing. After the actual
helper was built and the correct environment key was supplied, those five passed.
This is not represented as one clean 76/76 run. Nine Python worker tests and the
three earlier plugin-change tests are recorded separately; repeat runs are not
counted as new coverage.

Original failures remain retained: sparse-source compilation, incorrect helper
metadata, the expected red callback assertion, arg0/home startup failure, real
runtime `StateLocked` reopen failure, and a v6 control RPC `CommitUncertain`.
Successful v7/v8 runs used new isolated namespaces; they are not represented
as recovery of the original v6 operation.

The first two v8 documentation attempts failed because the sparse checkout lacked
workflow inputs and then algorithm-spec inputs. The complete exact tracked tree
was subsequently materialized and the final gate passed. Its CNS subordinate
validator executes reference tests; those ran before final fix/fmt. The outer
success report did not expose a subordinate test count, and none is invented.
Its `historicalEvidenceRevalidated` field is false.

## Remaining boundaries

- Reopen occurred inside the same runner OS process, retaining prepared worker
  capabilities and authority owners. Fresh-process, reboot, power-loss, and
  production privilege separation are not qualified.
- Successful v7/v8 stderr was empty; v8 uncertain-readback events were empty.
  Synthetic runtime tests call pending-request/reconcile directly and do not
  exercise the example helper's new CommitUncertain branch. No UNKNOWN
  CURRENT/FinalUse publication fault campaign is claimed.
- Delivery was to local fsynced receiver files. External delivery and production
  model adoption remain unqualified, as do general model quality and work cost.
- The Cell journal binds operation, state, prefix, outbox, and costs. This is not
  a new atomic transaction across CURRENT, artifact, FinalUse, and all other stores.
- This private-owner V13 execution and public Chain native/V3 proof profiles are
  different paths. No public Chain proof was consumed by this owner commit path,
  and actual MiniLM computation was not proven by those public Cell proofs.
- Historical consensus validity uses protocol parent state and consensus time.
  Today's use still requires today's generation, revocation, and FinalUse checks.
  Native seconds, V3 milliseconds, and owner monotonic clock values must not be
  implicitly interchanged.
