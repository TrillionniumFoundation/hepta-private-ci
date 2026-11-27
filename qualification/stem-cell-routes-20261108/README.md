# Trainable Cell routes: implementation and engineering evidence

This change supplies an executable shared semantic route, a private stateful
temporal route, and deterministic components behind one experimental lifecycle
interface. It extends the existing native bundle/update contracts without
replacing the native daemon or authorizing production adoption.

The engineering probes below passed on the preserved source snapshots. They do
not select a universal Cell kernel, qualify a production model, or establish an
advantage over deterministic solutions. The HCSN formal study is separate; this
change starts **zero HCSN formal fits**.

## Implementation

| Area | Implemented behavior | Boundary |
| --- | --- | --- |
| Shared semantic route | One backend per complete frozen binding; compatible batching; optional frozen domain projection; private linear or low-rank head; MSE and cross-entropy candidate training | The actual provider measured here is a small Llama language model, not a VLM or a production language-quality evaluation |
| Temporal route | GRU default; simple diagonal SSM comparator; original PRED-1 BPTT/Adam; independent candidate parameters and optimizer state | The diagonal recurrence is not S4D or Mamba; HCSN remains an explicitly unadmitted research selection |
| Deterministic route | Exact retrieval, bounded rules, numerical algorithms, explicit host-injected tools | No neural training is required; tool authority is supplied by the host |
| Common owner | SQLite intent/receipt/state persistence; replay; checkpoint, restore, candidate adoption and rollback; bounded histories and recovery | This Python owner is an experimental integration implementation, not the daemon's production state owner |
| Native gate | Complete bundle validation, immediate lineage, route-specific local update scopes, and the existing sealed Reset plan | Host policy supplies the family; a candidate cannot authorize a broader scope by declaring its own family |

The owner distinguishes its lifecycle epoch from the native bundle generation.
Unknown effects are never redispatched. Readback preserves the original request,
identity, budget and measured cost; unknown cost stays unknown. An effect that
completed over budget retains its resulting state and requires explicit recovery.
Persisted global and per-partition capacity limits stop new allocations while
permitting settlement and replay of existing work. Old evidence is not deleted to
make a quota appear available.

Candidates carry their actual parameter/configuration commitments. Shared-base,
encoder, tokenizer, domain-adapter, numeric and state-semantics changes cannot
pass as ordinary private-head updates. The checks compare commitments; they do
not authenticate arbitrary remote tensor semantics or evaluator authority.

## Route A: actual shared-model measurement

The retained run used an Apple M5 with 32 GiB unified memory, Python 3.14.3,
MLX 0.31.1, mlx-lm 0.31.2, NumPy 2.4.2 and Transformers 5.5.4. The public model
was `mlx-community/SmolLM-135M-Instruct-4bit`, pinned to revision
`642e06afe3fab57fd6cc518637c471af0a569e1e`. All downloaded files were rehashed
before loading. The weight file SHA256 is
`e91560ee24b13eee6ddeb14879d728a90780053d69057b15ff199ccadfcfe33b`.

The model was loaded once. All 30 transformer layers and the final RMSNorm ran;
the final valid token supplied a 576-dimensional normalized feature vector. Four
Cells shared that backend and owned four independent, nonzero heads. Each Cell
received two of the eight declared fixture inputs. Three interleaved rounds
compared separate Cell calls with one compatible batch on the same loaded model.

| Round | Separate total wall | Batch total wall | Separate encode wall | Batch encode wall | Separate parameter guards | Batch parameter guards |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 267.611 ms | 66.610 ms | 59.467 ms | 14.884 ms | 208.001 ms | 51.663 ms |
| 2 | 234.766 ms | 68.630 ms | 29.016 ms | 17.117 ms | 205.594 ms | 51.446 ms |
| 3 | 236.451 ms | 68.361 ms | 29.669 ms | 16.844 ms | 206.620 ms | 51.452 ms |

The maximum absolute feature and head-output differences were **0.0 in all three
rounds**, verified again from the retained arrays. Encoding includes tokenization,
the full transformer, synchronization and postprocessing. Total wall includes
complete parameter-value SHA guards before and after encoding. Much of the total
wall reduction comes from running those guards once per batch instead of once per
Cell. These three rounds do not establish a universal GPU speedup or a confidence
interval.

Each of the four private candidate heads completed 64 genuine SGD updates on the
declared fixture MSE objective. Loss changed as follows:

| Cell | Source loss | Candidate loss |
| --- | ---: | ---: |
| 0 | 0.343498 | 0.053065 |
| 1 | 0.353376 | 0.027231 |
| 2 | 0.359123 | 0.003344 |
| 3 | 0.375181 | 0.063492 |

The shared parameter fingerprint, all active head digests, private states and
retrieval views stayed unchanged. Each candidate has a different head commitment
and an immediate successor bundle; the serving probe did not adopt candidates.
This validates local parameter updates, not language-task generalization.

| Memory/cost measure | Observed value | Scope |
| --- | ---: | --- |
| MLX peak active allocation | 119,981,920 bytes / 114.4 MiB | Allocator high-water from provider initialization, including loading and probe |
| MLX active allocation at end | 78,111,368 bytes | MLX allocator only |
| MLX cached allocation at end | 16,729,440 bytes | Reported separately from active allocation |
| Process maximum RSS | 284,082,176 bytes / 270.9 MiB | macOS high-water sampled before final evidence serialization; not an incremental estimate |
| Four private head arrays | 36,928 bytes | NumPy array storage only |
| Load/freeze/synchronize window | 80.578 ms | Excludes download, earlier file hashing and some import overhead |
| Measured probe execution wall / process CPU | 2.476307 s / 1.959102 s | Includes warmup and training; excludes top-level imports and final archive serialization |
| Energy | Unmeasured | `null` in retained receipts |

The configured 384 MiB MLX memory setting is an allocator guideline, not a hard
RSS limit. There was no experiment with four separately resident model copies,
so this evidence does not quantify memory saved against that alternative. The
pool's host-array report cannot see MLX allocations; the provider's counters are
the distinct source for the measured Metal values.
The probe execution timer excludes model download, process launch, pre-main
imports, and final raw-array compression and receipt/manifest publication.

## Route B: fixed temporal engineering probe

The protocol was fixed before fitting: seeds 41, 67 and 89; 64 training episodes;
64 separate confirmation episodes; 12 observations per episode; 40 Adam updates;
learning rate 0.02; gradient clip 5. Each episode reveals a first-step cue that
must be retained until the final prediction. An exact cue-retention rule remains
in the comparison. No hyperparameter sweep or winner selection was performed.

| Kernel/control | Actual parameters | Confirmation accuracy in each of three seeds | Confirmation NLL by seed |
| --- | ---: | --- | --- |
| GRU, hidden 12 | 770 | 100%, 100%, 100% | 0.00007266, 0.00001248, 0.00002368 |
| Diagonal SSM, hidden 24 | 794 | 100%, 100%, 100% | 0.088405, 0.098499, 0.177318 |
| Exact cue-retention rule | No trained neural parameters | 100%, 100%, 100% | Not applicable |

The nearest available parameter counts differ by 3.1169%; no dummy parameters
were added. Each fit retains data digests and the seeded generator source,
labels, before/after logits, losses, parameter arrays, optimizer checkpoint and
source/config identities. A real SQLite
roundtrip checks trained-candidate qualification, adoption, hidden-state reset,
next-task use and persisted readback. The injected qualification callback is an
engineering evaluator, not production evaluation authority.

All three methods solve this small fixture. It does not demonstrate a neural
advantage over rules, a general GRU/SSM ranking, or a reason to fix HCSN as the
system's only Cell. The separate [immutable HCSN protocol](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/5f7f55e015dde7fab0c174081fef090ff45501de/proposals/localization-v2/formal_protocol.json)
is unchanged.

## Validation and provenance

The initial native stage is commit
`a7e727468da41fe2ac826b8b38178a6958f7ffea`, based on
`1eb72a1131285f5de98beeb7c95a27eab72d647e`. Its real
[Actions run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42506279859)
passed **111 tests with zero failures**. Five new tests cover local-update scope,
lineage and Python/native canonical commitments. The one independently ignored
worker is deliberately invoked by the passing process-kill/reopen matrix.

The retained local Python suite passed **49 tests** on unchanged source bytes.
It includes actual file-effect execution followed by lost acknowledgement,
database reopen and readback without a second invocation. These local Linux
tests include 13 semantic tests. The Apple Silicon real-model measurement ran
separately; it is not a second platform run of the unit suite.

Source code was published as small review stages; see
[review-stages.json](review-stages.json). Tests and measurements are attributed
to their executed source snapshots. Required scoped `just fix` and `just fmt`
maintenance, any actual patch, and later CI identities are recorded separately
in [CURRENT_RESULT.json](CURRENT_RESULT.json); formatting is not described as
having run on bytes that were measured earlier.

All three scoped push workflows passed at commit
`9e3cab866aa6202b99e9546f2c3c52137cc58c86`: the independent Python workflow,
the independent native workflow, and the combined tests-then-maintenance
workflow. The latter ran `just fix -p codex-hepta-learning-artifacts --locked`
and `just fmt --base 1eb72a1131285f5de98beeb7c95a27eab72d647e` only after
its tests. Its actual patch was reviewed and applied as commit
`b67016d8c44885afdf0df2507d214b02b141744e`: all 19 output file hashes matched
the retained receipt, all 17 Python ASTs were unchanged, and the two Rust changes
only wrapped test code and removed a trailing blank line. The original recurrent
reference files remained byte-identical. No manual test rerun followed maintenance.
The three new workflow YAML files also passed exact Prettier 3.5.3 with the
repository's original configuration. Both `--write` and `--check` succeeded,
and all three files stayed byte-identical. This was a scoped workflow check,
not a repository-wide `pnpm run format` execution.

## Retained attempts and reproduction

[evidence/manifest.json](evidence/manifest.json) records artifact sizes and SHA256.
The archives preserve original evidence rather than replacing unsuccessful or
superseded attempts with a clean summary:

- `semantic-real-v1.zip`: public model metadata and download receipts, a failed
  initial model-metadata request (HTTP 401), the successful pinned download,
  exact source snapshot, raw arrays and four source/candidate bundle pairs.
  The separately retained `semantic-runtime-jobs.json` provides authoritative
  runtime completion records. Model weights are not committed.
- `temporal-attempt-001.zip`: six initial engineering fits before the final
  lifecycle-capacity changes. This is retained as superseded integration evidence.
- `temporal-attempt-002.zip`: six fits on the final pre-maintenance source,
  including a complete source ZIP. It repeats the same three seeds and protocol;
  the two attempts are not twelve independent seeds or a tuning sweep.
- `native-initial.zip`: downloaded original JUnit archive, raw logs, exact
  native source and parent identities, and the failed Mac checkout record.
- `python-tests.json` and `python-tests.log`: the 49-test suite with before-source
  hashes and a verified unchanged-source result.
- `ci-maintenance.zip`, `ci-native-junit.zip` and `ci-python-probe.zip`: the actual
  downloaded, digest-verified Actions artifacts for the three passing workflows.
  `ci-records.zip` retains their raw job logs and API metadata; `ci-summary.json`
  records exact source identities and per-workflow counts. The maintenance ZIP
  includes the actual formatter patch, both source identities and its probe.
- `prettier-evidence.zip` and `prettier-result.json`: exact package/configuration
  identity, actual output and unchanged-file hashes for the scoped YAML gate.
  `prettier-runtime-job.json` retains the authoritative completion record.

The two local temporal attempts consumed 2.497177 seconds wall and 2.333560 seconds
process CPU in total. They comprise 12 fits / 480 updates on a repeated three-seed
fixture. The two archived CI repetitions add another 12 fits / 480 updates on
the same protocol and seeds. They add verification work, not independent
research evidence. Any automatic CI after final publication has its own Actions
records and is outside this frozen four-run / 24-fit archive. The Mac checkout attempts
timed out before any native build; Linux Actions supplies the native test evidence.

Use the commands in [the package README](../../scripts/hepta_cells/README.md)
for CPU tests and the create-only temporal probe. To reproduce the optional
Apple Silicon measurement, use the recorded source/runtime versions and the
archive's pinned public-model downloader, then run:

```sh
python3 scripts/qualify_hepta_semantic_serving.py \
  --model-directory /absolute/verified/model \
  --download-receipt /absolute/download-receipt.json \
  --output /absolute/new/semantic-attempt
```

Production adoption, daemon wiring, real-task retention/generalization, broader
serving measurements and the separate formal HCSN comparison remain open gates.
Passing these engineering checks does not change those gates to PASS.
