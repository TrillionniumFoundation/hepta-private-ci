# Separate train2017 metadata preflight candidate

**PROPOSAL ONLY / HOLD_NO_GO / DENY_ALL.** This is not P44, not a prospective
registration, not an image-acquisition builder, and not a scientific admission
gate. It cannot choose a seed, allocate a split roster, download photographs or
models, fit a Head, or emit an old P44 seal. Its schema is separately named
`hepta.train2017-metadata-preflight.candidate.v1`; old consumers are not changed.

## What this stage establishes

Read only the retained official 252,907,541-byte annotation ZIP and the pinned
384-photo P39 registry. Verify their exact byte hashes, stream the entire pinned
train instances/captions and val instances members through EOF, verify each raw
member's length/hash and ZIP profile, then count complete metadata eligibility.
The train instance member's bound is 500 MiB (actual 469,785,474 bytes); captions
100 MiB (actual 91,865,115 bytes). These are separate train-aware limits, not an
edit to the old 48 MiB/5,000-image val chooser. Profile pins were measured from
the retained original ZIP, not previously preregistered as a train protocol.

Structural validation rejects duplicate JSON keys, nonfinite values, excessive
records/buffers, duplicate IDs/files/canonical Flickr photo IDs, unknown target
ontology/license definitions, orphan annotations, wrong source-partition URLs,
and disagreement between instance/caption image rosters. All dimensions and
file IDs are checked. No `assert` guards disappear under `python -O`.

Metadata eligibility retains exactly one annotated category among cat/dog/horse/
cow, license IDs 4/5, positive dimensions capped at 4,194,304 pixels, and available
original human captions. Exclusions cover P39 and **all 5,000 val2017 images** by
image ID and canonical Flickr photo ID, not merely exact URL spelling. A photo
group means `flickr:photo:<id>` only: not an author, animal, scene, or independent
sampling unit. Canonical source aliases are rejected, not counted twice.

The receipt preserves the complete eligible inventory in numeric image-ID order
**for auditing, not selection**. Each record has a partition-qualified image key,
source-group key, original source URL, metadata license ID, correct `/train2017/`
official future image URL, caption count, and digest of _all_ sorted caption-ID /
exact-text-SHA256 pairs. No caption is selected and no seed from old P44 is reused.
Human captions remain provenance, not evidence of a natural-caption-input task.

Both license 4/5 and the optional license-4-only counts are reported; neither
license policy is selected. Numeric image-license metadata is **not rights
clearance**. Per-photo creator/title/source/license/notices and other rights
remain unverified. Annotation licensing is separate from photograph licensing.
The program sets rights/scientific/production qualification false, even when
`metadata_supply_status` is `SUFFICIENT_METADATA_ONLY` and the process exits 0.
Insufficient supply returns exit 2 without weakening quotas; invalid source
inputs return `FAILED_CLOSED` / exit 2 without an eligible inventory.

## Proposed unchanged pilot and future controls (not implemented experiments)

The comparison is still **112 photographs / 224 paired question rows**: cat/dog
16/8/8/16 photographs each for experimental train/dev/calibration/test; horse/cow
8 each for OOD. The official source partition `train2017` is not an experimental
split assignment. Calibration has 16 photographs, not 32 independent examples.
Independent source units are at most 16 and independence remains unestablished.

Any later protocol must separately freeze the actual source/seed/order/roster,
caption role, ontology/negative-label scope, rule family and error definitions,
rights review, and independent source publication before dependent work. Retain
the 2 MiB per-image / 140 MiB total image budget and raw/RGB equality plus dHash
distance >=5 checks against P39 and all selected photos. These are future gates;
this candidate implements no image acquisition or fingerprinting. Any failure
must stop rather than substitute pictures or lower a quota after observation.

For eventual scientific comparisons, predeclare and audit equal source rows,
Encoder checkpoint/profile/forward work, representation width, Head parameter
and optimization-search budgets, calibration access and multiplicity across
the relevant joint, single-modality and mismatched controls. This metadata-only
code does not implement or claim those compute controls, measured quality gain,
model selection, or production safety. The old model/risk gates are not edited.

The separate acceptance-design note also remains unchanged: at delta=0.05,
M=200 simultaneous fixed rules, and a 5% source-conditional error target,
`ceil(log(delta/M)/log(1-0.05)) = 162` is only a zero-error **accepted independent
source feasibility floor**, not a powered sample-size plan. With 16 independent
accepted sources and zero errors the illustrative upper bound is ~40.45%.
This assumes a justified binomial fixed-sample model; actual independence,
acceptance probability, nonzero errors, target population, coverage/error-budget
allocation and multiplicity remain to be prospectively addressed. No larger
acceptance cohort is selected, no old risk threshold is relaxed, and repeated
looks are not licensed by this arithmetic.

## Reproduce locally without new acquisition

Use a new destination opened exclusively by a calling harness; the CLI itself
only writes stdout and never creates/overwrites a data path. Never redirect onto
an existing source or evidence file. The CLI requires a working address-space
limit and enforces at most 4 GiB; it refuses unsupported platforms rather than
claiming that limit. Record/buffer/output bounds are also enforced in code.
The local validation is Linux/Python 3.12 only, not native Windows/macOS coverage.

```sh
python -B run_synthetic_tests.py
python -B -O run_synthetic_tests.py
python -B preflight.py --archive /path/to/retained/annotations_trainval2017.zip \
  --p39-registry /path/to/retained/coco_caption_sample_v1.json
```

The CLI blocks socket connect/address resolution using a Python audit hook;
there is no download code. This hook is defense in depth, not an adversarial
sandbox or a claim that arbitrary caller-supplied Python is contained. The
library function also performs no networking, but the CLI owns the address-space
guard and bounded serialization. New task outputs must remain <=128 MiB; each
CLI receipt is capped at 16 MiB. Full train JSON members are never materialized.

The candidate is isolated from old P44. Its five reviewable stages add bounded
JSON/custody, metadata validation, exclusion/inventory, CLI/docs, then source-
hygiene guarded synthetic CI. Every stage has runnable tests; only the complete stack is a preflight.
The exact-head CI uses standard-library synthetic fixtures only: no ZIP, image,
model, dependency install, or original-metadata execution. It rejects missing or
skipped test methods and retains SHA-scoped logs without cancelling other runs.
No repository-wide Rust build, hosted CI, image/model execution, new protocol
registration, or external publication is claimed by the Python checks.

CI checks HEAD-relative tracked changes and rejects scoped status entries,
including untracked/ignored source files, before and after tests. Logs remain
outside the checkout and bytecode is disabled. This is bounded Git/source
hygiene, not runtime, runner, dependency, or adversarial sandbox attestation.
