# Original-index source depth: posthoc attribution, not a new retrieval policy

This consumer cross-checks two already completed, exactly SHA-pinned GitHub
experiment archives (frozen retrieval grid `11700818304`, native comparison
`11700958394`). The original retrieval controls and the complete publisher
oracle responses existed **before** this analysis. The analysis is retrospective;
it cannot select a retrieval policy, create a holdout, sign a semantic ruling, or
certify any production improvement.

The 80-query label-blind grid originally froze each as-of-index top-eight and
its ordered top-64 candidates without looking at targets. A separate native
comparison contains 32 registered evaluation queries, weak native source labels,
limited publisher-oracle literal source spans, and scoped immutable SQLite
indexes. Only eight of the 25 weak-source-scored queries have a concrete
publisher-oracle *literal source* in the original response; 17 remain unknown
for rank-depth attribution. Another seven were not native-source-scored.

**Recomputed observed depth (eight publisher literal references):** five rank
within top eight; two at ranks 13 and 25 respectively; one in the original
same-scope as-of SQLite index but outside the retrieved top 64. No test labels
were used to pick or reorder a candidate. This separates possible 9-64
reranking headroom from upstream top-64 retrieval headroom. It does **not**
prove those passages are sufficient, imply answer/semantic improvement, or
establish a universal ceiling on missing sources. For the 17 missing oracle
literal spans, source rank is unknown, not zero or out of index.

The already completed simple session-diversity ablation rescues 0 weak source
cases and regresses 12 among native-scored questions. Therefore session
diversity must not be adopted merely because more sessions appear in top eight.

To replay using read-only GitHub artifacts and the original source bytes:

```sh
python3 -m unittest discover -s scripts/memory_cell -p test_stem_candidate_depth_audit.py -v
python3 scripts/memory_cell/stem_candidate_depth_audit.py GRID.zip MATRIX.zip DEPTH.json
```

`hepta-memory-stem-frontier-depth.yml` fetches the two exact ZIPs, verifies their
outer and per-file hashes, reruns this audit and stores only the historical
summary, not copyrighted benchmark originals or pretrained weights.

Research priority: run a **new label-blind upstream candidate acquisition**
comparison on genuinely unexposed source families, and a separate fixed-
frontier 9-64 reranker comparison. Preserve the original as-of, source scope,
reader, delivered token and window ceilings. Freeze proposals before opening
new test labels. Reject any strategy with more weak support regressions than
rescues; even support gains require same-reader end-to-end and independent
semantic validation before adoption.

All outputs retain `production_accepted=false`, no independent citation verdict,
no qualified prospective window and no statistical advantage over strong RAG.
