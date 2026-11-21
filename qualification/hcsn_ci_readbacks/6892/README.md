# HCSN N256 runtime-v3 mismatch localization originals

This evidence-only readback preserves the exact originals from Draft #6892 and the complete hosted job log without re-executing the candidate, oracle, dynamic step, dense exponential, Torch, or an optimizer.

## Bound source and execution

- source commit: `fdf5b123afb108bbce21c3bfb574b989d02890f2`
- Actions run: `44910007894`
- job: `136863614180`
- artifact: `14709805060`
- artifact ZIP SHA-256: `958c7e4c5459e760e14ff3c363ea55f517a48a51add40279164040759b29ad10`

## Preserved result

All 69,728 coordinates were compared. The historical runtime-v3 result remains RED with 665 bitwise mismatches, maximum absolute error `0x1.e000000000000p-54`, and maximum ULP distance 98. All mismatches are in propagated state tensors: 650 active plus five each in discounted-hit, mass, and occupation. Packet tensors, metadata, upper state, and the unchanged active slot were bitwise exact.

The read-only runtime comparison found a lineage mismatch: the oracle recorded Python 3.12.3 on the Ubuntu 24.04 hosted lineage, while the later RED execution actually observed Python 3.12.16 on Ubuntu 26.04. NumPy 2.3.5 and SciPy 1.17.0 were declared for both. This is an unresolved identity confounder, not proof that the numerical kernel is correct or incorrect.

No threshold was changed. No historical RED or UNKNOWN was removed. This readback grants no large-grid qualification, full-state qualification, finite-domain qualification, C2 full replay, HPCA update, or production adoption. Global status remains HOLD and `all_closed=false`.
