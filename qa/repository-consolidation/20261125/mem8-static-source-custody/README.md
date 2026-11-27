# MEM8 historical source records

The v17 Fence proposal workflow and its original-job comparison, and the v14
formatter comparison, are retained verbatim as original evidence. The v17
workflow is a historical record, not a workflow enabled by this checkout.

Run the repository's `qa/repository-consolidation/20261115/restore_raw_evidence.py`
with a fresh output directory outside the checkout to recover their exact
paths and bytes. For the v17 static replay, copy the other files from the
`v17/fence013-preparation` directory to a scratch projection, overlay the
recovered files, and run its original `validate_static.py` there; the validator
writes the two derived outputs in its own directory. The frozen preparation
and publication manifests, candidate workflow bytes, and static assertions
are unchanged.
