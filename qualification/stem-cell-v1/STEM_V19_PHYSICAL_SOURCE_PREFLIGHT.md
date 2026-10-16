# V19 — physical original-source byte binding before Reader generation

**DRAFT · RESEARCH_ONLY · SHADOW_ONLY · DENY_ALL · HOLD_NO_GO.**

## Why

V14.1, V15, V16, V17, and V18 already bind the *declared digests* of
sources, requests, original Reader responses and postseal outcomes. Their
source-only unit tests do **not** read the true original private source text,
reconstruct prompt bytes, authenticate an issuer, or execute a real model.

V19 closes one bounded prerequisite: given a **pre-registered** V14 plan,
V15 decision study and V18 source-roster manifest, reread **actual bytes** from
a separate local material directory and require the SHA-256 of every original
question, source span and fully rendered model request to agree exactly with
the registered digests. It does not pretend that internally consistent private
files establish publisher authenticity, semantic sufficiency, statistical
independence, or pretrained model execution.

The previous V18 branch `e18784553d36e7d77dc1e0d147f1493a3c0a0f91` remains
an independent exact-head predecessor. This child does not edit V14/V15/V16/V17/V18
algorithms, model weights, Rust Worker, NDU, Cas/CNS, FinalUse or main.

## Concrete V19 profile

- The V19 prompt renderer is **new and versioned** as
  `hepta.stem.v19.physical-source-preflight.v1.canonical-json-evidence.v1`.
  It writes a fixed system/user/assistant envelope, a JSON-quoted question,
  ordered `[source-id]` and JSON-quoted evidence text, and JSON-quoted optional
  reasoning-state text. It does **not** guarantee that prompt injection is
  harmless. This specific renderer must be used before generating the V14 and
  V15 *study* request digests. Older V13 prompt SHAs or already frozen V14
  plans cannot be silently reinterpreted or rewritten into this profile.
- Each V14 study arm (`none`, `retrieved`, `sufficient`, `lesion`) must
  reconstruct an actual request from its exact declared ordered evidence IDs.
  `V15[root]` must render the exact V14 `sufficient` request with empty
  extra reasoning-state input. Each additional V15 node needs one separately
  staged state text file to explain its distinct model input.
- The case-local source roster binds a map of evidence IDs to actual byte
  SHA-256, and every V15 node binds the IDs delivered to that model request.
  Identical physical text cannot be double-counted as two distinct evidence
  IDs within a case or as independent source families across cases.
- One restricted material root is opened once as a directory file descriptor;
  file names must be simple basenames. Every source is an actual non-symlink
  bounded regular file. File opens use `O_NOFOLLOW` on Linux; JSON parsing
  rejects duplicate properties and nonfinite values. One file is at most
  1 MiB, all unique staged source bytes together at most 32 MiB, and one
  complete model input at most 1 MiB. There is **no silent clipping**.
- The material preflight performs **zero pretrained forwards**, then emits
  private create-only `0600` request files, one per distinct full input SHA,
  a private request index and a sanitized source-byte receipt. Files in the
  output folder may contain personal/sensitive source text and **must never be
  uploaded to the public repository or public Actions artifacts**.

The V19 manifest is an ordinary UTF-8 JSON file, with exact keys:

```json
{
  "schema": "hepta.stem.v19.physical-source-preflight.v1.material-manifest",
  "source_only": true,
  "frozen_before_predictions": true,
  "production_authorized": false,
  "v14_plan_sha256": "<SHA256 canonical V14 JSON>",
  "v15_study_sha256": "<SHA256 canonical V15 JSON>",
  "v18_source_roster_sha256": "<SHA256 canonical V18 JSON>",
  "renderer": "hepta.stem.v19.physical-source-preflight.v1.canonical-json-evidence.v1",
  "cases": [
    {
      "case_id": "case-1",
      "question_file": "case-1-question.txt",
      "source_files": {"e1": "case-1-e1.txt", "e2": "case-1-e2.txt"},
      "state_files": {"root": null, "continuation": "case-1-continuation.txt"}
    }
  ]
}
```

The JSON above shows only schema structure. Placeholder SHA fields are not
valid and the V14/V15/V18 plans must actually match rendered bytes; the
example does not prove model execution. The manifest must be frozen before
model predictions or target labels are opened. A printed timestamp or Boolean
flag is not an independently authenticated pre-registration record.

## Actual CLI preflight and private handoff

```bash
export PYTHONPATH=qualification/stem-cell-v1
python3 qualification/stem-cell-v1/v19_physical_source_preflight.py \
  --v14-plan PRIVATE/v14-plan.json \
  --v15-study PRIVATE/v15-study.json \
  --v18-source-roster PRIVATE/v18-source-roster.json \
  --material-manifest PRIVATE/v19-material-manifest.json \
  --material-root PRIVATE/original-material-files \
  --private-output PRIVATE/new-create-only-request-bundle
```

The CLI first calls **the canonical existing V18 `source_first_seal`** and
rejects invalid V14/V15/V16 predecessor bindings. Then it independently
re-reads private question/source/state bytes, reconstructs the complete
versioned Reader inputs and verifies every digest. This full validation is
required before the private bundle is written. Do not use a self-declared
`source_original=true` or caller-provided `validated=true` flag instead.

The separate model host can consume the private request index *only after its
own model weights, tokenizer, operator/runtime and executor are fully pinned
and independently admitted*. It must create authentic original Reader output
receipts and account for actual CPU/GPU, token and recovery costs. The V14
candidate/reference Reader pair still needs **two distinct real authenticated
models** and a separate *postseal* independent source-level evaluator.

## CI and source-only validation

The dedicated exact-head read-only workflow executes ordinary and `python -O`
source/test checks on Python 3.12, plus inherited V14/V15/V16/V17/V18 suites
using the real repository files. Its fixtures physically read and hash *fake
sample files*, not original LoCoMo/MultiRC source or archived model weights.
Isolated local Python 3.13 source-only tests: **28/28 and 28/28 optimized**.
Hosted exact-new-head matrix and blocking-ci may pass or fail independently.

The same increment repairs one **observed, genuine CI environment blocker** in
`.github/workflows/hepta-neuron-next-round-matrix.yml`: the CPU matrix imports
`safetensors.torch`, whose pinned test environment lacked its required
`packaging` dependency. Explicitly install `packaging==25.0` and perform a
real import assertion. No source tests are skipped, loosened or expected to
pass solely because the missing import has been fixed. Remaining cargo-deny,
Prettier, Bazel and matrix test failures require their own investigation.

## Mandatory NO-GO boundaries

`physically_rehashed_input_bytes=true` certifies only equality between local
physical bytes and *registered digests*. The source issuer, completeness,
semantic evidence necessity, model host, evaluator identity, temporal source
independence and final answers are **not authenticated**. One complete
V14 candidate+reference execution and multiple truly independent future
windows are still missing. This is not a demonstrated NDU benefit, neural
reasoning emergence, new modality generation, safe Cell Split, or any
10T/100T behavioral-equivalence result. All promotion, FinalUse and production
flags remain **false**.
