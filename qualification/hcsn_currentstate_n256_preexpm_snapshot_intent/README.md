# N256 current-source pre-expm input snapshot intent

Status: **HOLD / SOURCE FREEZE / ZERO EXECUTION ON THIS BRANCH**.

This separate diagnostic narrows the #6901 strict RED without retrying its consumed identity. It reads the already-published attempt002 oracle/candidate boundary containers and the #6901 rebuilt candidate boundary, verifies all three immutable boundary identities, and materializes the exact undiscounted and discounted augmented matrices and seeds that the frozen current oracle and candidate sources pass to `scipy.linalg.expm`.

The admitted run performs three boundary decodes and six NumPy-only pre-expm constructions. It performs zero dynamics, zero matrix exponentials, zero SciPy imports, zero Torch calls, and zero optimizer steps. It preserves all raw matrices and seeds even if any byte comparison is RED. The host record binds CPU flags and NumPy/OpenBLAS configuration that the earlier oracle/candidate runs omitted.

Exact equality only proves that the current frozen sources derive identical pre-expm inputs from the published boundary bytes. The original oracle run did not publish its actual pre-expm bytes, so this diagnostic cannot retroactively bind them. It does not qualify the exponential arithmetic path, dynamic result, N256, later cycles, N512, full state, training, task value, C2 replay, HPCA custody, production, or adoption. The #6901 RED and its cause `UNKNOWN` remain.
