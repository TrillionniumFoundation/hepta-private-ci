# Source-only two-hop curriculum: bounded order ablation

This is an **opt-in research scheduling control**, not a new Memory OS,
independent source collection, retriever, Reader, or production adoption.
The old `original` strategy remains the default with the same plan bytes
and source-only question targets. The `direct_interleave` strategy is legal
only with `source_two_hop` and `completion_ce`.

Earlier source-only composition prepended two-hop examples within each scope.
Under the **unchanged 128-update and 65,536-input-token ceilings**, a large
two-hop prefix can leave direct current-source facts with zero optimizer visits.
The new source-only scheduler interleaves one direct and one two-hop example
per scope, retaining all original candidate identities, sources and complete
examples. It does not read evaluation queries, downstream answers, or human
review decisions. It never silently truncates a sample or skips an over-budget
scheduled step. Scope-round-robin and the old optimizer/loss remain unchanged.
This is a **training-order/coverage** intervention, not an encoder, adapter,
ranking or decoding change.

The coverage audit independently reconstructs both the ORIGINAL group digest
and the re-ordered digest. It verifies all original question IDs, scheduled
indices, source kinds, token counts, and unvisited candidates; corrupt
receipts fail closed. No missing source-only example is called unanswerable.

The existing source-preflight workflow now runs original single-hop, original
two-hop and interleaved two-hop on the SAME immutable controlled corpus and
fixed publisher Qwen tokenizer. It writes source-only exposure and token
measurements before ANY pretrained weight is loaded. Differences in direct
visits are not task gains, and differing actual input-token counts must be
reported rather than described as matched FLOPs. A real matched Reader
experiment would require independent saved writers and exactly matched
source/evidence/decoder and a frozen task cohort.

```sh
python3 -m unittest discover -s scripts/memory_cell -p 'test_source_schedule_interleave.py' -v
python3 scripts/memory_cell/source_write_schedule.py SOURCE.json /tmp/source-original \
  --source-sha SOURCE_SHA --curriculum source_two_hop
python3 scripts/memory_cell/source_write_schedule.py SOURCE.json /tmp/source-interleave \
  --source-sha SOURCE_SHA --curriculum source_two_hop --strategy direct_interleave
```

No new task success, citation entailment, independent longitudinal observation,
statistically significant RAG advantage, or production certification is
claimed. `production_accepted=false` still applies.
