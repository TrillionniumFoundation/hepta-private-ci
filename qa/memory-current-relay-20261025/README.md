# Current evidence relay: source and local qualification

## Status

The positive remote-evidence handshake is implemented in new modules and a new two-job workflow. The final local control suite passed **11/11 tests, zero skips**, with 79 scoped source/dependency/workflow files unchanged during execution. Those results belong to the retained **pre-format execution bytes**. A later isolated `just fmt` changed four Python files; their location-free Python ASTs remain identical. The formatted bytes were not retested locally. No local model training or decoder invocation was performed for this extension. An independent agent reviewed the current source and found no required source changes.

**This is local control qualification and a runnable hosted experiment, not a completed hosted result.** The parent will publish the source, trigger the branch, retrieve actual artifacts and decide the hosted outcome. The original experiment's scientific recipe remains frozen.

## Reviewable stages and exact files

The execution layout had 448 Python changed lines. Actual formatting expands the runner to 346 lines, contract to 134 lines and tests to 280 lines; the whitelist diff is eight additions and one deletion. The minimal complete-code publication split is: implementation 489 changed lines (runner + contract + whitelist), tests/workflow 456 changed lines (280 + 176), and a separate small qualification-document stage. These counts use the actual formatted source; no compressed pre-format line count is presented as the publication diff.

| File | Role |
| --- | --- |
| `scripts/memory_cell_distributed/relay_current_contract.py` | Signed readiness, evidence and acknowledgment validation; exact root, scope, epoch, source/target identity, bytes and envelope hashes |
| `scripts/memory_cell_distributed/relay_current.py` | Real source reads and revocation, acknowledgment choreography, legacy target withdrawal/restart composition, report |
| `scripts/memory_cell_distributed/relay_current_tests.py` | Eight control tests with actual source store transitions and explicit artifact/identity fixtures |
| `scripts/memory_cell_distributed/relay_protocol.py` | Only adds `current-evidence` and `current-ack` to artifact stage whitelist |
| `.github/workflows/hepta-memory-current-relay.yml` | Parallel source-owner and target-worker hosted jobs; six artifact exchanges |

All five file SHA-256 values and byte/line counts appear separately as `executed_source` and `formatted_source` in `local-qualification.json`. Its `publication_formatting` section records the formatter receipt and each Python AST digest. The existing `relay_trial.py`, `relay_evaluate.py`, `artifact_relay.py` and original workflow match HEAD bytes. The `PROTOCOL` AST is unchanged. No Rust source was changed for this extension; the earlier NDU work remains frozen under parent control.

## Actual causal construction

1. The source executes the original preparation recipe: new random three-fact assignment after pinned checkout, 256 training updates, rank 8, learning rate 0.001, seed 2718, adapter/base/shuffled source reads, original placement fencing and checkpoint offer.
2. The target executes the original target read: initial three-query decoder call and 32 serial cold one-query requests. It then creates a private Ed25519 key outside uploaded evidence, binds the signed ready envelope to its actual recorded runner identity and exact evidence request, and uploads that signed ready artifact.
3. The source downloads and verifies ready. It preserves the original post-ready former-placement refusal. It reads the exact granted root through `SourceEvidence.dispatch`, which checks the live source head, scope, epoch, conflicts, withdrawal and canonical payload hash. Full source snapshot equality is checked around this read. It uploads a signed current-evidence envelope bound to the offer, signed ready envelope, target public key, source snapshot digest and frontier.
4. The target verifies the source signature and same-run provenance, exact root/scope/epoch/placement and source actor, payload size and bytes. It signs an acknowledgment over the exact canonical evidence envelope hash, ready hash, source snapshot hash, manifest, request, root, epoch, payload hash and byte count. It records that acceptance uses the delivered cut and that no model callback occurred after evidence receipt. It uploads the signed acknowledgment.
5. The source receives that exact acknowledgment, verifies target signature and actor, and checks that the confirming source is the same runner/job as the offer. It reopens the real source and performs a **second actual current evidence read**. The source snapshot must still equal the snapshot sent earlier, and the resulting evidence must exactly equal the earlier evidence. It durably retains `source-ack-current.json` before mutation.
6. Only after this check does the source actually call `MemoryService.revoke("remote/source_00", 0)`. It requires epoch advancement by one and the granted root in the actual revoked frontier. It records the real transition and publishes a signed withdrawal bound to both the exact target acknowledgment hash and the source-current confirmation hash.
7. The target executes the unchanged withdrawal refusal, verifies the causal acknowledgment link, and starts the unchanged fresh-owner old-cut replay refusal. The resulting finished artifact carries those links. The source combines the original evaluator with the new causal checks, including finished provenance and stable target runner identity.

The causal claim requires the explicitly recorded assumptions: the workflow is the sole source writer, source epoch advances monotonically and source volume is not rolled back. Under those assumptions, equality of the source snapshot before evidence delivery and after receipt of the exact acknowledgment means the target's intervening acceptance happened before the subsequent withdrawal. This argument does not depend on synchronized clocks.

Target acceptance is not an online source-authority query. The signed source cut travels through authenticated artifacts, and source currentness is confirmed causally afterward. GitHub Actions exact-run artifact authentication is the trust origin for the ephemeral source and target public keys; self-signatures alone are not an identity proof.

## Two evidence deliveries must remain distinct

The first `current-evidence` artifact is accepted under the delivered signed cut **before the source confirms its exact acknowledgment and revokes**. The later withdrawal artifact also carries a copy of those source bytes for the existing delayed-evidence refusal check.

The frozen legacy receipt field `evidence-refusal.reason = "source withdrawn before delivery"` describes **that second, withdrawal-bearing delivery**. It does not describe the first accepted delivery. Keep this distinction in the final hosted report; do not summarize the trial as if the positive evidence step never occurred, or as if the later withdrawn bytes were accepted.

## Local verification and retained failures

The final local run is `relay-current-tests-004`; its compact receipt, source hashes, runtime origins and output hashes are embedded in `local-qualification.json`. Full run receipts/logs remain in the working-session control directory. It started at 2026-10-25T10:38:58.419122Z, exited 0, and reported 11 passed tests. The eight new tests cover:

- Correct canonical bytes and exact root/scope/epoch; valid signatures do not excuse mismatched content or source actor.
- Acknowledgment signature, exact envelope, root/epoch, target actor and run binding.
- Readiness runner identity and exact authorized evidence request.
- Wrong acknowledgments and wrong source owner do not advance the actual source.
- The actual source accepts the correct acknowledgment while current, records it, then actually revokes.
- An intervening source correction prevents confirmation and withdrawal.
- Both new artifact stage names retain exact ZIP member/digest admission and reject traversal paths.

The three existing contract tests still pass: cross-run/signature replay rejection, exact artifact digest/member admission, and durable RPC reservation accounting.

Local artifact delivery, runner identities and the target's prior callback count 33 are explicit fixtures. Actual source writes/corrections/revocation, source evidence reads, signatures and source placement refusal execute real code. The 33 target callbacks and actual hosted artifact delivery remain to be measured by the workflow.

Earlier attempts are preserved rather than overwritten:

| Attempt | Actual outcome |
| --- | --- |
| 001 | New module import failed because cryptography was absent; no new test executed |
| 002 | Four earlier-source tests passed in the shared model runtime after the package addition; superseded by 004 |
| 003 | Three old contract tests passed; new suite import failed because frozen tensor_contract imports torch eagerly, absent in the crypto-only venv |
| 004 | Eleven tests passed with explicit, recorded dependency origins; final source freeze |

The workflow also passed static PyYAML parsing, branch/two-job/permissions/pinned-action checks, and six unique artifact names with exact JSON basenames. This is not GitHub server validation or hosted execution evidence.

## Runtime provenance and disclosed change

Before the parent requested a separate runtime, a completed `uv pip install` into `/tmp/hepta-memory-resume-runtime` added `cryptography==50.0.2`, `cffi==2.1.1` and `pycparser==3.12`. No removed or replaced packages were reported, and no rollback was performed. The parent was immediately notified. Exact command start time was not captured; observed INSTALLER mtimes place the addition around 2026-10-25T10:33:34.913586Z–10:33:34.915606Z. `relay-runtime-addition.json` records those limits and hashes. The preceding `python -m pip` attempt failed because pip was absent and made no package changes.

Subsequent commands did not modify that shared venv. A separate `/tmp/hepta-memory-current-relay-runtime` was created. The isolated-cache network download was denied by the sandbox; installing the pinned cryptography package and its two dependencies into the new venv from the existing uv cache with `--offline` succeeded.

Because the frozen source stack imports torch at module import time, final test 004 explicitly places the separate cryptography site-packages first and reuses the shared model site-packages only as an import path. `runtime.json` records sys.path and actual cryptography/torch module files and versions. No additional model package install, model run or training was performed.

## Formatting bridge and checkout isolation

Formatting ran only in `/workspace/scratch/12ef9c5bdc23/hepta-relay-publish-20261025`, based on exact `ba32a22de7c586ae6a1ac6ebeb5d67b54259021b`. Ordinary shared clones could not traverse missing promisor history from the shallow source repository. The replacement used a new local Git repository, a read-only object alternates path and the original shallow boundary; no remote was configured or fetched. Sparse checkout contains scripts, tools, workflows and root configuration. The main repository's seven copied deliverables were verified unchanged.

`just fmt` exited 0 at 2026-10-25T10:43:31.962343Z using the frozen project Ruff 0.15.13 in the separate `/tmp/hepta-current-relay-format-runtime`. It reformatted only the four expected Python files. The workflow and qualification files were unchanged by the formatter; Ruff also created normal Git-ignored cache files. No Rust checkout, source edit, build, fix or test was involved. The format-scope inventory retains those generated cache paths separately from source changes.

For each Python file, `ast.dump(ast.parse(source), include_attributes=False)` is exactly equal before and after formatting. This is a source-equivalence bridge with source hashes on both sides, **not a second executed test result**. The report explicitly records zero tests after formatting, as required by repository guidance. Documentation was then updated only in the publication checkout to describe this distinction.

## Publication and remaining limits

The workflow push trigger is **`codex/memory-current-relay-20261025`**; workflow_dispatch is also declared. The parent alone performs remote Git publication and triggers the workflow. This agent performed only the authorized isolated local checkout setup and `just fmt` described above; it performed no remote Git writes, Rust builds, fix, post-format tests or hosted run.

Source and target raw evidence remain downloadable Actions artifacts with 14-day retention. Preserve a detailed hosted report and compact receipts in Git; avoid adding another large raw archive. The existing 256-update recipe and raw adapter/base/shuffled quality outcomes must remain visible, including negative outcomes.

This work does not establish online or replicated authority, direct cross-host mTLS, physical hardware attestation, partition/quorum recovery, production admission, future-task superiority, matched-budget split gains, or net compression. The report explicitly keeps those claims false or unqualified, independent future tasks at zero, future accuracy null, and full research gates closed at zero.
