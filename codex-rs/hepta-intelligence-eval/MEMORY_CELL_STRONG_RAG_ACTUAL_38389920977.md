# MemoryCell: verified 40 + 72 actual-reader closure (2026-10-13)

This is a **reproduced, source-pinned development experiment**, not production
admission, an independently sampled future task benchmark, or a semantic
citation certificate.

## Original, reproducible evidence

- [Successful GitHub Actions run 38389920977](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38389920977):
  format/preflight **success**, real Qwen reader **success**, separate-process
  independent replay **success**.
- Exact generating commit: `3b03ea7dee4b270bdf328251f7a404571c9d1013`.
  Never transfer this CI result to another SHA.
- Original frozen input archive 11669174727:
  `23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b`.
  Original plan SHA-256:
  `9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`.
- Model-generation archive [11812994915](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38389920977/artifacts/11812994915):
  ZIP SHA-256 `de7087dbd3ee367475ef279d01dbeeeea46ee991b11399324289300df10c40bf`.
- Calibration checkpoint artifact 11811977893:
  ZIP SHA-256 `26ff349eef1e78367577be7dc59308166bb73ea13d5f63070ecdfd6fbc093f24`.
- Separate independent-replay artifact [11817452081](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38389920977/artifacts/11817452081):
  ZIP SHA-256 `442c7171cb2c522988e6e6c52b12201d1b59104702229dc256ca91b7bf6559c1`.

All four ZIP hashes, the inner complete `SHA256SUMS` member census (35 original,
43 generation, 20 checkpoint, 8 replay), the exact generating commit, all
40 calibration and 72 evaluation original answer entries, immutable raw/scored
score preservation, frozen reader identity, and source excerpts were checked
independently of the archived success flags. **28 constrained program tasks**
were re-executed using the original byte-pinned probe; their stdout, stderr
and exit codes matched the recorded observations. The 20 checkpoint contents
were byte-identical to their corresponding generation-archive files.

The local reproducer is `scripts/memory_cell/actual_strong_rag_archive_audit.py`.
The digest-pinned machine-readable receipt is
`scripts/memory_cell/data/strong-rag-actual-38389920977.json`.

## Real results, one frozen Qwen2.5-3B reader

Calibration on eight previously exposed *authored* questions ran 40/40 genuine
model generations for `k={1,2,3,4,6}`. Task successes: 4, 4, 4, 4 and 2.
The preregistered rule selected **k=1** on lower observed prompt cost. It was
**not robust to leaving out one calibration question**: 7/8 folds chose k=1,
one chose k=2. This calibration is not future-task generalization evidence.

The independent evaluation completed **72/72 actual generations**, all using
the same Qwen model/reader, original source bytes and recorded token cap:

| Arm | Strict successes | Correct with every program-declared source cited | Input tokens, eight calls |
| --- | ---: | ---: | ---: |
| Reader-calibrated top-k=1 | 5/8 | 3/8 | 3,961 |
| Hybrid top-4 | 3/8 | 1/8 | 10,806 |
| Hybrid top-6 | 2/8 | 0/8 | 15,463 |
| Hybrid top-4, reversed order | 3/8 | 1/8 | 10,806 |
| Single-hop selection | 4/8 | 4/8 | 4,575 |
| Full-path entity/revision filtering | 8/8 | 4/8 | 5,752 |
| Deterministic organized evidence | 8/8 | 4/8 | 5,179 |
| Program-defined support set | 8/8 | 4/8 | 5,179 |
| No evidence | 0/8 | 0/8 | 1,630 |

The *source-aware causal effects* are different from superficial headline
accuracy:

- **Full-path traversal versus single-hop:** 4 paired wins, 0 losses,
  4 ties; task-success delta **+4/8**.
- **Organization beyond full-path filtering:** 0 wins, 0 losses,
  8 ties; task-success delta **0/8**.
- **Organization versus calibrated k=1:** 3 wins, 0 losses,
  5 ties; delta **+3/8**.
- **k=1 versus fixed hybrid k=4:** 2 wins, 0 losses,
  6 ties; delta **+2/8**.
- Organization uses **573 fewer input tokens (9.96%)** than full-path
  filtering across eight reads, but contributes no new strict successes.
  Observed reader seconds also differ, not a deployed cost or statistically
  significant latency/ROI finding.
- Original model answers matched across **39 observed same-source prompt
  pairs**, with no recorded output-token, text, or task-result disagreement.

The formal citation metric here is **coverage of program-declared sources**,
not independent human entailment. Only **4/8** of the fully correct
`entity_time` and `organized` answers cite the complete declared chain.
This cannot support a >=99% independent citation precision claim.

**Total measured Qwen usage of this exact experiment:** 112 real generation
attempts, 109,100 input tokens, 1,411 output tokens, about 2,733.5 summed
reader inference seconds. These are measured inference counters, *not*
end-to-end deployed cost: ingestion, storage, maintenance, revocation,
recovery, amortized calibration and cloud pricing are not qualified.

## Mandatory disposition

**Scientific result:** For this authored eight-question population, relation
traversal matters, but full organization has **no incremental accuracy
advantage** beyond full-path entity/revision filtering; its small observed
token savings may still matter for efficiency. The unrobust top-k selection and
incomplete citation chains remain explicit failures to qualify.

**No parametric-memory promotion:** This job does not train or validate a new
parameter-memory module. It has **0** independent future source families,
**0** independent semantic citations adjudicated, no deployed lifecycle
measurements, no production switching/rollback receipts. Preserve
`production_accepted=false`, `statistical_superiority=false`,
`candidate_accepted=false`. Other branch HEADs or unrelated PR CI results
cannot be substituted for this completed source.

## Reproduce without downloading model weights

Download the four artifacts above, preserve their exact ZIP bytes, and rename
in one external directory to:

- `event-inputs-20261010.zip`
- `memory-strong-rag-20261013-real-reader.zip`
- `memory-strong-rag-20261013-calibration-checkpoint.zip`
- `memory-strong-rag-20261013-independent-replay.zip`

Then run:

```bash
python3 scripts/memory_cell/actual_strong_rag_archive_audit.py \
  --archive-dir /path/to/four/zips \
  --output /path/to/new/audit-result.json
```

The script fails closed on missing or changed ZIP/member pins, source drift,
duplicate scored records, altered answers/reader receipts, wrong task labels,
mismatched source excerpts, procedure stdout/exit-code drift, altered arm
metrics, or changes to the archived immutable independent-replay receipt.
It does not regenerate text or claim human semantic authority.
