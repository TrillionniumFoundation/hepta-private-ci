# Independent supplemental execution audit

**PASS: zero mismatches in the completed namespace-4 confirmation evidence.**
The audit did not combine original run_01 confirmation performance with the new batch. It read original model freezes, training archives and supervisor cost metadata only. Scientific effect estimates and admission decisions remain the separate statistics audit.

## Evidence checked

| Check | Coverage |
| --- | --- |
| Successful fit/domain workers | 16 / 16 |
| Distinct shared worlds | 2,048 |
| Twelve valid-arm episodes / queries | 24,576 / 147,456 |
| All arm attempts, including mean | 26,624 |
| Completed/prefix query checkpoints independently reconstructed | 159,707 |
| Keyed observation tokens independently reconstructed | 49,607 |
| D / same-matrix HMM complete episode trace pairs equal | 2,048 |
| Mean support failures / attempted episodes | 16 / 2,048 |

Targets were independently recovered by left-bisecting archived world paths. Observation tokens were rebuilt from the declared emission probabilities and keyed blake2b draws. The audit did not call Episode.target, Episode.observe, run_episode, Planner or BeliefMemory. A separate four-address filter replay used the frozen matrices and SciPy expm to verify every public WRITE, propagation, observation update, causal deadline answer and query checkpoint hash. It also recomputed action durations, prices, fees, query utilities and episode aggregates.

Left-versus-right boundary handling materially changes the correct target for **826 distinct world/query pairs** and the token for **154 distinct actual observations**. All archived records use the declared left-limit semantics. This is an exercised boundary condition, not merely an untriggered source assertion.

## Mean support failure and provenance

All sixteen mean failures occurred in OOD: four for fit 151103, six for 151107, four for 151113, one for 151117 and one for 151123. Each was independently reconstructed with exactly zero predicted observation mass and a real keyed observation. All invalid outcomes remain null; actual consumed fees and CPU are preserved. No survivor-only mean performance estimate was computed. This finding concerns the registered two-neighbor phase-index projection, not every possible point-state approximation.

The supplement readback timestamp 2026-11-01T08:08:42.449656+00:00 precedes launch 2026-11-01T08:08:43.367797+00:00 and the first claim 2026-11-01T08:08:43.744180+00:00. All sixteen claim/result identities agree with supplement commit e4b51213bd19b6532553d252056573c17abc4814. The original eight fitted archives and selections remain byte-identical to the original model freeze. All 41 local Git blob identities matched the publication receipt; the remote readback itself is evidenced by the separately retained connector receipt.

## Exact progress-archive reconstruction

The complete compressed confirmation archives reconstruct **all 2,048 progress lines and 89,314,299 bytes** exactly. Each regenerated line was compared byte-for-byte to its local plain JSONL counterpart, and every full SHA-256 matched both disk and the confirmation record. Publishing the complete confirmation archives therefore preserves every progress-record byte without a duplicate progress upload. Local progress files remain untouched.

| Worker | Progress JSONL SHA-256 |
| --- | --- |
| 151101_iid | 23e95074168521f5f0d1d2d4ef24e403df7790dd0c05db1fbd6294e26c1d586b |
| 151101_ood | f831bb2dc169dfd0e4f30ba302a0df4fe757f201f98bd6156ac9934e96211b88 |
| 151103_iid | d01cd943ecae96d69339a1035366eddb14b9208080c0232be42946627ac40331 |
| 151103_ood | 62a5310b28cf99f8a879ebf09f0d859b0c7b9fd32fc4636cdb3b731e34f0bc16 |
| 151107_iid | 2d1c775e677d833178a44ed2562f85129c8f6dd1cdfa86897a7ef68a6b15e5a6 |
| 151107_ood | bb7d4589b770aeddd7ee05bc4913c1ced987ee6d58277d16a2f51b4da46f6a18 |
| 151109_iid | 191f59381adeb537e7809f5b91bc924786dcef68e3eb56f0ad78bb44b8b21b95 |
| 151109_ood | 3d406d60ce100b8a3d3d7275a8a15765501125ec20abaf2fdf8c7085f690031a |
| 151113_iid | 974a0326bcb646b348d01c591b71d1057f3d7c5b5d198e10c3ee11ea06cd73be |
| 151113_ood | 9566a72e66f797e8d09dc3e93731804ad82cd048c1c6b5f125a402ea884739d0 |
| 151117_iid | 31d2c791bc19b35bcc73064202f35b7c24d686c5fc9dbf15ba3ae1bc93afeb1d |
| 151117_ood | 6e39e17557ec78a6b8a1a6fe6f000a4920bc313509b6c5c613ac77215d3e808e |
| 151119_iid | 1a7995481f5e93873fb89746b92bef4be537618fdcceea60f1cff15f6a033500 |
| 151119_ood | 2bbc2b35c19b248404e80dd00c24a2297006ff741186de35c3caaaad6fd9b572 |
| 151123_iid | a2e4958fa4e05927af0da3815c9aef6ee31153494b6228a930ff5b45c34fba98 |
| 151123_ood | f92665e1240e82ccd7cdfca004d81abe2c1ad544d503339e6fbb78d1faa60213 |

Reconstruction command from the repository root; it writes a separate directory and refuses to overwrite existing files:

```bash
python - <<'REBUILD'
from pathlib import Path
import gzip, hashlib, json
base = Path("tools/hcsn/addressed_decision_r15_20261101/run_02")
output = base / "reconstructed_progress"
output.mkdir(exist_ok=True)
for source in sorted((base / "confirmation").glob("*.json.gz")):
    record = json.loads(gzip.decompress(source.read_bytes()))
    target = output / f"{record['seed']}_{record['domain']}.jsonl"
    digest = hashlib.sha256()
    with target.open("xb") as stream:
        for index, world in enumerate(record["world_tapes"]):
            row = dict(index=index, world=world, arms={
                name: arm["episodes"][index]
                for name, arm in record["arms"].items()})
            line = (json.dumps(row, sort_keys=True, separators=(",", ":"),
                               allow_nan=False) + "\n").encode("utf-8")
            stream.write(line)
            digest.update(line)
    assert digest.hexdigest() == record["progress_journal_sha256"]
    print(target.name, digest.hexdigest())
REBUILD
```

## Accounting and limits

The supplemental confirmation receipts sum to **293.518550 child CPU seconds**, with zero failed workers. The old sixteen confirmation attempts, including five failures, remain recorded as **171.435688 child CPU seconds** in the separate research ledger. These are process costs, not simulated task fees.

This audit's metered child used **26.895126 CPU seconds** and 199,324 KiB peak RSS. The meter includes scientific-library imports, raw-file reads, verification and the initial JSON write; it excludes the outer interpreter startup and final receipt/Markdown write. Detailed timing scope is retained in the JSON.

The audit verifies recorded finite-model execution and evidence consistency. It does not independently prove the financial continuum model, holding-time sampling distribution, global controller optimality, Python process isolation, native Rust integration or hardware energy. The memoryless candidate matrix is reconstructed with the frozen declared helper. None of these limits changes the exact trace, checkpoint and archive-equivalence findings above.
