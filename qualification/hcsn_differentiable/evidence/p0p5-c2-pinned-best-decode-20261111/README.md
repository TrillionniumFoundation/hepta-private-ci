# Original HCSN C2: two SHA-pinned best.pt decode-only check (2026-11-11)

**Draft / HOLD_NO_GO / no original writer resumed.** This supplements, and does not replace, the six-attempt frozen structural inventory in #5920 and independently read-only reconciled evidence in #5945. The original job `1a1c74f3308-be2a-75` remains finalizing / terminal unknown. Its four producer `result.json` records, two zero-byte `interrupted.pt`, missing controller `RESULT.json`, 16 complete journal rows and torn seventeenth record remain original failures, unchanged.

## What was tested

A new *separate* read-only verifier `recovery_v1/c2_pinned_best_decode.py` reads the frozen original eight-file manifest (original blob `5a258598ba60754776902e3f7b58146766c02a74`, SHA-256 `ced4684a427b255e5686aae2f88fee27e6b2edc40cf31d48516a700158259abf`), verifies both exact original `best.pt` SHA-256 and size **before** loading the file with `torch.load(..., weights_only=True, map_location="cpu")`, and checks frozen job/root/attempt IDs, 23 finite model tensors, finite optimizer tensors, optimizer and RNG structure, seeds, counter bounds and original data manifest `0eb233da8d0b766c35356ba450d0572f1e6a87a47f1d8a17cd32c2ae6f25a1cb`.

The two producer-incomplete candidate *best checkpoints* were independently decoded with **no model forward, optimizer step, resume, complete trajectory, downstream B assessment or training terminal**:

| Original candidate | Original best.pt SHA-256 | Size | Retained epoch | Retained updates | Decoding |
| --- | --- | ---: | ---: | ---: | --- |
| s211 / lr0.001 | `a83e259366c76f1f3856c4be1291d2e842d32b283c661f656ae44fd156b37b3c` | 450,552 B | 124 | 1488 | pinned `weights_only` decode |
| s307 / lr0.001 | `14a9c527bf87ad6524c771ab7da5a1ccf32723cd1f2fc6c7d8f6d8797d1b2ed9` | 450,552 B | 126 | 1512 | pinned `weights_only` decode |

Independent output: [READONLY-DECODE.json](READONLY-DECODE.json), SHA-256 `d03e191481b794352aaf5e0201baf407c818581c28c71b5073dbb8dee85e5473`. **2/2 best.pt structurally loaded, still 0/6 complete training independent replay, 4/6 producer result.json, 2/6 missing producer results; scientific admission HOLD_NO_GO.** These `best.pt` files do not reconstruct the two latest interrupted states (both `interrupted.pt` empty).

## Exact native red/green lineage

- `desktop`, original Python `/home/qian-qi/hepta-hcsn-trainer-20261108-s3-v1/dependency-recovery-v2/venv/bin/python`, Python 3.12.3, torch 2.8.0+cu128, CPU-only `map_location="cpu"`.
- A preliminary independent *read-only* original two-file decode job `1a1c9de0510-2564-32f` exited 0 and established both the original archive structures. The new verifier regression job `1a1c9e0488a-2564-337` passed 10/10 synthetic tests.
- First real-inventory verifier job `1a1c9e302cb-2564-340` **FAILED**, with 0/2 decoded: the verifier incorrectly required exactly `dict` and rejected legitimate PyTorch `OrderedDict` model state. The source manifest copy was also one newline short, and its SHA-256 did not match the frozen blob.
- After a *fresh isolated copy* of the frozen manifest was fixed to its exact original SHA-256 and the verifier was corrected to permit `OrderedDict` safely, native job `1a1c9e5a665-2564-34f` exited 0: 10/10 tests and **2/2 pinned original best.pt decoding**. Added a dedicated native `OrderedDict` regression; job `1a1c9e6772d-2564-351` exited 0 with **11/11 tests**.
- Exact native-tested SHA-256: verifier `85c4726d86ea30019fdcc7567b06878d8ac6cb19bde2c88431850d97fb7c3549`, test `37f7aa149dcabedd9f5cee8d0712b7b590d29f8eae1123d1b2ebd424f1c28526`. No changes were made to other worktrees, original source, original weight files or original controller.

## Limits and next acceptance

GitHub HCSN test CI must independently run the new tests on the **exact PR source**. That still cannot prove native full C2 terminal, complete resource bill, train-visited numeric accuracy or scientific benefit. P0/P1/P2/P3/P4/P5 stay HOLD_NO_GO pending verified common-source P0, whole posterior/rare-tail/gradient P1, six *new* durable-runner/controller complete and independent replay outcomes and fair matched strong baselines P2, matched DP/QVI P3, real multimodal plus anti-diffusion P4, and stable cost-adjusted benefit before P5 adoption.

Do **not** restart the unknown-effect original job, promote old best checkpoints to full terminals, alter frozen records or merge to production as a Go.
