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

## Actual historical ZIP byte-audit (separate, stronger original evidence)

New source-only `e3_archive_byte_audit.py` (SHA-pinned, bounded ZIP
scanner) and its 20 negative/positive tests form a **separate layer**
from the metadata gate. The metadata gate verifies the original
GitHub API run/job/artifact **records**; the ZIP byte audit actually
opens the archived numerical files and compares cryptographic
digests and original per-case source bindings.

**Original physically completed anchors (historical, not new clean run):**

- Granite/DINO pretrained original run 38678847948, artifact 11947722496,
  ZIP SHA256
  `f421f20cdb5d35becf5e93ed63e58996d48701c2b27b979d608e2b05b6b61f30`,
  sealed prediction member SHA256
  `e6354f38de4292dda60ebab380cb13d488853b9c08371e54f8f1762827febaf7`.
- Real 192-original-image Tesseract+Granite run 38825811927,
  artifact 12027769435, ZIP SHA256
  `c80d5b9cda23a8a6ee144aeba459dc516b6b67c854c2c5fe86d3b2ba94884964`,
  sealed OCR predictions member SHA256
  `96ba4117a37689eeafe2415661e028a9170b7ccdd8c345b6b8d6241b7a928885`.
- Both sources are original ScienceQA-IMG
  `a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202`;
  original frozen Granite97 upstream revision is
  `835ad14087e140460703cf0fae09f97d469d65c2`
  and DINOv2 upstream revision is
  `ed25f3a31f01632728cabb09d1542f84ab7b0056`.

The ZIP verifier checks original archives' SHA256, bounded and safe
ZIP members, the baseline's complete internal SHA256SUMS, model
revisions and physical forward/call counts, and 64 original
source/group/sample-ID parity, including the original image-masked
negative control. It **does not read or infer the original heldout
TEST labels**.

**Already executed in the local Linux/Python container** against the
above actual ZIP bytes: all 64 original test case/group/source
triples join exactly; old OCR changed original text argmax 21/64;
learned visual gate changed 38/64; both changed on 18/64;
masked negative control is equal to text-only for 64/64; old
original 192 OCR calls (110 nonempty), 60 original frozen
Granite forward batches, mean OCR-vs-text total variation
0.010508824227240665. Output is a create-only
`DENY_ALL` report with `accuracy_observed=false`.
20 archive/source-tamper synthetic test methods passed in ordinary
Python and the same 20 passed under `python -O`. Submitted source and
tests were re-fetched from GitHub and verified byte-identical to the
actual executed local files by their Git Blob SHA values; this is
local evidence, not a new hosted CI PASS.

**Hosted exact-archive execution:** The independent
`audit-completed-historical-granite-ocr-zip-bytes` workflow Job,
separate from the 23 REST metadata tests, downloads two **previously
completed** original GitHub Actions artifacts via authenticated GitHub
API. It explicitly *does not forward the token* to the allow-listed
HTTPS storage redirect, bounds the transfer to 1 MiB and checks
both SHA256s before running the same read-only byte audit. It publishes
only the small numeric `DENY_ALL` report. It neither changes source
models nor fetches new pretrained weights.

Local equivalent (requires the two actual, existing ZIP files):

```bash
python3 experiments/shared_stem_cell/e3_archive_byte_audit.py \
  --baseline-zip original-38678847948.zip \
  --ocr-zip original-ocr-38825811927.zip \
  --out original-ocr-byte-audit-deny-all.json
```

**Important:** Historical old OCR was executed in a TEST-target-visible
workspace, so byte-validating those original predictions does NOT
retroactively satisfy the stricter #2461/#2468 TEST-redacted 196-file
input-tree evidence. This new ZIP audit is deliberately **historical
mode only**; it does not claim to validate the four future clean-model
archive ZIPs. Those need separate original provenance, 196-byte
pre/post receipts, independent held TEST label reviewer, true
four-archive cross-run byte checks, and genuine future-window
evaluation before model selection. The current extra step never
permits production promotion or NDU/FinalUse.

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
