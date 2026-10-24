# Reproduce the posthoc audit

Run `python3 reanalyze_published_evidence.py` in this directory inside the repository. The script imports only Python standard-library modules. It trains no model, makes no provider call and does not read a network.

Large V3 ledger/report inputs are read from the exact local Git objects at `4b3081c25af86f707a5c0d50c688c959a04af446`; `EVIDENCE_INPUTS.json` fixes both stored and decompressed hashes and lengths. This branch descends from that revision, so the objects are part of its normal history. A shallow checkout must obtain that original revision before reproducing. No missing object triggers an automatic network fetch or a model rerun. Other small audit inputs and the exact executed source bytes are retained alongside the script. The Python source copies are historical byte-for-byte audit inputs, never imported or executed.

The root review removed a future import from the newly authored audit script and added the read-only Git-object resolver. It reran all arithmetic; every diagnostic value was unchanged except the explicitly recorded script SHA256. The original agent manifest is preserved as `AUDIT_MANIFEST.original.json`. This is retrospective diagnosis of exposed evidence, not new acceptance, a new confidence interval or a causal intervention.
