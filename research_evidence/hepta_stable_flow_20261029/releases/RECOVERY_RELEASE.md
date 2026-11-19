# Verified recovery evidence release

The complete available recovery evidence contains 1,170 files (plus its manifest), 35,438,067 uncompressed evidence bytes. The scientific sources, checkpoints, exact reconstructed raw arrays, new appendices and readable report are anchored in commit `fc7d141c19703e7e104cff2a8dae5c492f034a77`.

The archive `hepta_recovery_evidence_20261030.tar.gz` is 18,821,020 bytes with SHA-256:

```text
604c2e402a1bba5c15121e9a1165a59e58e4a4322da87f73086500d7a5256423
```

All bytes are public through the nine parts in [recovery_parts_20261030](recovery_parts_20261030/PARTS.json). The contiguous download copy is excluded from Git to avoid storing the same bytes twice. The manifest, creation receipt and [independent extraction and roundtrip audit](independent_recovery_archive_audit.json) are retained here.

From the repository root:

```bash
python -I -S experiments/call_put_stable_flow_analysis/release_parts.py verify --manifest research_evidence/hepta_stable_flow_20261029/releases/recovery_parts_20261030/PARTS.json
python -I -S experiments/call_put_stable_flow_analysis/release_parts.py assemble --manifest research_evidence/hepta_stable_flow_20261029/releases/recovery_parts_20261030/PARTS.json --output hepta_recovery_evidence_20261030.tar.gz
python -I -S research_evidence/hepta_stable_flow_20261029/recovery_20261030/recovery_archive.py verify --archive hepta_recovery_evidence_20261030.tar.gz
```

The assembly output must not already exist. Use the new recovery verifier shown above; the generic part tool's printed legacy `release.py` suggestion applies to the earlier archive contract. Verification uses only the Python standard library and does not rerun scientific experiments.

This is a distinct recovery archive. It includes available originals, exact digest-verified reconstructions and explicitly new numerical and timing verification. It does not claim recovery of the missing original complete archive (`a8ce9dcc...`), original timing JSON or historical commit `b1806a2e...`, and does not claim that all scientific hypotheses passed. The final recovery audit retains `all_research_blockers_closed=false` and `original_archive_recovered=false`.
