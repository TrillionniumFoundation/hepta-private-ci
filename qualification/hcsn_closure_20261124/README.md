# HCSN prospective closure campaigns

This package contains the independent 8/32/64-population research implementation,
the frozen comparisons, and explicit numerical follow-ups for PR #7067.
It keeps the earlier `hcsn_smallnet_20261124` source immutable. A completed
campaign is an evidence record; its learning, precision, relative-quality and
integration gates remain separate judgments.

Read [the full Chinese results](RESULTS_CLOSURE_ZH.md),
[the mathematical contract](theory.md),
[rule programming and conventional controls](RESULTS_COMPANIONS_ZH.md), and
[the primary research sources](RESEARCH_BASIS_ZH.md).
The real paired audio/video experiment has its own
[package and data contract](../hcsn_closure_av_20261125/README.md).

The measured executable source is commit
`c4ae70d44613434aaf165529a6076fa3400ca431`. The complete three-wave raw
evidence is present at `84d554300002f802e98d30ef0552ab008c2b0241` on
`evidence/hcsn-closure-results-20261125`; later report commits on that branch
do not change the executable source. The [catalog](evidence/EVIDENCE_CATALOG.json)
binds both revisions, 75 raw archives and the separately counted experiment
roster. The 177 completed training slots do not imply 177 passed capability gates.

## Reproduce executable source

The measured Linux runtime is Python 3.12.3, Torch 2.8.0+cpu and NumPy 2.5.4.
The isolated installer validates the exact 21-file base manifest, copies only
the requested extra sources, and records all copied bytes. It does not install
software, change the repository or start training. Every output directory must
be new. Use a checked-out source revision, not an unrecorded edited working tree.

```bash
python qualification/hcsn_closure_20261124/install_workspace.py \
  --repo /absolute/hepta-private-ci \
  --out /absolute/hcsn-source \
  --profiles core variants efficiency normalization communication companions \
             projection precision joint boundary av
```

Subsequent module commands run with `/absolute/hcsn-source` as the working
directory. `INSTALLATION.json` must remain at that source root: it binds the
historical base. Each campaign additionally freezes its own complete source
and runtime closure. A different runtime creates a new reproducibility record;
it is not the recorded trial's original execution.

## Campaign entry points

The main factorial has 63 slots. It includes 54 mixed training slots
(18 boundary/feature/width settings times three seeds) and nine native32 quality
comparisons. The two commands below reproduce the standalone main factorial;
for the joint conventional comparison, run only `prepare` here and follow the
coordinated sequence below before starting main training.

```bash
python -m qualification.hcsn_closure_20261124.campaign prepare --root /absolute/run-main
python -m qualification.hcsn_closure_20261124.campaign run --root /absolute/run-main --workers 6
```

The same audited fit loop is used by source-bound independent variants.
Each suite has its own fixed seeds and source identities; they cannot be pooled
as if all methods were evaluated on the same test sample.

| Experiment | Prepare module / extra argument | Run module | Slots |
|---|---|---|---:|
| Actual call/panic drift feedback | `variant_run prepare --suite dual` | `variant_run run --workers 6` | 12 |
| Original versus accelerated mixed training | `variant_run prepare --suite fast` | `variant_run run --workers 6` | 18 |
| Signed, unsigned and boundary controls | `communication_run prepare` | `communication_run run --workers 5` | 21 |
| Pure boundary / pure signed / joint | `joint_run prepare` | `joint_run run --workers 6` | 9 |
| N64 projected native32 quality follow-up | `precision_run prepare` | `precision_run run --workers 6` | 6 |
| One fixed boundary-centering confirmation | `boundary_fix_run prepare` | `boundary_fix_run run` | 12 |

The module prefix in every row is `qualification.hcsn_closure_20261124` and every
command requires `--root /absolute/new-run-directory`. These commands reproduce
the declared experiments; repeated use of an already revealed test family must
not be advertised as a new independent confirmation. The campaign requires the
complete terminal roster and checkpoint seal before test construction. A
process, protocol or receipt error stops the gate rather than silently skipping
the slot or replacing its result.

For the conventional controls, use a fresh prepared main directory and freeze
the baseline protocol before either suite constructs its holdout. In terminal A:

```bash
python -m qualification.hcsn_closure_20261124.baselines_run freeze \
  --root /absolute/run-baselines --parent-root /absolute/run-main --suite baselines
python -m qualification.hcsn_closure_20261124.baselines_run campaign --root /absolute/run-baselines
```

The baseline campaign trains and seals all 27 candidates, writes
`/absolute/run-baselines/TRAINING_TERMINAL.json`, then waits for the main seal.
After that terminal record exists, run the prepared main campaign in terminal B:

```bash
python -m qualification.hcsn_closure_20261124.campaign run \
  --root /absolute/run-main --workers 6
```

Main testing now starts only after both training rosters have sealed. The baseline
driver verifies both seals before its own holdout and waits for all short tests
before the long-delay panels. This deliberately serializes baseline fitting ahead
of main fitting so the documented CLI sequence guarantees the same information
barrier; it does not reproduce the recorded campaign's overlapping scheduling or
outer wall time. Do not run the complete standalone main example first and then
call a newly fitted baseline a prospective common-holdout comparison.

Rule programming uses a separate directory and can begin after the fixed main
parents are available:

```bash
python -m qualification.hcsn_closure_20261124.baselines_run freeze \
  --root /absolute/run-programs --parent-root /absolute/run-main --suite programs
python -m qualification.hcsn_closure_20261124.baselines_run campaign --root /absolute/run-programs
```

Read [PROGRAMS_ZH.md](PROGRAMS_ZH.md) for the exact rule prior, editable support,
query routing and regenerated-program controls. [COST_REPLAY_ZH.md](COST_REPLAY_ZH.md)
describes the separate cold-process timing replay. Supervised closed-form ridge
fitting is not labelled strict WSP.

## Numerical and causal checks

The tests address mathematical derivatives, cache lifetime, mass/risk semantics,
causal continuation, source/roster tampering and actual BP. They are not proxies
for the learned-task gates.

```bash
python -m unittest \
  qualification.hcsn_closure_20261124.fast_tests \
  qualification.hcsn_closure_20261124.dual_tests \
  qualification.hcsn_closure_20261124.communication_tests \
  qualification.hcsn_closure_20261124.normalization_tests \
  qualification.hcsn_closure_20261124.projection_tests \
  qualification.hcsn_closure_20261124.precision_tests \
  qualification.hcsn_closure_20261124.joint_tests \
  qualification.hcsn_closure_20261124.boundary_fix_tests -v
```

The normalization and explicit projection numerical sweeps use, respectively,
`normalization_probe launch --root ...` and `projection_probe launch --root ...`.
Both preserve raw FP64 comparisons and rejected cases. The explicit bounded
joint projection is an opt-in numerical operator, not a repair silently applied
to the original results. FP32 input-VJP failures remain part of its qualification.

CPU measurements distinguish update body, complete worker launch-to-exit,
validation, final testing, source/data preparation and publication. Nested scopes
must not be added twice. Energy and unmeasured program-discovery costs are
unknown. The plots are generated from audited summaries by `render_results.py`;
`figures/FIGURE_DATA.json` binds their exact inputs and values.

## Recover raw evidence

Every logical archive is distributed as size-bounded, individually valid gzip
parts. The index and per-object descriptors bind encoded parts, decoded bytes,
original object SHA256 and Git blob SHA1. The archive itself has a complete
per-member checksum manifest. A successful decompression alone is insufficient.

From a checkout of the evidence revision, verify and restore each wave into a
new output directory. The command verifies every part and complete object before
creating that wave's output directory:

```bash
for wave in root-wave1 wave2 wave3
do
  python qualification/hcsn_evidence_transport_20261125/reassemble.py \
    --repo-root /absolute/hepta-private-ci \
    --index /absolute/hepta-private-ci/qualification/hcsn_closure_20261124/evidence/raw/$wave-INDEX.json \
    --output-root /absolute/hcsn-restored/$wave
done
```

The three indices contain respectively 19/30/26 archives and 206/165/117 gzip
parts: 75 archives, 488 parts and 206,178,943 original archive bytes in total.
The maximum encoded part is 479,168 bytes. The
[raw catalog](evidence/RAW_EVIDENCE_CATALOG.json) records the full successful
verification against the published checkout, per-object hashes and index hashes.
The `source_commit` field in a transport index names its known publication
ancestor; each frozen campaign's embedded source manifest is the authority for
the executed experiment. Raw transport does not certify scientific conclusions.

Reassembly writes to a separate output location; it does not replace the
source checkout. The archive member manifests must also be checked before using
restored trial files. Raw trial directories preserve all candidates, failures,
predictions, checkpoints and costs. Derived interpreter caches are excluded
explicitly. AV media and repeated public cache arrays have their own explicit
exclusion and acquisition manifests.

Research source is frozen on the PR source head; subsequent independent reports
and raw evidence can be appended on the dedicated evidence ref without changing
the executable source under CI. Their publication catalog binds those two
revisions. Neither a successful local test nor an evidence upload substitutes for
the final source head's required hosted integration checks.
