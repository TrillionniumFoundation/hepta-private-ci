# Complete local evidence inventory

The reviewed inventory CLI completed after all experiment producers stopped writing. It scanned exactly the three authorized task roots. No evidence was copied, compressed, archived, or uploaded.

**47,770 regular files; 5,448,401,856 logical bytes (5.074220 GiB); 1,258 directories.**

All regular files were included without filename exclusions, including existing failure records, raw media, weights, and checkpoints. The metadata census, no-follow path checks, and per-file read checks passed. Logical sizes count each listed path; hard links are not deduplicated. Quiescent producers were required; this is not an atomic filesystem snapshot.

## Root distribution

| Root | Files | Logical bytes |
|---|---:|---:|
| abc2-assets | 1,002 | 194,125,554 |
| abc2-runs | 46,767 | 5,254,183,627 |
| runtime-receipts | 1 | 92,675 |

## Run distribution

The root-files bucket contains files directly under `abc2-runs`; each other row is a complete immediate run directory.

| Run | Files | Logical bytes |
|---|---:|---:|
| (root-files) | 12 | 56,067 |
| analysis-001 | 5 | 2,116,572 |
| base-recovery-001 | 16 | 6,902,723 |
| causal-av-codec-pilot-001 | 28 | 3,337,863 |
| causal-av-evaluation-001 | 2,891 | 653,309,116 |
| causal-av-evidence-audit-001 | 1 | 344,291 |
| causal-av-fit-001 | 91 | 3,585,402 |
| causal-av-qualification-001 | 470 | 118,203,646 |
| causal-av-static220-diagnostic-001 | 7 | 941,748 |
| causal-av-static220-fixtures-001 | 6 | 32,411 |
| causal-av-static220-fixtures-002 | 3 | 2,399 |
| control-001 | 11,136 | 3,102,545,351 |
| control-audit-001 | 29 | 812,249 |
| cost-analysis-001 | 5 | 1,281,666 |
| qualification-001 | 11 | 1,749,154 |
| resume-verification-001 | 25 | 38,659,922 |
| source-recovery-001 | 2 | 5,924,206 |
| timing-registered-three-001 | 8,648 | 33,043,825 |
| timing-supplementary-all-001 | 23,048 | 87,816,396 |
| training-001 | 310 | 1,193,361,563 |
| training-audit-001 | 23 | 157,057 |

## Identity and location

- Detailed local manifest: `/workspace/scratch/2b3c256bef7d/evidence-inventory-001.json`
- Manifest bytes: 10,582,422
- Manifest SHA256: `fee203e32ba48cccb6725bb9ad1204f76b939e8660440dfafcd99955486b2e9a`
- Census SHA256: `1ee11854fd8b7d3c7e997868bc22aa55b3020a4eec21ec46e323c0cfc7e87871`
- Local process receipt: `/workspace/scratch/2b3c256bef7d/evidence-inventory-001-receipt.json`
- Receipt SHA256: `17de0e07d079a8d247224064acadabea4e7de3fdcc1ce31ca14e2b6eb45f8251`
- Reviewed inventory implementation SHA256: `0d39bffcc7398a3ba039974b408163c244103ad161b97e3107b00eb41062182c`
- Exact invocation source SHA256: `8aa0298842a072f54b3a1d990cd510e3c869eb5cc4bebf97fd0769a49ad9c3b8`

The detailed per-file manifest remains local and is not included in this repository review. `execute_inventory.py` preserves the exact invocation and receipt wrapper. `review.json` contains only aggregate counts, identities, and costs. External evidence export still requires separate explicit authorization.

## Actual cost

| Scope | Wall seconds | CPU seconds |
|---|---:|---:|
| Initial census, streamed hashes, first final census | 10.459832522 | 7.898209329 |
| Complete inventory call, including manifest publication | 10.837811002 | 8.260035433 |
| Complete CLI child process, including Python startup | 10.898054216 | 8.319897000 |

Child peak RSS: 137,850,880 bytes. Exit code: 0. These are nested scopes of the same scan and must not be added together. The small subsequent aggregate review is outside the recorded scan cost.
