Read-only review of #6234 exact a385c0fe6fafc513da8539799338182176a1a9f8. The independently reproduced 002 receipt checks original n128/n512 arrays, physical FD arithmetic, source/input identities and bounds without importing the numerical candidate. Zero ODE/kernel/Torch/optimizer calls. The raw 001 receipt, checker RED001, 002 receipt, tested/published inspector bytes and format witness are in ORIGINALS.tar.gz (12882 bytes; SHA256 f1caaa257d4fd29274087a8e610fa6205e612dd6c6f0dfccaa2871c73b8ad15c).

Inspector formatting includes a stdlib pathlib import reorder. Full AST equality is false; the explicitly disclosed top-level-import-normalized AST relation is true. Exact tested inspector bytes are retained, so no old execution is assigned to new source SHA. The fourteen numerical candidate source files have a separate full normalized AST equality witness and were not modified or rerun by this review.

Reproduce the arithmetic only after reconstructing the #6234 original archive into its candidate root:

python reproduce_large_review.py --review LARGE-RAW-ARRAYS-REVIEW-001.json --root CANDIDATE_ROOT --output NEW_RECEIPT.json
