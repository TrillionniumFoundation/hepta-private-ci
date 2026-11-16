# Numerical follow-up evidence: publication map and review

This is a proposed publication inventory, not a publication receipt. It binds
existing files to SHA-256 and repository-relative target paths. No numerical
test or training process was started for this inventory. The frozen source,
the failed attempt and every original receipt were left unchanged.

Evidence prefix: `qualification/hcsn_differentiable/evidence/localization-v2-20261108/math`.

The machine-readable map is publication/math-v2-file-map.json. Its top-level
files entries contain source relative to the scratch workspace, target relative
to the repository, sha256 and bytes. The map itself is published as
publication-file-map.json under the prefix; its final hash is computed by the
outer publisher rather than embedded recursively. This review is mapped to
PUBLICATION.md; its hash appears in the machine-readable map.

## Publication organization

- Publish one original repair-source.zip plus the locked 29-member manifest.
  Do not unpack snapshot Python files into evidence, where test discovery could
  import duplicated tests. The three actual implementation paths are a separate
  review stage in the real package.
- Publish raw receipts, JSONL event logs and subprocess logs as readable
  individual files. Do not also publish the duplicate attempt-002 evidence ZIP.
- Preserve failed attempt 001 before passed attempt 002. Do not rename the
  original blocked/incomplete result as a successful qualification.
- Exclude repair-v2/submission.json, repair-v2/native-export.json, the unpacked
  local repair-source copy and all bytecode caches. These are duplicate
  transport/working files, not independent evidence.
- The six files under proposals/localization-v2 and subsequent training
  artifacts are handled by the parent publication plan, outside this map.

## Verified source inheritance

Parent: the math-closure **28-file** snapshot, archive SHA-256
`353f7c0f50d187adeccbd1fff0638d1a649fe2c547c03ebf23e3fceafa846ff8`. Its planned prior-stage capsule target is
qualification/hcsn_differentiable/evidence/math-closure-20261108/final-native/source.zip.
This is a lineage reference, not a claim that that publication already exists.

Repaired capsule: **29 files**, archive SHA-256 `cb49a5f1aa24e15e25f46dd9fc8722de8fba4fa471d69a52142d37e8d98c3a2a`.
There are **26 byte-identical inherited files**, two changed existing files
(operator.py, MODEL.md) and one added test file. Among Python files,
**19 are inherited byte for byte**, only operator.py changes, and
tests/test_probability_intervals.py is added. In particular, network.py,
encoder.py, contract.py, checkpoint.py, regenerative.py, finite_renewal.py
and value.py retain their parent exact hashes.

The parent capsule members, frozen local parent files, repaired ZIP members,
unpacked repaired working copy, qualification before/after hashes, both budget
before/after hashes, and original failure hashes agree with their corresponding
manifests. The patch equals the exact unified diff of the three changed paths.
This inheritance statement refers to the 28-file math-closure parent, not to
an earlier Git commit's unmodified bytes.

| File inside repaired capsule | Relation to parent | SHA-256 |
| --- | --- | --- |
| .github/workflows/hcsn-differentiable.yml | inherited_exact | `b67cf5d771ec888a96e0a5d9344c101a36037dba6b7aebceac03cff68efd76bd` |
| BENCHMARK.md | inherited_exact | `bcfbeb4174d834115017d23e4921838c401aa741fd49eef2572776ed633bc969` |
| DATASET.md | inherited_exact | `820da5ac36a1553346a756eedac57aa9928a97e4e8c566ef5ca8beff01359bbd` |
| MODEL.md | modified | `059a76bd635f95e6dfc467237f25b661859c61c94a09067aeb9165c28924f5ee` |
| README.md | inherited_exact | `c9e56371ea22d637939675d837fbe85e74f9a9abcf7d3e05062f4abe2f370e3a` |
| __init__.py | inherited_exact | `bcde159e1a07a1da1df4b22caccae7f974443d34bbd071a6e845791f3e8b4123` |
| benchmark_admission.py | inherited_exact | `468f53365852f75d18708b504855ac1b5ad8e982fb4d82a6c5f7ee5bac9eabb0` |
| checkpoint.py | inherited_exact | `9565cba284f479bbab7c8ee61ca7a5330ddb9a9c4efed7786d92a37f7a93c793` |
| ci_baseline.json | inherited_exact | `9788b360050963ea0aee86fb825335fa45cdb4f32e0db60adfdf25812c9c4db2` |
| contract.py | inherited_exact | `79e1127dc126fb8ac97ce7542bac2c9d70c71e0fd2d24416f146d4ec82be099e` |
| encoder.py | inherited_exact | `8297a3a994e0ff7b97e4d73b4ac92f8bdc8a691dfdf145fc8fcc45be5cad7b18` |
| error_budget.json | inherited_exact | `58581f46eaba0381884665b7b7ca7d191a4d026d7b3866622c5da72702649a86` |
| error_budget.py | inherited_exact | `0b378dfea9f72cd946f40248c7573bff324db7fff9570b15cab67d9a2cb78b58` |
| finite_renewal.py | inherited_exact | `6f582ab64695ba676f5d1b4f47ceb39c6b4f8a70cde85eafe21ab3aaaca823de` |
| localization_smoke.py | inherited_exact | `99c214040e1c2bd3057fb77641c2b75faad3c3c61d48c27fda33629d1332e372` |
| network.py | inherited_exact | `04726551b6d4a53de2eb0daa1d8f5f30d96c7852bcf3ee769220ff584e56a687` |
| operator.py | modified | `a372ca8eef2b41714f632e0b1db2a58f98409fbb23858eb83bfe93a7833f1677` |
| regenerative.py | inherited_exact | `551bdc384257ab0ae510903165b580c50e761410777480989406395750a71ae1` |
| research_protocol.json | inherited_exact | `27c84c4867f3967e2544639ca188fae865768dfc9d6928074062e027ca2a83e8` |
| run_qualification.py | inherited_exact | `d84e5fdac31da852f9e4639899dae3e797ee6c0a4e2dd81772d03eff5e43e4c6` |
| tests/test_benchmark_admission.py | inherited_exact | `f5372a17de53d86f39604f79a137cfa2fc0108b1158c04d52f7056b715d01e55` |
| tests/test_encoder.py | inherited_exact | `8f8235398de00aaefef30b92633e189a451c24ed657858220c352e0b6ce66011` |
| tests/test_finite_renewal.py | inherited_exact | `394014c3c8b569af4436619e3c2a846970c282d5a3ff6d7248c1b091e89038aa` |
| tests/test_network.py | inherited_exact | `0ff492b3068cfcb63925d0b986194d8f1cd26ce0672faf48ddbaba07fcb47759` |
| tests/test_operator.py | inherited_exact | `6887878f132ee6a86423f400aaeeac35ff2a96032ac199534e4932fcf3976779` |
| tests/test_probability_intervals.py | added | `14aba48940fbc279532a6a081d708f3a42fc3c94bcfeefad2aaaee09ff945ba9` |
| tests/test_regenerative.py | inherited_exact | `d3b6b14859b235f7b2eee3ecefebf76a8e45d1eec34aa55315983be5e26887e0` |
| tests/test_value.py | inherited_exact | `ce6d57768ca785d656fdcb1ab7c86d7379d16f47a58540044474d40378e2acf9` |
| value.py | inherited_exact | `59847f1a39e834e2eb927840ee608b5914b7a61c1ebb4be7fce956b1285b8101` |

## Runtime precision and retained outcomes

The mathematical/operator work uses **Torch FP64** on CPU, with fixed ordinary
FP64 durations and first-order reverse AD. Actual transformed physical FP64
tensors are recorded in hexadecimal in the full v2 receipt. No FP32,
mixed-precision, GPU kernel or higher-order-derivative qualification is implied.

The independent rare-bin references use **80 decimal digits of working
precision**. They are numerical reference evaluations, not exact arithmetic
certificates. Both source coordinates, both negative bins, positive-density
integrals and high-precision survivor differences are retained. Fixed positive
Gauss quadrature of order 32 is part of the operator; order 64 is the declared
quadrature refinement.

| Existing execution | Outcome | Receipt SHA-256 |
| --- | --- | --- |
| v2 attempt 001 | blocked_or_incomplete; native exit 2 | `7dc38190983f99baa5a3ae0c858331f0072235fdfef4e8d1dbcdf379c618413d` |
| Repaired qualification | 75/75 passed, 0 failure/error/skip | `9610040fd99f9501ba4d1cfc047517101d0142bfa3994073a68b797d59c5df34` |
| Old four-fixture budget rerun on repaired source | four fixtures passed | `e9c4a749bb8740ee5ae662fef677983910d014f27de2019ffb09d3c635bed48f` |
| New v2 attempt 002 | passed_locked_frozen_profile; all four gates true | `1c31a015de53ad720bfa7ac3e952fdbe494a8251161f5741c49239b247a53ddc` |

Attempt 001 failed at a spatial refinement because subtracting two survivor
values near one produced two negative active-bin coefficients. Their true
positive probabilities are about 1.118858573369923e-16 and
1.083323438097214e-16. Direct Gaussian interval masses and reflected log
differences resolve the cancellation. The tail remains a direct survivor;
there is no clipping, row renormalization or positivity-tolerance waiver.

The four added tests check the trigger against the high-precision reference
and independent positive-density integration, CDF/SF tail endpoint derivatives,
reflected-bin first-order AD versus finite differences, and the complete
256-cell trigger. The repaired trigger probability is
1.1188585733699357e-16 with relative reference error 1.1324274851176597e-14.

The original durable stdout, stderr and status of the failed budget, its
diagnostic, and the repaired three-stage job were retrieved read-only.
Status/log captures are new byte-preserving copies of existing executions;
they do not represent reruns. Empty stderr files are retained as zero-byte files.

## All admission gates and fixed resource limits

The original and repaired v2 profiles have equal physical/grid/initial-law,
gap-selection, threshold, CPU and memory values. The original failed profile
SHA-256 is `09fbea17afe5e95a98cd9efbf84a92b2b7c61a8653bcaf241f6d00ba769b59df`; the repaired profile SHA-256 is
`a6661067b366f386d96782687dee6ace5718ffcd8148b2def3bca286c7293600`.

All value/refinement errors below use the scale specified by their full
receipt, usually max(1, absolute continuum reference). The old four-fixture
rerun retains its own d=0.1 profile and fixture initializations; it cannot
substitute for the distinct d=0.2 localization profile.

| Metric | v2 observed maximum | Locked limit | Old four-fixture rerun maximum |
| --- | ---: | ---: | ---: |
| `combined_value_error` | 0.0020855629019780526 | 0.01 | 0.0028164964555819792 |
| `linear_solve_residual_estimate` | 6.585372225579775e-13 | 2.0000000000000001e-10 | 4.8276590772036052e-13 |
| `phase_refinement_delta` | 2.154699219006264e-05 | 0.0050000000000000001 | 1.2573428955221647e-05 |
| `probability_mass_error` | 5.5511151231257827e-15 | 5.0000000000000002e-11 | 1.3322676295501878e-15 |
| `quadrature_refinement_delta` | 2.4685086495704369e-10 | 1.0000000000000001e-05 | 1.7165157906035553e-11 |
| `sequence_mass_drift` | 6.2172489379008766e-15 | 1.9999999999999999e-06 | not a four-fixture gate |
| `space_refinement_delta` | 0.0017234743105992492 | 0.0050000000000000001 | 0.0021152154159696209 |
| `tail_refinement_delta` | 0.00023339675335488845 | 0.0050000000000000001 | 5.7327686473756734e-05 |
| `time_refinement_delta` | 0.0022829490872890291 | 0.0050000000000000001 | 0.0027563824716785789 |

Additional explicit requirements:

- Probability minimum must be at least **0**, without a negative tolerance;
  observed minimum across all 325 gap tables is **0**.
- The sequence continuation error uses the same **0.01** combined-value limit;
  its maximum is **0.0008784401090655221**. A terminal continuation is paid once.
- All global gap interfaces, all locked positive-gap perpetual checks,
  all six refinement anchors, and all six unconditioned schedules must pass.
  The four recorded aggregate gates are all true.
- Source-before and source-after must equal the locked manifest. All three
  passing stages and the failed attempt satisfy this identity check.
- CPU threads **1**, CUDA **disabled**, v2 wall budget **300 s**, RSS limit
  **2,147,483,648 bytes**. Actual v2 duration is
  **82.183511047856882 s** and peak RSS
  **821,989,376 bytes**.
- Locked grid: 128 active cells, endpoint 2.4, 16 remaining-time phase cells,
  deterministic refractory duration 0.2, tail rate 1, quadrature order 32,
  initial log standard deviation 0.08; total state count 145.
- Frozen physical initialization: mu=-0.12, sigma=0.35, log boundary=0,
  log absolute reset=0.32, discount=0.15; initial margin 0.55. The actual
  transformed tensor values, including FP64 rounding, govern reproducibility.
- Integer tick differences are divided by **10,000,000**. No timestamp clipping,
  resampling or substeps are used in the actual schedules. The step-halving
  budget is a separate fixed-basis resolvent sensitivity. The 26 locked distinct
  gaps include zero; a zero-duration perpetual resolvent is not evaluated.
- Four 32-event A01 windows retain the original first gap of their slice,
  including windows 2-4. Complete A01 128-event and D01 64-event prefixes
  begin with zero gap. This matches the separate interface runner.

## Limitations that must accompany publication

- The d=0.2 localization profile is a different fixed physical model from the older d=0.1 profile; no old qualification was inherited.
- Only the recorded frozen physical initialization, grid, conditioned-Gaussian initial law, exact gap metadata and A01/D01 schedules are numerically admitted.
- The 325-gap audit verifies positivity and row mass interfaces; it does not qualify full-dataset learning or every initial law.
- The 0.016974039199635815 rowwise perpetual discrepancy is a diagnostic scaled by max(1, infinity-norm of continuum basis U), not a passed uniform-state error gate.
- Observation-conditioned neural filtering/content feedback, the full trainable physical parameter domain, arbitrary new sequences/initial laws and long-sequence error amplification remain unqualified.
- Refinement deltas are sensitivity observations; repeated QPR projection can make smaller steps less accurate. They are not independent additive errors or certified bounds.
- Rounded residual error estimates use rounded floating-point residuals and norms; they are not certified error bounds.
- These numerical jobs started zero training fits. Any later interface training evidence is separate; no model superiority, GPU/mixed-precision, throughput or energy claim follows here.
- The trigger/reset policy remains fixed; endogenous optimal free boundaries/QVI and original equity E are outside this qualification.

The maximum rowwise discrepancy is **0.016974039199635815**, or **1.697404%**
on its declared diagnostic scale. It exceeds the 1% common-prior gate if that
gate were improperly repurposed as a uniform-state gate. The actual qualification
never declares such a uniform-state gate. The common-prior maximum is
**0.208556%**; the unconditioned sequence maximum
is **0.087844%**. These results must remain separate.

## Exact publication inventory

Target suffixes in the table are relative to the evidence prefix above.
Original file contents are copied without reserialization. The derived
PUBLICATION.md and machine map are additional review indices; they do not
replace any original receipt.

| Target suffix under the evidence prefix | Bytes | SHA-256 |
| --- | ---: | --- |
| README.md | 3906 | `9cd1564a37e0149e0d747a339475fc50120e2ff0650bb1bcc49d6f17da94373a` |
| profile.json | 2667 | `09fbea17afe5e95a98cd9efbf84a92b2b7c61a8653bcaf241f6d00ba769b59df` |
| run_budget.py | 15240 | `e4d50b270f9c04f28a1724f9bc32989f10093023b92b2a62efff85ed64040e7d` |
| source_manifest.json | 3482 | `494b8718e41106d7b80bd8dd1122fe0dbe8bac737a853cb0c400e13e0e163d03` |
| attempt-001/result.json | 125430 | `7dc38190983f99baa5a3ae0c858331f0072235fdfef4e8d1dbcdf379c618413d` |
| attempt-001/negative-bin-diagnostic.json | 1853 | `5f9585c18a2dc60f129746234514caab70b2d572351abf4ddac79ac3b8670246` |
| repair-source.zip | 102025 | `cb49a5f1aa24e15e25f46dd9fc8722de8fba4fa471d69a52142d37e8d98c3a2a` |
| stable-intervals.patch | 9487 | `152d2da9c2998ac0809f10ae4dbca997ef1add04c3a8e328e91ff33e30fe0286` |
| repair-v2/profile.json | 3020 | `a6661067b366f386d96782687dee6ace5718ffcd8148b2def3bca286c7293600` |
| repair-v2/run_budget.py | 15316 | `f8f411e1e3c7a13c9f5a4c6d94b631201506c143e0c2232cce60d68ede11b05b` |
| repair-v2/source_manifest.json | 3625 | `a0e067b9c7403d0ba2a683307f82ed0d461f771200a84de63e5dd1426fdd3bc3` |
| repair-v2/native-provenance.json | 2088 | `a100414589a51e586402e2e817c13f9dd0a8fb3672de515d053338c66833ff3d` |
| repair-v2/REPAIR.md | 7369 | `1ad05725e5eafbb82fc78eb80fd7f57c84348db83665c088090b06f6eb9b3994` |
| attempt-002/qualification.json | 47783 | `9610040fd99f9501ba4d1cfc047517101d0142bfa3994073a68b797d59c5df34` |
| attempt-002/qualification.log | 24347 | `5609708a8e26fd5551d161f0606fc4c91f22fd150b7a95d224bb5935559f203e` |
| attempt-002/original-four-fixture-budget.json | 30023 | `e9c4a749bb8740ee5ae662fef677983910d014f27de2019ffb09d3c635bed48f` |
| attempt-002/original-four-fixture-budget.log | 154 | `6fbb7df64c82086f03c99d35bb6316491518c4e31a070ad3746923b29d26993a` |
| attempt-002/v2-profile.log | 231 | `744838d96397fb194d37b815305b687ffa7bd11113fa4541283754d223702983` |
| attempt-002/v2/locked-profile.json | 3787 | `941001eb053559483265827a181976ab4a390c6bd2ed4914fed497e4669c9c87` |
| attempt-002/v2/result.json | 126260 | `1c31a015de53ad720bfa7ac3e952fdbe494a8251161f5741c49239b247a53ddc` |
| attempt-002/v2/gap-inputs.json | 10301 | `75cfcaa06f1325e7f3b6c65addd1f1b5cd3356c836ae04651c78e3015a4f0b24` |
| attempt-002/v2/events.jsonl | 4996 | `abaa86c157a4a0b60f959cbd28e9f19f9d679be4cea17abe44b0e98349c40818` |
| attempt-002/execution-summary.json | 1594 | `ae8f8c88ff49c3410e1103b7d0bc889edb2b2577c9926f3e7add3c28a5c8bd14` |
| attempt-002/negative-bin-diagnostic-extended.json | 1652 | `f6521170e16d9be71626a8880cbb54a22d4b5807e6000459f526366182200670` |
| attempt-002/metrics-summary.json | 5794 | `744da0356d24faccac42d6b41c046255353c75bce25d0b1ce5362c237aafe74d` |
| attempt-001/budget.process-status.json | 727 | `bd8fab75f0c1dff2748d65c189f9c6dfff90d7d48ea7fb68b8969c1b7dc1fb55` |
| attempt-001/budget.stderr.txt | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| attempt-001/budget.stdout.jsonl | 505 | `198eea138825209eb42214cf1ecfab956b5d377d261b42597df8d261cf0635dd` |
| attempt-001/events.jsonl | 1553 | `fe858338ab233f90a4035a6259c2f8f00a895b7ccf722370d47ee96e5db4971a` |
| attempt-001/gap-inputs.json | 10301 | `75cfcaa06f1325e7f3b6c65addd1f1b5cd3356c836ae04651c78e3015a4f0b24` |
| attempt-001/locked-profile.json | 3428 | `2be56e718c72e75d4ed61b3d344fddae2992237ef84e45e0312f0a8f1ae579af` |
| attempt-001/negative-bin-diagnostic.process-status.json | 732 | `459e3a28295484faa2cee68a9f49f0b7f27585bb4379549e07d467dcd31bde61` |
| attempt-001/negative-bin-diagnostic.stderr.txt | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| attempt-001/negative-bin-diagnostic.stdout.jsonl | 1276 | `6b4c1521edaed3d6261364f274355dc96e38b81b05610be09982e2f2bab84e78` |
| attempt-002/combined.process-status.json | 732 | `a2bde43a5a350c55ca30c28c25eeef8431ad9a1ff1f337eefef62e1c2d778801` |
| attempt-002/combined.stderr.txt | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| attempt-002/combined.stdout.jsonl | 3825 | `05a1af7176bd590fcac1a44f308ea67cb5787cb1c4cfb5281f0c4a3208c05f64` |
| capture-index.json | 2871 | `9e83e9a03522fb956bdabe019ed53e17af86ac317f3726b1936e1900074e75cf` |
