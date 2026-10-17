# V27: label-late original ScienceQA conditional vision replay

**DRAFT / SHADOW_ONLY / DENY_ALL / NO_MODEL_WINNER / NO_MAIN_MERGE.**
This is a cumulative research-only child of PR #2537 (V24); it neither
changes the selected production Stem nor modifies Neuron, NDU, CAS, CNS,
Worker, FinalUse, or original E3 pretrained weights, source cohorts, model
outputs and published historical results.

## Exact scientific hole

V24 independently audited the complete original physical 64-case ScienceQA
prediction archive, but original **per-case answers were absent from that
archive**. Consequently a fixed text-margin `< 0.005` route that would ask for
vision for 21/64 cases and change 19 answers had only an identified historical
accuracy range of 5/64–33/64, not a measured route accuracy.

## New executable bridge

- A label-blind `seal` step verifies the **complete original ZIP bytes**, inner
  member digests, historical Head, original 64×8 four-class score vectors,
  original reviewer consistency, then seals each case's choice and modality request
  using a fixed original threshold. This create-only 0600 plan is **not
  published**; it is committed to disk before original TEST labels are touched.
- A label-late `review` step reacquires the **same pinned public ScienceQA-IMG
  revision** using the original E3 source staging algorithm, regenerating
  **exactly the same 192 source rows and 64 heldout answers**. Original source
  and held-target JSONL **complete byte** SHA-256 must equal the archived E3
  source and private-target seals or execution stops. No approximate case join.
- The consumer rederives the entire label-free plan from the original archived
  model vectors, then joins all 64 original per-case labels. It independently
  recounts correct cases for **all eight archived inference arms** and their
  paired rescue/harm totals, checks the published original review, and only then
  reports the exact historical conditional policy accuracy and nominal paired
  binomial statistic. Failure in *any* historical arm aborts publication.
- Only sanitized aggregate numbers are eligible for uploading. Original images,
  questions, per-case labels, model weights, private per-case routes and raw
  original outputs stay outside the repository and final artifact.

## What this result will NOT imply

This is **retrospective lookup of PREVIOUSLY EXECUTED, ALWAYS-ON full vision
model outputs**. It does **not** run the vision Encoder only on triggered cases,
prove saved FLOPs or energy, estimate genuine conditional p95/p99, demonstrate a
causal modality necessity label, add independent publisher datasets or future
windows, certify production authority, or show a Cell Head better than a cheap
matched baseline. Do not call the source re-download independent human ground
truth. The same historical TEST panel has been inspected by earlier research;
reported statistics are descriptive and do not establish model superiority.

## Source and negative controls

- Source parent: PR #2537, `research/stem-v24-multimodal-identification-20261016`
  at `7a896f3e304bd320f64de72c966002247f1972e3`.
- Original inference: Actions run `38672941350`, artifact `11945106672`;
  `b8b2f10fe38506972301e77e3836729a90200673`.
- Archive ZIP SHA-256 `7807b82d6c747b0b13666b330145e3801a8c8a0aadeee3f2ff7ab5f5c8c00a30`.
- Original sealed predictions SHA-256
  `c91824b378357c60f6272b785233854eaa762efd8fadc421bf99b996a58dd8e4`.
- Original complete source JSONL SHA-256
  `a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202`.
- The TEST label SHA-256 is read from the **pinned original archive's**
  `source-seals.json` and independently enforced against downloaded original
  source material; it is not an invented label certificate.
- Python source-only suite covers route replay, exact all-arm recount,
  changed routes/policy, invalid probabilities, source drift, label mismatch,
  forged original reviewer, untrusted authorization, duplicate entries,
  canonical JSONL and create-only evidence handling.

## Ordered steps and rejection rules

1. Run source-only tests and freeze an exact Git SHA. On same-repo branch push,
   retrieve the original artifact by numeric ID and verify the entire ZIP bytes.
2. Run `seal` before dataset/label retrieval. Persist private per-case plan via
   `O_EXCL`, fsync. Never upload plan or original outputs to GitHub artifacts.
3. Download and stage exactly the pinned original dataset. Require full original
   source membership and original held TEST label SHA-256 equality.
4. Independently rescore eight original arms plus the fixed label-blind
   conditional route. Publish **only** the aggregate HOLD result if all 64
   case identities and all historical published arm metrics match.
5. Follow with a separate physical conditional-vision experiment on a new
   source/time cohort, with native Worker forwards, signed artifact/authority
   receipts, matched costs and independent utility/retention. This experiment
   does not remove any existing `blocking-ci` or lifecycle blocker.

## Reproduce source-only contract tests

```bash
cd qualification/stem-cell-v1
python -m unittest -v test_v27_conditional_vision_replay
python -O -m unittest -v test_v27_conditional_vision_replay
python -m py_compile v27_conditional_vision_replay.py test_v27_conditional_vision_replay.py
```

Original reenactment requires the exact E3 archived ZIP, original frozen dataset
material and a SHA-pinned source owner. No synthetic fixture or missing material
may be replaced with success.
