# Independent-source eligibility preflight (research only)

Previous #1875 video experiments repeatedly used ten pinned small clips. Their
calibration/holdout scores are **exposed exploratory observations**, not new
independent confirmation. This add-only research gate fails closed before any
new label access, and deliberately changes no existing experiment, video CI,
production routing, CURRENT pointer, model weights or authorization.

Run (stdlib only):

```bash
python -m unittest discover -s qualification/stem-video-independent-source -p 'test_*.py' -v
python qualification/stem-video-independent-source/source_gate.py \
  --plan /path/to/prelabel-plan.json \
  --prior-sha256 EXTERNALLY_PINNED_SORTED_PRIOR_SHA256 \
  --output /new/preflight-report.json
```

The plan must contain exactly: schema, prior_source_ids, candidate_sources,
candidate_revision (immutable 40-character Git commit), candidate_repository.
Every candidate has source_id, media_sha256, split (train/calibration/holdout)
and group_id; **no labels, model predictions or performance estimates allowed**.
Hashes are lowercase SHA256 hex. The prior inventory's externally pinned
digest is SHA256 of compact JSON of the **sorted prior source IDs**.

Minimum two distinct source-family groups per split, with no group intersection
across splits, and no duplicate candidate media or candidate/prior source IDs.
There must be at least ten prior source IDs and six new candidate records.
Incorrect inventories fail, never silently replace samples. The output is
create-only; no model or label is accessed.

Important limitations: source IDs must be established from a trustworthy
publisher provenance process, and previous family overlaps beyond the supplied
ten items are not detected. Hash equality is not semantic duplicate detection.
This script does not download or verify publisher media bytes, establish
licensing, check pretraining contamination, prove independent sampling,
or establish quality/retention. Pass is **identity eligibility only**.

Until truly new independent-source records are acquired, verified, and
prospectively evaluated, maintain the prior **NO CERTIFICATE / research Draft**
status. Existing queued real-CLIP CI cannot be counted as success.
