# Frozen v1 Cell-action audit — post hoc, non-authorizing

Purpose: independently count the original decoder-token controls attributed to each of six action choices in the **immutable negative v1 test journal**. This does not claim causal Cell contributions, NDU gains, or independent text/pixel generation.

The script SHA256-pins `raw/test.episodes.jsonl` to `b9e7e0a53622b9b87e29507684684389aaf798e97bf53b0d4e93f44570786e39` (from the original 831-file portable evidence archive), requires the complete 64-source × 12-method roster at seed 23, validates control weights against action IDs, and includes every incomplete NDU episode in the decision histogram.

```sh
python -m unittest -v test_audit_cell_actions.py
python audit_cell_actions.py --journal /path/to/hepta-ndu-evidence-v1-20261022/raw/test.episodes.jsonl --output /tmp/ndu-cell-action-audit.json
```

Historical observations: 64 NDU source episodes, 139 decision checkpoints, 493 token steps with active action modifier; NDU vs mean-only has 62/62 equal quality among jointly completed episodes (the other two NDU episodes were incomplete, and are **not** removed from primary quality scores). Token argmax changes by action: no Cell 0/88, four-Cell average 16/94, vocabulary 0/75, horizontal 21/58, vertical 34/98, stop 0/80. The first and last Cells have measurable log-probability effects despite no observed argmax switch; do **not** infer they were inactive. Mixed-Cell action is a fixed equal average, **not** evidence of learned synergy. The actual decision histogram is 0:2, 2:47, 3:15, not the target 8–16 decisions.

**Acceptance status: HOLD_NO_GO.** These are descriptive *logged local argmax switches*, not counterfactual token trajectories, not independent per-Cell terminal loss effects, and not externally attested GPU/encoder clocks. This addendum does not revise the registered 768 outcomes or establish v2 held-out benefit. Source hash alone pins bytes but does not authenticate original execution.
