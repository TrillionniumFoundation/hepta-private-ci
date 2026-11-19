# P1 real checkpoint evidence → P2 frozen feature-bank bridge (research only)

**DRAFT / DENY_ALL / HOLD_NO_GO.** No selected model, no artifact signing, no
FinalUse, no CNS route cutover, no NDU selection, no physical Cell Split.

## Upstream *real* execution, verified 2026-10-17

Original GitHub source HEAD `b2ac32e34dc0c69d5cb57db7ae7a2ea718bb910f`
from [PR #2579](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2579).
Workflow [39034514849](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39034514849)
completed SUCCESS. Independent named jobs:

| Model | Job | Source and CPU-forward artifact | GitHub artifact ID | Original ZIP SHA256 |
|---|---:|---|---:|---|
| Ettin original 400M class | 117430936595 | 5 files + weights-only original CLS | 12108091511 | `c40d8c2f7610d55f2447d65845b4e6cb488e2b26af2f39a7a8d46127c5d30b1a` |
| Laya original 421M | 117430936593 | 5 files + native `noul` probability | 12107424477 | `41e31a2d34cc6a4e2a9c411953aa28a273b21a3b7406602fd216581754d209fd` |

**Independently opened and validated all four original JSON receipts** in
both downloaded GH artifact ZIPs; original run and ZIP sha are frozen above.
All original reports declare no issuer signature, held-task accuracy, equal-head
training, model promotion or Cell Split. Both reported **one genuine frozen
Encoder CPU forward** from fully SHA/LFS checked source bytes.

| Metric | Ettin | Laya |
|---|---:|---:|
| Original loaded parameter tensor elements | 447,458,496 | 421,293,827 |
| Original selected files, combined bytes | 1,585,736,960 | 846,195,574 |
| Input tokenizer output tokens | 37 | 42 |
| CPU ns from original model-loader/execution scope | 14,019,161,193 | 9,167,183,494 |
| Wall ns from original model-loader/execution scope | 23,009,297,927 | 11,157,527,648 |
| Linux peak RSS KiB (whole process, self-reported) | 3,465,736 | 2,855,496 |
| Output type | 1024-D frozen CLS SHA256 | native `noul` probability 0.6782 |

- Ettin has **6.21% more observed tensor elements** than Laya, notwithstanding
  their published nominal class names. A 4,161-param identical Head is not
  proof of same total model, compute or lifecycle costs.
- CPU/wall/RSS values are **single-run self-reported and include model loading
  and runtime snapshot copying**; different input tokenizers and model outputs
  make speed or semantic quality comparisons unsupported.
- Original Laya emitted a warning about invalid saved temperature calibration
  entries (a `choice:11+` bucket, separate from this `noul` probe). Do not certify
  all Laya confidence calibration from a successful native forward.
- Original model source-LFS/Git checks and double local hashes are *not*
  independently cryptographic publisher signatures.
- P1 2-arm forward artifacts have no FIT/CAL/TEST sample bank and no held labels.
  They do **not** establish that a replacement model is better.

## New read-only contract

`physical_evidence_review.py` independently reads exactly the two **pinned
GitHub artifact ZIP bytes** above; refuses other SHA, alternate commit, extra
ZIP members, symlinks, nonfinite or duplicated JSON, changed authority claims,
wrong source/forward identity, impossible output types, forged training/held
scores, and changed CPU/token/tensor metadata. It emits only a create-new
`HOLD_NO_GO` combined physical evidence record. This is a second independent
parser and check of *original P1 self-reports*, not a second P1 model forward.

`physical_feature_bank.py` is the next execution stage for two original models:

1. Ingest a separate source-owned **label-free** `gate.SCHEMA` panel plus exact
   `hepta.stem.equal-size.original-input-views.v1` evidence/question/
   ordered-options source manifest. Require all source SHA, full view SHA,
   original group/split, original dataset snapshot and budgets to match; any
   label/target/gold/calibration field causes a hard deny *before model imports*.
2. Require P1's original signed? **No:** pinned, double-hashed local source
   receipt, then copy only allowlisted weights/tokenizer to an isolated runtime
   directory with another full byte review. Models never get unreviewed stage
   files. No remote model code, unpinned `from_pretrained` or pickle loading.
3. Load the **real** original Ettin with `torch.load(weights_only=True)` and exact
   tensor key/shape checks, or the real native Laya 0.3.20 encoder. Run every
   ordered question/evidence/two-option input without silent truncation, one
   original Encoder forward per case, record original tensor counts, actual
   model-specific input tokens and process CPU/RSS/wall.
4. Export only an owner-private create-new 0600 frozen FP32 feature bank that
   matches P2 `matched_head.validate_bank` and a small no-authority cost report.
   Raw original evidence is **not** included in feature banks or GitHub
   artifacts. Do not print, upload or persist FIT/CAL/TEST features publicly.
5. Pass original private banks to the already implemented 4,161 parameter,
   40-step independently replayed P2 Head. A fully independent publisher-label
   evaluator and negative/future source windows must remain separate.

There is **no** original source-owned `panel` + case-view manifest attached to
this PR, so this new bridge has *not* yet produced genuine multi-case 421M/447M
bank features. The new source-only tests use tiny synthetic case views and
mocked model drivers, not a physical pre-trained Encoder; never count them as
true model forward or utility evidence. The code is executable for the
source-owned inputs above, but the P1 original real single-probe evidence is
**not** secretly reused as an original multi-case benchmark.

### Independent local verification

```bash
# After downloading original GitHub Artifacts 12108091511 and 12107424477:
python physical_evidence_review.py --ettin original-ettin.zip \
  --laya original-laya.zip --out original-two-model-audit.json
python -m unittest -q test_physical_evidence_review test_physical_feature_bank
python -O -m unittest -q test_physical_evidence_review test_physical_feature_bank
```

No production or original-publisher credential is used, stored or minted here.
The upstream `blocking-ci` is still **FAILED** on Rust advisories (including
`RUSTSEC-2026-0318/0319/0346`–`0349/0367`–`0369`) and Bazel jobs. Do not
ignore vulnerabilities or relabel a global failure as green. Changes to base
Rust dependencies or production integration require their own owners/gates.
