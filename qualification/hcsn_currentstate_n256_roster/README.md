# Authentic N256 symbolic roster

Status: **SOURCE_ONLY / HOLD_NO_NUMERICAL_EXECUTION / all_closed=false**.

This package binds the new-export-only N256 bytes published by Draft #6256 and symbolically expands the warm/coarse/cold packet schedule into an N256-specific roster. It reuses only dimension-generic symbolic helpers from the N128 compiler; no N128 roster identity, denominator, numerical result or qualification transfers.

The independent auditor imports no compiler module. It re-decodes the exact N256 export, independently reconstructs every packet tuple, capsule, coordinate span and ordered coordinate identity, and verifies the raw manifest.

The frozen expected denominator is 18,225,028 FP64 coordinates across 14 capsules; the largest capsule is 3,444,164 coordinates. These are static structure and memory lower-bound facts only. This package executes no state propagation, spatial operator, matrix exponential, oracle, Torch operation, backward pass, optimizer step or training. N256 dynamics, serializer/full-state recovery, cross-runtime exactness, N512, finite-domain qualification, fullnetwork training and all historical RED/UNKNOWN results remain OPEN.
