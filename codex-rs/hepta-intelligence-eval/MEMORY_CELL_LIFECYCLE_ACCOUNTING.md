# Complete task effects before lifecycle or production claims

Base: `0f2856b6a7eded7c913a8ef448521126844bf839`. Existing code already implements
fixed-reader diagnostics, event/time/correction organization, source-written
knowledge, the ten-weight read policy and source-before-task frozen sessions.
This continuation does not claim those modules as new or retrain any model.

The next decision must use actual task outputs, not selected-source coverage.
`frozen_policy_receipt.py` binds the original plan, raw answers, frozen snapshots,
policy parameters, source bytes and model inventory. It recomputes the four
existing policy selections, verifies the exact committed results and unsigned
citation requests, and re-executes the same bounded procedural worker. Both clean
backup replay and current ancestor withdrawal are checked with zero model calls.
Original generation and verification/replay remain different events. A changed
output, partial census, unknown source or old generation relabelled as new rejects.

The pinned model run is `38067150556`, generating source `0f2856b6...`. Its status
must be successful and complete before a full receipt can be emitted. The job is
not replaced by whichever run has the best score. A pending/failed source run
makes the receipt workflow fail, with logs retained; it is not counted as an
experiment success. GitHub's authenticated artifact metadata provides the external
archive pin and the existing archive validator checks all internal hashes. This
is provenance checking, not an independent semantic review or source consent.

## Match the requested four research phases

1. Reader capability: the inherited natural-language reviewed-source set still
   lacks independent human judgments. Controlled program-support/omission probes
   can diagnose a reader but cannot fill that missing human capability evidence.
2. Organization: compare hybrid with deterministic organization using the SAME
   reader and actual task outcome. Entity/time/correction effects are not learning.
3. Learning: compare learned policy against BOTH its initial weights and the best
   deterministic organized baseline. Changing selected sources without a task win
   is counted explicitly. Source-written knowledge is a separate pending workflow;
   this receipt cannot turn policy weights into evidence of knowledge compression.
4. Lifetime: a restored output is replay, not old-task retention after new learning.
   A supplied withdrawal check is not deployed multi-host recovery. No real future
   window, independent learned snapshot or production acceptance is created here.

## Costs must remain complete and nonduplicating

`lifecycle_accounting.py` represents inclusive measurement envelopes with explicit
parentage, receipt digests and clock domains. The training interval inside writing
and the model load/inference interval inside reading do not get charged twice.
Cycles, duplicate identities, incompatible clocks, nonfinite/negative values and
children exceeding their enclosing interval reject. Caller-supplied measurements
are not externally authenticated by their names or hashes.

The actual frozen experiment records extraction, indexing/planning, policy writing,
snapshot freezing, reader loading/execution, backup copy and replay. Original
sources and full archived snapshot/index copies are retained in storage counts.
Referenced model inventory bytes are reported separately; this model-free audit
does not re-download or verify the model tensor bytes. The original pinned model
execution is responsible for those checks.

Sums across recorded phase envelopes are aggregate recorded work, not a single
elapsed wall-clock or equal-hardware claim. Shared multi-arm costs cannot be
assigned wholesale to each arm. The reuse curve is explicitly a projection of the
mixed-arm study average, NOT a learned-policy or production speedup. Unknown
maintenance and production recovery must remain null in full projections; clean
replay cannot impute them as zero. Every future query count is hypothetical.

The user objective is C_extract + C_index + C_train + N*C_query + C_maintenance,
including recovery. Known subcosts support diagnosis; they do not certify economic
benefit unless all required measurements, allocation, hardware and quality
comparability are established. No numerical claim overrides existing HNMF gates.

## Execution

```sh
python3 -m unittest discover -s scripts/memory_cell -p 'test_*.py' -v
python3 scripts/memory_cell/frozen_policy_receipt.py INPUT.zip NEW_RECEIPT.json \
  --archive-sha EXTERNALLY_PINNED_SHA256 \
  --generating-source 0f2856b6a7eded7c913a8ef448521126844bf839
```

The retained receipt workflow uses read-only permissions and the original locked
regression environment. Required format/Architecture/owner checks are unchanged.
A temporary formatting workflow can create only a separate review branch after
checking executable AST equality; its candidate removes that temporary writer.
