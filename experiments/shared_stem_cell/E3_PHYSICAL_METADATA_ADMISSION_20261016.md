# E3 original physical run metadata admission — never a Stem or efficacy gate

**Research only / DRAFT / SHADOW_ONLY / DENY_ALL.** Strict additive child of
[#2468](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2468)
at `39ccf773c36dad63ad505ffaa8f1bce8a9981b40`.

## Concrete failure mode

A GitHub Actions workflow marked `success` may have run only the
source/contract job while **skipping** OCR, native Google model inference or
the independent original TEST scoring job. Prior E3 #2349 showed exactly
such a distinction. A GitHub Actions queue may also hold an exact source
commit for hours. A green source-only check must NEVER be presented as a
complete physical five-arm success.

The independent `e3_physical_run_metadata_admission.py` reads exactly
three GitHub REST API **JSON responses** for one ORIGINAL run:
`actions/runs/<run-id>`, `actions/runs/<run-id>/jobs` with
`filter=latest`, and `actions/runs/<run-id>/artifacts`. It requires:

1. Original repo, workflow, expected exact 40-character SHA, original
   E3 research branch and **`event=push`** (PR skipped jobs do NOT count).
2. Run completed/success, valid original run ID and run attempt.
3. **Exactly five** expected jobs: source/security, original Tesseract+
   Granite97, original pinned native Google Gemma2, independent original
   OCR TEST scoring and independent complete five-arm+matched-Head scoring.
   Each must be from the SAME original GitHub run, complete and successful.
4. Every actual step in those jobs must have completed successfully. No
   skipped/cancelled/in-progress step qualifies. Require the original
   **specific** pre/post 196-file source-tree steps, original native
   pinned snapshot and actual encode/Head training, independent source
   comparison and TEST labels **after** prediction seals, in strict order.
5. Four **distinct, non-expired and nonempty** numeric artifact entries
   produced by the same run, each with GitHub Actions SHA256 archive digest:
   `hepta-e3-same-original-ocr`,
   `hepta-e3-same-original-native`,
   `hepta-e3-original-ocr-independent-outcome`,
   `hepta-e3-five-arm-source-sealed-historical`.
6. Source JSON envelopes must have no duplicate keys, overflowing JSON
   numbers, malformed SHA/digests, missing original metadata or symlinks.

## Operator workflow on an authenticated authorized machine

```bash
set -euo pipefail
REPO=TrillionniumFoundation/hepta-private-ci
RUN_ID=<exact completed ORIGINAL push run ID>
SHA=<exact 40-character commit SHA for that run>
mkdir -p e3-run-audit
gh api "repos/$REPO/actions/runs/$RUN_ID" > e3-run-audit/run.json
gh api "repos/$REPO/actions/runs/$RUN_ID/jobs?per_page=100&filter=latest" > e3-run-audit/jobs.json
gh api "repos/$REPO/actions/runs/$RUN_ID/artifacts?per_page=100" > e3-run-audit/artifacts.json
python3 experiments/shared_stem_cell/e3_physical_run_metadata_admission.py \
  --run e3-run-audit/run.json \
  --jobs e3-run-audit/jobs.json \
  --artifacts e3-run-audit/artifacts.json \
  --expected-sha "$SHA" \
  --output e3-run-audit/non-authorizing-rest-metadata.json
```

Use the original run, not the separate PR check or a previous source
commit. The three JSON responses must be obtained through an authenticated
`gh api` session with appropriate Actions read privileges. This utility
has **no network access**, no GitHub secret material and no permission to
trigger/cancel/approve any workflow. Its output is create-only.

## Narrow evidence and scientific limits

Even if this independent REST metadata gate succeeds, it **DOES NOT OPEN
or independently verify the four ZIP archive bytes**. It cannot confirm
the original model was publisher-signed or that its internal actual
Transformer forward counter is authenticated. It cannot attest true
TEST-label ownership, calibrated visual necessity, three original future
windows, negative transfer, 4,096-Cell resource scaling or target-host
p95/p99/energy cost.

The result deliberately labels itself
`REST_METADATA_ONLY_NOT_SCIENTIFIC_SELECTION`,
`original_artifact_zip_bytes_independently_verified=false`,
`resource_cost_matched=false`,
`stem_winner=null`, `production_accepted=false` and
`authority=DENY_ALL`.

An original scientific result still needs the **separate** actual archive
SHA-256/inventory verifier and source-first held TEST evaluator, plus
original model input-byte pre/post, real resource measurements and
prospective external evaluation. Passing this gate cannot enable original
NDU, FinalUse, production Stem, CAS/CNS/Worker or Cell Split.

## Testing

`test_e3_physical_run_metadata_admission.py` contains 23
synthetic-REST-envelope methods. They cover complete but nonauthorizing
metadata, queued runs, successful PR with skipped model work, missing
individual OCR/native/label score steps, wrong run SHA, duplicate jobs,
missing or invalid output artifacts, malformed numerical values and
symbolic-link file sources.

Test normal Python and optimized `python3 -O` via the dedicated
research-only Actions workflow. **Synthetic metadata passing is not a
real full physical workflow PASS.** The #2468 original physical push and
source CI remain isolated, unchanged and queued until proven otherwise.
