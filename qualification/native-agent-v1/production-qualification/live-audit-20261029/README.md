# Representative live audit, 2026-10-29

Read [LIVE_AUDIT_20261029.md](LIVE_AUDIT_20261029.md), [FAILED_CALLS.md](FAILED_CALLS.md) and [CONTROLLED_INPUT_PLAN_20261029.md](CONTROLLED_INPUT_PLAN_20261029.md). This append-only update preserves the earlier frozen source/results and supplies the actual outcomes. It does not change the old `behavior_matched` or `individually_optimized` labels in the raw records.

The first label is application-task matched, not byte-identical model input. The second is a candidate configuration whose new limits were not binding, not an established optimum. Results are 9/12 and 5/12. All ten live task failures hit the sixth valid new tool proposal against the five-admission budget. No provider response.incomplete is implicated.

All three long-output physical jobs produced the same complete 1,179,648 bytes; only one harness completed inside its observation budget. Keep owner execution success separate from harness task success. No general latency, p95, memory or system-cost superiority is established.

The native binary was built from the published source and pinned Runtime revision. The archived build metadata and test stdout/stderr retain their precise scope; post-live full model and library identities are separately captured. Production replacement remains held.

## Reproduce the local audit

Run `python3 restore_raw.py`, which restores to a new `raw` directory adjacent to this file and verifies the full manifest. Then run `python3 audit_live.py` and `python3 audit_supplement.py`. These scripts only inspect the frozen evidence; they do not start model, tool or owner operations. The exact precomputed derived files are included for review.

The canonical-initial document is a proposed next experimental policy. No executed canonical-initial result is claimed by this publication.
