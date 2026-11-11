# E — exact-source daemon CI readback

## Result and identity

This is a read-only archival verification of an existing successful GitHub Actions run. No CI run, native build, runtime test, training job, or adapter qualification was started by this readback.

| Identity | Value |
| --- | --- |
| Repository | `TrillionniumFoundation/hepta-private-ci` |
| Source commit | `6ecfa504d2132f3682ffb01f8c9d65346b26cf5b` |
| Source tree | `9184583f3842d90a560436f279c753f15792e3ab` |
| Run / attempt | `42937198717` / `1` |
| Native job | `130250073525` |
| Original artifact | `13821310445` |

Sources: [original run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42937198717), [native job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42937198717/job/130250073525), [artifact](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42937198717/artifacts/13821310445), and the preserved original records in this directory. The run's own head SHA and tree, execution records, and source snapshots establish identity; a later moving PR head is not used.

## Independently parsed tests

| Lane | Actual JUnit cases | Failures / errors | nextest excluded or ignored | nextest runtime | Recorded command elapsed |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ordinary | 1,146 | 0 / 0 | 72 | 199.746 s | 503.015228544 s |
| Root | 7 | 0 / 0 | 948 | 0.382 s | 1.828428932 s |

Ordinary covers `codex-hepta-agentd` (884 cases), `codex-hepta-intelligence-eval` (143), and `codex-hepta-learning-artifacts` (119), with `--lib`, two test threads, and zero retries. The ordinary launch record requires effective UID 1001. Counts come from actual unique JUnit testcase elements, independently matched to the raw nextest summaries and execution-record hashes. Neither XML contains failure, error, or skipped testcase elements. The 72 and 948 skip counts describe nextest exclusions or ignored tests; they are not additional executed testcases.

Root is a separate `codex-hepta-agentd --lib --run-ignored only` execution with one thread, zero retries, and a fixed seven-name filter. The complete decoded job log contains the actual output `2026-11-11T01:39:10.2357658Z Root test uid=0` at line 24169. Root's seven unique JUnit names exactly equal its expected and observed parent-name sets. Those parent names do not occur among ordinary's executed cases.

`root-prior-junit-excluded.xml` is byte-identical to ordinary's 1,146-case XML. It is retained solely as exclusion evidence and is not counted as Root output. The fresh `root.xml` has seven cases and a different SHA-256. Nested child output is not counted as extra Root parent cases. Exact commands, names, hashes, and identity checks are in `CI_EVIDENCE.json`; the original launch, execution, summary, coverage, and XML records are preserved in `RAW_ARTIFACT_RECORDS.zip`.

## Source unchanged through tests and maintenance

The six cuts are `checkout`, `before-tests`, `after-tests`, `after-maintenance`, `after-bins`, and `final`. Every original snapshot records the exact commit and tree above, an empty status, and 14,399 inventoried files.

All six original compressed inventory members were actually decompressed, parsed, hashed, and compared by full uncompressed bytes. Each expands to 3,332,743 bytes with SHA-256 `733e9f65946fc4cc67f8aa843c691b1fbb5eff77d3f94a8073ab3599861e73fe`; the six full byte strings are equal. This is stronger than accepting a green workflow or comparing the snapshot JSON alone. The large inventories themselves are intentionally omitted from E; their complete compressed and uncompressed hashes, sizes, file counts, and performed checks are recorded in the full member index.

Maintenance commands all returned zero, with no timeout or output limit:

- `just fmt --base b8e8c6e82abc1479c573f61a5e17d28d581e6cad`
- `just fix --locked --offline -p codex-hepta-agentd -p codex-hepta-learning-artifacts -p codex-hepta-intelligence-eval`
- `cargo check --locked --offline -p codex-hepta-agentd -p codex-hepta-learning-artifacts -p codex-hepta-intelligence-eval --bins`

`maintenance-summary.json` records completion and an empty changed-file list. Both `maintenance.patch` and `maintenance-postimages.jsonl` are zero bytes. These records, the six clean snapshots, and equal full inventories support unchanged source within this CI lane. The fix/bins package scope is the three daemon-related packages above; it does not establish completion of core or RMCP maintenance or their whole test suites.

## Helper custody

The helper command successfully built `hepta-joint-propose` from `codex-hepta-infer-worker-host`. The complete compiler JSONL contains 1,303 parsed messages, ends with successful `build-finished`, and emits the executable associated with the manifest's package and path. Its complete 1,049,638-byte JSONL and 62,077-byte stderr are preserved inside the compressed records ZIP.

The original helper manifest and verify-only record bind the clean exact source before and after, record a 1,439,816-byte executable with SHA-256 `26c976816b7e748ecfe1056944211d7bd4eee329111476c0fc7c5bde422e8824`, and report matching size/hash. The helper build command elapsed is 512.436105983 seconds. The executable binary itself was not included in the original artifact. Its hash is therefore original CI custody evidence, not an independently downloaded binary verification. Building the helper is not counted as a runtime testcase.

## Integrity and inclusion

The complete original artifact is 6,952,389 bytes with SHA-256 `c6563259135e25853ae98f7a45a25d5d06abf6204dd1a6206bdf23e9f1edc947`, matching GitHub's artifact digest. All 47 original ZIP members passed CRC checks. The original ZIP remains at `/workspace/scratch/f7c0ded86bcc/p0-ci-audit/daemon-6ecfa504-native-13821310445.zip` and is not republished in E.

`ARTIFACT_INDEX.json` indexes all 47 original members with their complete byte counts, SHA-256 values, original ZIP compressed sizes, CRC values, and inclusion or omission decisions. `RAW_ARTIFACT_RECORDS.zip` preserves the other 41 members byte-for-byte, including complete command logs, both fresh JUnits, prior-JUnit exclusion evidence, maintenance state, helper records, and toolchain/fetch records. Only the six large source inventory members are omitted.

`job-130250073525.log.gz` preserves the complete 3,145,405-byte decoded UTF-8 job log, including its original BOM and newline bytes. The raw decoded SHA-256 is `b0256d7bd9aff7ba2c54efc4de79a2851a057fe2b149a9142907fe18fcfe2688`. Decompression was checked for exact byte equality. `API_CAPTURE.json.gz` preserves the retrieved run, jobs, and artifact metadata without temporary artifact download URLs.

Every delivered file is at most 512,000 bytes. The complete log is naturally gzip-compressed and complete original record members are naturally ZIP-compressed; no binary has been split into fragments and no size exception is used. `MANIFEST.json` hashes every delivered file except itself; the manifest's own hash is reported with the handoff. `verify_archive.py` performs read-only archive checks and can repeat the original ZIP/inventory checks when provided the retained original:

```sh
python3 verify_archive.py --original-artifact /workspace/scratch/f7c0ded86bcc/p0-ci-audit/daemon-6ecfa504-native-13821310445.zip
```

## Cost and claim boundaries

The command elapsed times and nextest runtimes above are original record measurements. Maintenance command elapsed, CPU time, peak RSS, energy, and monetary costs are unmeasured here and remain unknown; they are not treated as zero. Timing fields are different measures and should not be added as if independent.

This evidence establishes the observed daemon lane tests, helper custody, and unchanged source across this lane's recorded cuts. Engineering testcase counts are not independent scientific tasks, adoption gains, or evidence of sustained learning benefit. This readback does not transfer qualification to another head, a newly added adapter, the full joint dependency closure, or an end-to-end scientific adoption claim. Earlier local SIGKILL and low-disk attempts retain their own source identities and outcomes; this successful CI lane does not retroactively change them.
