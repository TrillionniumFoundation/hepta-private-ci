# PERC frozen-source reuse guard
This engineering-only check rejects identical original-document SHA-256 group IDs reused across any TRAIN/DEV/confirmation role in earlier published PERC manifests. It requires prior manifest byte hashes; it never reads sealed targets.
A clean group audit is PASS_GROUP_REUSE_CHECK_ONLY, not scientific PASS. Missing earlier campaigns, group-to-original provenance, templates, organization independence, preregistration, actual independent training, evaluator security, production ownership and costs remain unverified.
The 32 previously published confirmation documents in qualification/perc-real-producer-20261109/MANIFEST.json must not be relabeled as fresh independent evaluation.
Run with python scripts/perc1_source_reuse.py --candidate NEW_MANIFEST.json --prior OLD_MANIFEST.json PINNED_RAW_SHA256 --output FRESH_REPORT.json.
A duplicate/reused group yields exit 2, malformed input fails closed. Never overwrite an existing audit report.
