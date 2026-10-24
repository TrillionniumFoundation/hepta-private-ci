# Finite native / Codex execution A/B task pack

**Review draft, no agent/model run performed.** Eight newly authored Python
repair tasks in four source-construction families, with 65 private black-box
checks. This is a bounded execution-layer qualification pack, not a cell
learning experiment or a representative general-agent benchmark.

Read [PROTOCOL_DRAFT.md](PROTOCOL_DRAFT.md) before using this pack. Root must
review, bind real executor/provider/permission identities and freeze the
registration. The fixtures' task/source IDs are deterministic. Private expected
values and reference code are never copied into an agent workspace.

## Files

| Path | Audience and use |
| --- | --- |
| `tasks/<slug>/repair_target.py`, `TASK.md` | The only two initial agent-visible files |
| `public/candidate_runner.py` | Input-only black-box adapter, run only inside the external candidate sandbox |
| `private/<slug>/cases.json`, `reference.py` | Trusted operator only; never mount into agent/candidate sandbox |
| `operator/pack.py` | Validate, materialize, emit grading inputs, and compare observations without importing candidates |
| `operator/task-index.json` | Exact IDs, family grouping and all task/reference/test hashes |
| `operator/author_selfcheck.py` | Executes only pinned author fixtures; cannot be used for model candidates |
| `operator/author-selfcheck.json` | Actual preparation receipt, including every initial/reference outcome |
| `operator/registration.template.json` | Incomplete root-review template, deliberately not executable authorization |
| `operator/assignment.py` | Deterministic serial pair order, alternating N→C / C→N |
| `controller/` | Separate non-idempotent effect fixture and fault contracts; not application repair tests |
| `build_tasks.py` | Deterministic preparation generator; no external sources or model output |

The author check completed locally: all eight references pass all 65 checks;
all eight initial buggy versions pass at least one check and fail at least one.
This validates the pack's basic satisfiability and error detection. It is not
evidence of either executor's competence. Do not modify tasks after model
exposure to make an executor pass or to remove a difficult case.

## Preparation commands

```bash
python -B operator/pack.py validate
python -B operator/pack.py list
python -B operator/pack.py materialize --task stream_frames --dest /an/unused/fresh/workspace
```

`materialize` refuses an existing destination. It creates no sandbox by itself.
Put the destination in a separately enforced common tool sandbox; do not make
the pack or its parent directories reachable. Each arm/attempt needs a fresh
destination. For local-only Git setup use the common operator-controlled image
without inherited global configuration, hooks, remotes or credentials.

After an admitted agent attempt ends and its candidate is sealed, the trusted
operator emits inputs, runs the public adapter in a separate admitted sandbox,
and scores its captured JSONL observations:

```bash
python -B operator/pack.py requests --task stream_frames > /private/operator/requests.jsonl
# External supervisor launches public/candidate_runner.py with the sealed
# candidate in a networkless OS sandbox, passes requests on stdin, and records
# responses plus complete process/resource receipts. This pack does not supply
# a fake no-op sandbox command or run a candidate directly on the host.
python -B operator/pack.py judge --task stream_frames \
  --replies /private/operator/observations.jsonl \
  --candidate-sha256 DIGEST_MEASURED_BY_TRUSTED_SUPERVISOR
```

`judge` is pure comparison, not an execution/isolation attestation. Its grade
must be joined with independently authenticated supervisor evidence. It never
loads or executes submitted Python. Hidden inputs become visible to the sealed
candidate only during isolated grading; hidden expected outputs stay outside.

## Preparation-only check

```bash
python -B operator/author_selfcheck.py --output /an/unused/preparation-receipt.json
```

This helper refuses source outside the index and requires exact initial or
reference hashes. It executes only this pack's self-authored bounded fixtures
in newly created temporary directories. It is not an OS sandbox and must never
be extended to accept arbitrary candidate files. For post-model grading use
the external sandbox path described above.

The preparation helper refuses an existing output receipt. The earlier draft
receipt is retained separately; no model saw either draft. Scoring/assignment
regressions are available through `python -B operator/test_pack.py`. Their
fixture-only process checks do not execute either real controller owner or
establish any native/Codex recovery result.
