# Initial local isolation attempt — retained failure

This is the original local attempt with independently trained skill parents for seeds 713, 971 and 1237. Seed 1237 was rejected at 39/48 calibration correct against the unchanged floor of 40. It was not silently retried or counted as a successful independent replication. The later isolation experiment instead explicitly fixes the qualified skill parent (seed 713) while varying project training seeds.

All 56 original files, including exact executed Python sources, the rejected checkpoint, source database, and earlier seed candidates, are retained in the indexed archive. Concatenate the 44 parts in INDEX.json order, verify each SHA-256 and the full gzip SHA-256, then extract the archive. This local attempt predates the V14 frozen CI source; source_commit is intentionally null, with exact source bytes inside EXECUTED_SOURCE. Do not treat it as an independent preregistered holdout experiment.

Candidate training measurements in the retained reports remain evidence. No missing whole-process cost is filled with zero. INITIAL_REJECTION.json and PLAN.json here are convenience copies of the archived records.
