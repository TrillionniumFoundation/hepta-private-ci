# Frozen cohort admission follow-up — 2026-11-05

Parent source: `379c21c2e625c3a3dfbb514e11b9e8fe2213cda8` (PR #4817).
This extends the existing V15 research evaluator. Native Rust execution and the
single-authority protocol are unchanged. Existing V14 negative results and the
original 53-case receipts remain historical observations of their recorded source.

## Corrected admission gaps

`prospective=True` alone no longer permits adoption. `MatchedEvaluator` freezes a
host-owned `registration` before predictors run and binds its digest into the
`hepta.memory.matched-admission.v15.cohort-v1` report. Missing registration still
permits diagnostic scoring, but returns no qualified cluster count or approval.

The registration must bind the exact final cases, protocol settings, frozen
candidate/control comparison roster and each arm's memory, legal training input,
executor, budget, encoder, decoder and tool-permission identities. The last three
identities are now explicit `Run` fields; different privileges reject even if
both are accurately declared. Training, calibration, selection and final source
clusters must be disjoint. Nonfinal observations precede the declared candidate
freeze; the final window starts strictly after it. Every case must match one
source unit, cluster and observation time within that final window.

Repeated node observations must retain their original source task identity.
Duplicating a source task under ten case or cluster names rejects the cohort;
`qualified_clusters` is null. Distinct steps within one declared rollout may be
retained, but their effective sample size remains one cluster. Discarded or
duplicate executions remain costs in the existing complete-attempt cost receipt.
Only a trusted source registry can establish that two identifiers are truly
independent: this implementation cannot discover deliberately falsified provenance.

The fixed error budget is divided across registered candidate comparisons,
`Protocol.planned_looks` and the overall plus required-stratum bounds. A look index
outside the planned range rejects. This is a finite union-bound protocol; it is
not an anytime-valid guarantee. The host must persist the registration, enforce
the look schedule and account for all searched candidates and inspected windows.

## What this does not establish

Timestamp declarations, component IDs and a digest do not authenticate the host,
prove chronology, enforce model input permissions, sandbox execution, or certify
cluster independence. Resource measurements and their horizon remain trusted;
unknown energy/storage/network or failed-search costs still prevent admission.
These controls do not train a language model or establish a beneficial split.

A useful structural study still needs the parent, equal-total-parameter single
head, two heads with fixed routing and two heads with learned routing, alongside
merge/retire/no-change proposals. Direct retrieval, centroid/ridge, frozen-embedding
routing and a small adapter remain required scientific controls. They need the
same lawful information and decoder/tool access, actual lifecycle accounting and
an independently collected future cohort. The original V14 negative verdict is
not changed by successful control tests.

## Reproduce

Use the repository's pinned Python dependency:

```sh
python -m pip install -r qualification/memory-cell-v15/requirements.txt
python -m unittest discover -s qualification/memory-cell-v15 -p '*tests.py' -v
python -O -m unittest discover -s qualification/memory-cell-v15 -p '*tests.py' -v
git diff --check
```

The source includes 14 new behavioral controls. All positive examples, provenance
registrations and costs in these tests are explicit synthetic fixtures. The
existing same-host process, crash, revocation, structure and verified-byte
integration tests run alongside them; no test is skipped or transformed into a
scientific efficacy sample. Use the commands above to avoid overwriting the
historical `evidence/checks.*` receipts with `verify.py`'s default output location.
