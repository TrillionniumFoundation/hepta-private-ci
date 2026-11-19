# Two fixed HX model identities (research only)

Additive opt-in package on exact #4663 commit `c418deeb670a1e5a52970e3a8b10fe95c75618a1`.
The sibling `local_equity_research` and production/default HX code are unchanged.
Only the two exact rational dictionaries in REGISTRY.json are supported. This is
not parameter generalization or a repair to the original default numerical model.
The second model's initially reused default label and stale proof paragraph are
retained in audit/; corrected proof is sources/second/PROOF.md. Default proof is
../local_equity_research/PROOF.md. Both roots, coefficients, frozen local domains,
Taylor/IEEE operation-order bounds and exact parameters are tied by the registry.

## Explicit use

Optional Python dependency: `python-flint==0.9.0`. From this directory:

```
python -B prepare_bundles.py
python -B research_contract_tests.py
python -B generate.py bundles/default
python -B generate.py bundles/second
```

No import from production, default test discovery, workflow or runtime is added.
The tests replay both root/coefficient computations, compare the old/new kernels
and 14 asset outputs bitwise, and exercise 47 finite rejection checks. Proof replay
writes replay/ and test receipts locally; these are not required runtime inputs.
Source paths are anchored to this package's __file__, independent of launch cwd.
The default source is the unchanged sibling package; the second source is bundled.

## Contract and limits

Canonical JSON is UTF8, sorted keys, compact separators, allow_nan=False. Exact
parameter strings only; no float/rational-spelling coercion. Duplicate keys,
nonfinite values, missing/unknown fields, wrong model/domain/threshold/version and
cross-model receipts reject. Only exact top-level elapsed_seconds (root) and
precompute_seconds (coefficient) are excluded from receipt hashes. Runtime byte
identity is checked without importing changed code. JSON input is bounded to
128 KiB and strict UTF8. Validation precedes atomic local emission.

This is trusted-local identity/version consistency, NOT a signature, authentication,
malicious-artifact verifier or general mathematical certificate. Trusted code,
registry, FLINT and the original CPython IEEE binary64 nearest-even assumptions
remain necessary. No concurrency/TOCTOU, hostile-directory or crash-durability
claim. Runtime does not revalidate proof files each call; no later mutation is
assumed. Relative error bound is 2^-49 only on each fixed inward-rounded asset
interval with exact-root log distance <=2^-19; global status stays NOT_CERTIFIED.
No clamp, production gate, arbitrary-model fallback, benchmark or global guarantee.

PROCESS.md records the initial execution-before-implementation-review gap; later
acceptance is not retroactive approval. The byte-identity CRLF defect was repaired
and implementation-approved before the corrected replay. audit/ reviews are
historical local provenance, not acceptance of this relocated package. Packaging
acceptance is separately recorded in PACKAGE_REVIEW.json after independent review.
