# Hosted attempt002 originals (evidence-only)

Exact execution source: `4b6fcf153375fb58e5a77c87c21d27569b3689c0` (tree `0359f5d49f3df5be190d3c28506de25a7b4d6682`).

GitHub Actions run `44217872325`, raw job `134512128390`, artifact `14388709067`, and execution key `hcsn-n256-corrected-t0-capsule-20261117-c06d-002` completed once. The key is consumed and must not be rerun.

The original ZIP is 22,276 bytes, has eight members, and has SHA-256 `39c63dcd7e46d842d6f911917a07bfe515147179880ed8e96f2ce6c6732ac820`. The capsule is 24,511 bytes. Independent cold parsing compared all 2,656 FP64 coordinates exactly: 2,600 current-state coordinates plus 56 packet coordinates, with zero mismatches. The run used eight candidate phase parsers, one oracle adapter, one canonical decode, two canonical encodes, one atomic publish, one independent parser, and zero dynamics, matrix exponentials, provider/model calls, Torch calls, optimizer steps, or training.

This closes only the corrected-lineage authentic warm t=0 capsule. It does not qualify cold load, N256 dynamics, the 18,225,028-coordinate / 279-frame roster, N512, arbitrary histories, checkpoint recovery, full prior, migration, full-network training, task benefit, asynchronous full cost, production adoption, or all_closed.

The precommit attempt001 remains a protocol RED: it executed before its source was committed and is not qualification evidence. Its original bytes remain under `evidence/precommit_attempt001`; its key is also consumed.

The attempt002 source was accidentally fast-forwarded onto Draft #6608's branch. No force push was used. Draft #6608 was restored by commit `d3c84b480ff3f4909b35e982ebd92f15e5075fbd` to its exact original tree `92c18900f50331a6d1472428b827e9b8fb0829b7`, while the exact execution source remains on the isolated successor branch. The workflow at this evidence head is intentionally non-runnable so PR creation cannot repeat attempt002.

Status: **HOLD**; historical RED, cancellation, and UNKNOWN records remain authoritative.
