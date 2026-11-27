# Ordinary daemon learning: validation and publication

## Result and acceptance boundary

Native Linux validation passed for the combined candidate: **749 agentd library
cases and 163 automation cases**, with **60 and 2 explicitly ignored cases**.
The 83-case focused run is a subset, not an additional 83 unique passes.
The ordinary daemon binary compiled. Production acceptance remains **HOLD**.

This candidate provides concrete checkpoint/stage-owner composition and an
opt-in supervised runtime consumer. It does not assemble real production owners,
Circuit input providers, a trusted Root learning lane or published-generation
recovery in `main.rs`. See [remaining-gates.md](remaining-gates.md) for the exact
missing implementations and call sites. The fixtures do not establish learning
efficacy, independent evaluator custody, production Root custody or a general LLM ABI.

## Exact source identities

- Baseline #5430: `38c95265e8e549ff60fd88e1db5d3bf31b4264e7`.
- Combined code commit: `5530f84e1305c4c86b8be19c4c8765c4340e51db`.
- Combined code tree: `07ec48e7cebe257c1b80ea13f1298bc984b4b6d8`.
- Tested source inventory: `dafefa3c44b2061b7fec0404d1ffbcbc1fb7d39ea2eb9f40d90ae424cfab8037`.
- Maintained source inventory: `d132325a8136cd50eefe4237f61867d9e03923fba30f5cab0b265aca5b534f7c`.

The code tree above is the union of the seven review stages. Each GitHub tree
was checked against its locally reconstructed tree; parents, PR bases, heads
and changed-line counts were read back. The native run validated the complete
candidate before maintenance, not each intermediate review cut in isolation.
This evidence supplement adds documents and receipts only; it changes no code.

## Native execution

Host: `ai395`, Linux x86_64. Rust 1.96.0, just 1.51.0 and cargo-nextest 0.9.103
were pinned. Build jobs were limited to four, CPU to 400% and memory to 32 GiB.
All test execution used the repository's `just test` entry point.

| Gate | Outcome | Exclusions |
| --- | --- | --- |
| Focused learning/Circuit/objective run | 83 passed | 803 skipped or filtered; subset of the full crate runs |
| Agentd full library | 749 passed | 60 explicit ignores |
| Automation all targets | 163 passed | 2 explicit ACT-1 child-process entry points ignored |
| Ordinary agentd binary check | exit 0 | Compile check; no production daemon launch |
| Caller closure | PASS; 6,135 Rust files | `authorityGranted=false` |
| Checkpoint source closure regression | 5 passed | Static boundary regression only |

The seven new `ordinary_delivery_*` tests ran. They include a fresh fixture
iteration through Experience, Dataset, Training, Evaluation, Selection and
NextUse; the initial checkpoint and all six stage checkpoints; real SQLite ACK;
recovery from completed state; missing/partial claimed state; source isolation;
readiness/admission gating; and required-service lifetime. The migration
integration test `v1_store_migrates_atomically_to_dispatch_outcome_schema` ran.

The two complete crate commands were:

```sh
just test --locked --offline -p codex-hepta-agentd --lib --test-threads 2
just test --locked --offline -p codex-hepta-automation --all-targets --test-threads 2
```

The binary check, run from the repository root, was:

```sh
cargo check --locked --offline --manifest-path codex-rs/Cargo.toml -p codex-hepta-agentd --bin codex-hepta-agentd
```

Exact argv, job IDs, elapsed times, source hashes and raw logs for all eight
attempts are in `native/validation.json` inside the archive. Actual PASS names
are preserved in `native/executed-cases.json`; the exact 62 ignored names and
existing binary hashes are in `native/ignored-test-inventory.json`. The ignored
names were enumerated with `--list --ignored`, without executing test bodies.
The three successful test logs contain no retry, failure or timeout event.

Not executed in this native qualification: other workspace crates' tests,
agentd integration-test targets and doctests, Bazel, non-Linux platforms, the
ignored cases, or production training/evaluation/capability provisioning.

## Maintenance and environmental failures

`just fix --locked --offline -p codex-hepta-agentd -p codex-hepta-automation`
exited 0 without changing any source. One non-fatal `clippy::duplicate_mod`
warning remains for the shared checkpoint test-support module.

`just fmt` exited 0 and formatted ten agentd files. The tested source and the
maintained source differ only by that formatter delta. Local and remote
maintained inventories matched. The archive includes `maintenance.diff.gz`,
`maintenance-delta.json.gz` and `local-maintenance-sync.json` with exact bytes
and hashes. **No tests were rerun after fix/fmt**, as instructed by AGENTS.md.

Two earlier builds failed before any test executed. `targeted-v1` exhausted the
remote `/tmp`; later attempts used a task-owned `TMPDIR`. `targeted-v2` lacked
baseline `docs/modules/MODULES.json` due to sparse checkout. That file and the
baseline `qualification/neuron-v13-generation/proposal_worker.py` compile input
were restored from exact #5430 blobs. No Rust change bypassed either failure.
Both failed attempts and their original logs are retained.

## Evidence and report limitations

- [native-evidence.tar.gz](native-evidence.tar.gz): 37 original native evidence
  files plus local synchronization and transfer receipts; all member hashes
  were checked before packaging. SHA-256: `90e887ee0494d2126272924e0329a52bbbcbd2e9c20255cf89a4413d16b1bd2e`.
- [static-evidence.tar.gz](static-evidence.tar.gz): exact caller proof, static
  guard output and execution records. SHA-256: `e0fb03070d72eeb380098ee5aec13d4747c2d7aa235e0de1e4424108b6eaced1`.
- [evidence-index.json](evidence-index.json): machine-readable source and archive
  bindings. [publication.json](publication.json): exact review commits and trees.

The automation JUnit is the real report from its actual nextest output path;
its mtime and 163 case identities were bound to the corresponding attempt.
Earlier focused and agentd JUnit reports were overwritten by later runs after
the collector assumed a different output directory. They are explicitly
recorded as null with the reason. Their full raw logs remain available; no
reports were fabricated and no tests were repeated only to obtain XML.

The native helper is an existing full-package compiler artifact with its binary
SHA and all 21 matching source files recorded in `helper-source-binding.json`.
Environment records contain only explicit build/test variables and required
paths, not the inherited environment or credential material.

These native results are separate from GitHub Actions. PR checks may still be
queued or running when the evidence is posted; draft/open status is not a CI
pass or production acceptance decision.

## Review chain

| PR | Stage | Changed lines | Commit |
| --- | --- | ---: | --- |
| [5452](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5452) | 01_outbox_storage | 292 | `9e43506f938c0119e01635874d53ff7e98706a67` |
| [5453](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5453) | 02_outbox_persistence_tests | 222 | `8d2dc3bec40edeb78561da317b511f3c7c3232bd` |
| [5454](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5454) | 03_checkpoint_composition | 245 | `1f57e7cfd661deca85bd47a673209b7eab0039fc` |
| [5455](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5455) | 04_checkpoint_composition_tests | 479 | `161c198b463ca3a55ff37c16f26d2059c5d405af` |
| [5456](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5456) | 05_delivery_readback | 384 | `05319bbf3f9a9e5fc7bdae02a1a8790d6726aa1e` |
| [5457](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5457) | 06_ordinary_runtime | 448 | `7e2c6d4b8823e7114f8317c8969515e64de27da9` |
| [5458](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5458) | 07_worker_validation | 631 | `5530f84e1305c4c86b8be19c4c8765c4340e51db` |

Every stage is below 800 changed lines. Production implementation stages are
below 500; the final fixture/qualification stage is 631 lines. The chain is
rooted at #5430 and selectively integrates the checkpoint/stage contract from
#5409 and durable delivery components from #5433. It does not merge every sibling
change or reuse sibling validation counts.
