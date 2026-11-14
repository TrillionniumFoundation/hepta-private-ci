# Current evidence relay: source and local qualification

**Hosted update, 2026-10-25:** the successful run is audited below and in [hosted-result.json](hosted-result.json). Earlier sections preserve the local qualification before hosted execution.

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

## Hosted execution and artifact audit

[Run 40186181816](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40186181816), attempt **1**, executed exact commit **`2fa2bd674fc2187bcf7019fe31f0dd19f1164613`** on `codex/memory-current-relay-20261025`. The final API observation at 11:00:09 UTC confirms every step succeeded in source-owner job **121147337806** and target-worker job **121147337605**. Five source/workflow files fetched at that commit match the formatted publication copy. The pre-format local test result remains separate.

All **eight downloaded ZIPs** match authenticated API SHA-256 and byte lengths. Independent standard-library/cryptography analysis completed **65 artifact consistency checks**: five Ed25519 envelopes, six exact sender/receiver/artifact byte comparisons and transfer receipts, canonical hashes, actual SQLite state, placement frontiers and callback counters. No model, training or product test was rerun. The finished object uses exact-run artifact authentication and stable target identity; it is not an Ed25519 envelope.

### Actual positive evidence and withdrawal

| Transition | Observed result |
| --- | --- |
| Granted current source | `remote/source_00`, revision 0, `remote_00` → `red`, epoch **3**; **172 canonical bytes**, hash equal to the granted root |
| First positive delivery | Target verifies root/scope/epoch/identity/bytes and signs the exact evidence acknowledgment; callbacks **33 → 33** |
| Source confirms acknowledgment | **Second actual source read**, identical evidence and epoch-3 snapshot, exact acknowledgment bound |
| Actual source mutation | Source DB advances **3 → 4**, revokes the granted root at epoch **4**; signed withdrawal binds acknowledgment and current confirmation |
| Later duplicate evidence | Withdrawal-bearing copy refused as current support; the earlier positive delivery remains accepted |
| Withdrawal inference | `withdrawn inference source`, callbacks **33 → 33** |
| Fresh-owner old-cut replay | `withdrawal frontier rollback or same-epoch fork`, callbacks **33 → 33** |

Archived SQLite independently contains the epoch-3 completed training job and exact snapshot, actual epoch-4 withdrawal, and queued epoch-4 training job. Target durable fences contain epoch **4**, the withdrawn root and counter **33**. Both source placement refusals retain counter **3 → 3**. The checkpoint remains retained: this proves withdrawal enforcement, not parameter erasure.

Causality requires the recorded sole-writer, monotonic-epoch and no-volume-rollback assumptions. The exact acknowledgment precedes actual revocation while the source snapshot remains identical; synchronized clocks and online target authority are not used.

### Runner, checkpoint and raw model result

Source runner `GitHub Actions 1000233653` and target runner `GitHub Actions 1000233643` have different job and boot identities; full boot hashes are retained in [hosted-result.json](hosted-result.json). Both hostnames are `runnervmwhx2h`. This establishes separate runner/VM environments without physical hardware attestation.

The **1,891,499-byte** adapter/configuration/lineage package is identical in the signed offer, original source publication, source worker and target checkpoint. Target has no `sources.sqlite`; decoder reads finish before source-evidence transfer. All read journals record no fact/retrieval/answer-lexicon input or answer postprocessing; raw-row evidence is empty.

| Decoder condition | Raw accuracy | Behavior |
| --- | ---: | --- |
| Source adapter | **3/3** | `red`, `green`, `orange` |
| Source base | **0/3** | Repeats each question |
| Source shuffled adapter | **0/3** | Repeats each question |
| Target adapter | **3/3** | Exact source-adapter text, token IDs and prompt hashes |
| Target serial load | **32/32** | Same three questions repeated **11 / 11 / 10** times |

The **36 successful decoder processes** are three source batches of three questions, one target batch of three, and 32 single-question processes. Training also succeeds. All 44 answers were not individually cold-started. Repeats do not add future tasks: **0** independent future tasks, future accuracy **null**, no strong-retrieval comparison.

### Measured costs and boundaries

The unchanged rank-8, seed-2718, learning-rate-0.001 recipe executed **256 actual forwards/updates**, **17,345 input tokens**, **512 supervised tokens**, and fact visits **85 / 85 / 86**. Training reports **81.884683 s**; its complete child takes **87.923642 s**. Safetensors-header analysis confirms **120 F32 tensors, 460,800 parameters, 1,843,200 tensor bytes**. Gradient and optimizer records add 1,843,200 and 3,686,880 bytes; these omit base, activations and runtime.

| Cost observation | Value |
| --- | ---: |
| 32 serial cold requests, concurrency 1 | **220.360354 s; 0.145216685 requests/s** |
| Nearest-rank p50 / p95 request wall | **6.859046 / 6.991547 s** |
| Source prepare wall / CPU | **112.413621 / 199.837886 s** |
| Target read phase wall / CPU, including artifact wait | **427.978045 / 248.494016 s** |
| Largest individual child peak RSS, source / target | **1,286,684,672 / 1,143,451,648 B** |
| Two separately inventoried base copies | **542,342,300 B** |
| Final source / target evidence, uncompressed file lengths | **6,598,614 / 4,833,857 B** |
| Two bases plus final evidence file lengths | **553,774,771 B** |

The p50 is sorted observation 16 of 32; the usual two-middle-value median is **6.860377985 s**. Cold wall includes startup/loading; it is not pure generation latency or concurrent throughput. Aggregate peak RSS is unmeasured, so individual peaks are not summed.

All **178 evidence-inventory entries** match final archives. Final totals add four later source files (**14,884 B**) and target inventory itself (**21,329 B**). Bases are inventoried, not included/rehashed in these ZIPs. Logical file lengths omit full dependencies/caches, base-download/TLS/upload traffic and CI billing. Net compression and equal-quality total-budget advantage remain unproven.

### Retained receipts and status

[hosted-result.json](hosted-result.json) preserves eight artifact identities/hashes/sizes/expirations, signed causal receipts, source hashes, costs and limits. Source/target ZIPs (**5,335,101 / 3,714,006 B**) expire on **2026-11-08**; none is added to Git.

The missing **positive current remote-evidence handoff before actual withdrawal** is now demonstrated for authenticated same-run artifact relay. Online/replicated authority, physical-node attestation, partition/quorum recovery, production admission, unseen-task superiority, matched-budget split gain and net compression remain outside this trial. Its full research gates closed count remains **0**.
