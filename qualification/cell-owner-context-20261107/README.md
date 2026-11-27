# Cell owner context: native seam and validation record

This change adds a request-bound context seam to the existing
`CellGenerationJournalV2`. It does **not** add a native verifier for Chain's full
Cell relation, connect Python proofs to Agentd, grant FinalUse, or establish that
a model was used. The existing journal, CURRENT, witness and operation identity
remain the owners of their respective effects. Receipts remain `DENY_ALL`.

The source is based on private integration commit
`066cb16c47b0e4dbc561d56fe7746dea98a479d8`, tree
`e41ef532cdf0ca05952ef42170e7628d19b1c16d`. The first native build used local
`7a2adbde9298a6bd4aaf5b0a743dc1b9839fe9ee`, whose tree
`97f68efe160e20e61fc4dbcd2ec350d93acdee2f` is identical to upstream
`09db432b6eb81e0b209986f14e3a958937cec8bd`. The subsequent integration change
affects only `codex-rs/cli/tests/exec_server.rs`; all five proposed source files
were retained byte-for-byte when composing the newer base. The 18-test CURRENT
run below used the newer base.

## Independent expected context

`CellGenerationExpectedContextV1` has private fields and no public constructor,
wire representation or deserializer. Consumers obtain it from their own guarded
journal's actual durable admission. They cannot supply a producer contract to
the export method and turn that contract into an expected context.

The snapshot retains the complete existing configuration and manifest; actual
request input, task, source frontier and deadline; predecessor state, scope,
generation and writer epoch; durable continuity checkpoint; and guarded owner
binding. Its trust is limited by the same host Current and witness ports as the
existing journal. It does not authenticate a producer or validate computation.

| API | Boundary enforced |
| --- | --- |
| `pending_expected_context()` | Read an actual pending durable admission; reject unguarded, idle, unhealthy or retired owners. Cold replay can produce the same context. |
| `require_expected_context()` | Recheck the current owner, complete configuration, original pending request and exact continuity checkpoint. Any intervening durable event invalidates the pending cut. |
| `commit_with_expected_context()` | Recheck the owner and request, then use the original journal commit. Fresh work requires the exact pending cut. An exact committed operation/proposal reads back its original receipt without another append; conflicts fail. |

The commit method accepts no producer-supplied verification-success boolean.
Callers still need a real computation verifier and their existing current-use /
FinalUse dispatch boundary. This method does not create an atomic transaction
spanning CURRENT, FinalUse and journal owners. Lost acknowledgement recovery
retains the original operation identity, and never creates a replacement
admission to hide uncertainty.

## Two time domains remain separate

Hepta admission, dispatch observation, settlement and request deadlines use the
host's monotonic microsecond lane. The new seam passes that lane to the existing
journal; it does not reinterpret it as Unix time or consensus time.

Historical Chain consensus must be checked against protocol-selected parent
state and consensus time. Current actual use must check current authorization,
revocation and generation through the existing host boundaries. Later revocation
must not rewrite a historical consensus verdict. This change neither supplies
a historical Chain validator nor substitutes current owner checks for one.

## Executed native mechanism tests

The five new tests use the existing file journal, actual file witness, CURRENT
owner and signed publication mechanisms. Proposed computation results are
explicitly synthetic test inputs. No successful verifier mock or claimed model
execution is used.

| New test scope | Observation |
| --- | --- |
| Durable admission and producer substitution | Input, task, source, deadline, generation, writer epoch, scope, before-state and operation substitutions fail without journal/witness mutation; unguarded export fails. |
| Exact checkpoint and replay | A durable dispatch observation invalidates an older cut; a current cut commits; replay and cold readback return the original receipt; a conflicting proposal fails. |
| Cold pending recovery and cancellation | Cold replay reconstructs the same pending context; cancellation invalidates the old cut and retains the existing cancellation/state rules. |
| Foreign task and real generation replacement | A foreign task owner cannot use the snapshot. Actual signed CURRENT publication fences the old guarded journal, including receipt readback through the commit seam. |
| Witness acknowledgement loss | The real witness CAS persists before an injected lost acknowledgement. The live handle becomes uncertain; cold recovery reads the exact original commit without another append or FinalUse nonce claim. |

The first successful selected run executed **5 tests, all passed, 720 skipped**.
After local integration onto the latest base, the CURRENT group executed
**18 tests, all passed, 707 skipped**. The 18 include the same five new tests;
these are not 23 distinct test cases. The group also exercises existing signed
publication, withdrawal/expiry and lost-publication-acknowledgement behavior.

The successful commands used the repository's `dev-small` Cargo profile,
`CARGO_INCREMENTAL=0`, one Cargo build job, the default product features and the
repository `just test` runner. These are resource-constrained developer test
results, not an unqualified pass for the default build profile, whole Agentd
package, target-host custody or release qualification.

```bash
just test --locked --offline --cargo-profile dev-small --lib \
  -p codex-hepta-agentd -E 'test(expected_context)'
just test --locked --offline --cargo-profile dev-small --lib \
  -p codex-hepta-agentd -E 'test(neuron_generation_current)'
```

## Opened-inode transport across PID namespaces

The complete neuron package was also exercised with an actual
`hepta-joint-propose` executable built from Cargo's compiler-artifact metadata.
The pinned helper is 814,360 bytes, SHA-256
`4bec67f0332a6abcefbfdf21beb25ab6b47e7ec2bd80872db5077cbf6cb73a76`.
Its source modules were unchanged by the caller-side transport repair.

Before that repair, the full package executed **174 tests: 167 passed, 7 failed,
0 skipped**. Missing helper metadata had been resolved; four Joint process
tests and three V13 process tests then exposed actual transport failures.

Independent probes established that `getpid()` was in an inner namespace while
the mounted `/proc` presented outer PIDs. The original `/proc/<getpid>/fd/<fd>`
path did not exist and spawning it failed with `ENOENT`. The same executable,
argv, environment and limits worked when the procfs-visible owner was used.
The opened descriptor and resolved proc path retained the same device/inode
and executable hash.

The two transport call sites now share one Linux-only helper that reads
`/proc/self`, accepts only a bounded positive ASCII PID component, and constructs
the held parent's fd path in that procfs view. The parent keeps the opened file
through child termination. There is no fallback to a replaceable executable
pathname, no permission bypass, and no change to argv, environment, descriptor
inheritance, pipe limits or test assertions.

With this substantive fix, the same complete neuron package executed
**174 tests: 174 passed, 0 skipped**, using the same pinned real helper. The
earlier 167/7 result remains a failed baseline; it is not reclassified as a pass.

```bash
just test --locked --offline --cargo-profile dev-small -p codex-hepta-neuron
```

After the transport repair, the final CURRENT regression again executed
**18 tests: 18 passed, 707 skipped**, including all five new context tests.
Its first rebuild ended with compiler SIGKILL before tests ran; the successful
retry used the same source, assertions, profile and feature selection after
task-owned temporary storage was reduced. That failed build remains recorded.

| Final check | Observed result |
| --- | --- |
| Complete `codex-hepta-neuron` package with real helper | 174/174 passed, zero skipped |
| Selected Agentd CURRENT group after the repair | 18/18 passed, 707 unrelated tests skipped |
| `just fix -p codex-hepta-neuron --locked --offline --profile dev-small` | Exit 0; no source rewrites |
| `just fmt` | Exit 0; final layout recorded separately |
| Workspace preflight | Exit 0; 194 local manifests, zero errors |
| Development documentation preflight | Exit 0; development profile passed |

See [validation-summary.json](validation-summary.json) for every attempt,
[source-manifest.json](source-manifest.json) for final formatted source hashes,
and [evidence-index.json](evidence-index.json) for exact raw-record identities.
Large compiler streams and cache inventories use gzip with their original-byte
hashes retained. Empty or truncated original records are preserved as observed.


## Failed and incomplete attempts are retained

The initial default-profile neuron library run executed 174 tests: 165 passed,
9 failed. Six reported missing actual `hepta-joint-propose` helper metadata;
three existing V13 process tests failed their process-observation assertions.
This run was not recorded as a passing package gate.

The first selected Agentd build exhausted the overlay filesystem. Several
`dev-small` attempts then exhausted temporary filesystem space before any new
test executed. One result could not be written after the log filled: its child
exit code and elapsed time remain unknown. Another attempt ended with compiler
SIGKILL; contemporaneous memory counters indicated memory pressure, but no
agent issued a process-kill command. These infrastructure failures are not test
assertion failures. The later passing runs do not erase them.

The real helper preparation also has an initial ENOSPC attempt: helper Python
exit 120 and outer recorder exit 1 were observed, while Cargo's own exit code
was not retained. Its compiler JSONL is truncated. These unknowns remain explicit
in the observation record.

Only this task's own rebuildable caches were reclaimed. Completed archives were
also copied, hash-checked and retained with symlinks at their original Cargo
paths to split storage pressure. No shared source or other workspace cache was
deleted. Resource receipts preserve the scope of these operations.

## Evidence and remaining scope

The adjacent evidence index records original raw log and receipt hashes, command
arguments, source-input hashes, profile changes and incomplete records. A pinned
native test executable and the actual helper's compiler identity are recorded
without treating either as a model proof.

Runtime tests precede `just fix` and `just fmt`, following `AGENTS.md`; they are
not rerun after those steps. Final formatting and source changes are identified
separately from the inputs of each executed command.

Native relation verification, proof-to-owner composition, external task-owner
authentication beyond the existing ports, production independent custody,
whole-stack acceptance and actual later model use remain outside this seam.
The change adds no new consensus work entry point and no new authority grant.
