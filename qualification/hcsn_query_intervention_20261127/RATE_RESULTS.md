# How many bits encode all 32 possible interventions?

On the frozen bank of 512 reachable group states, unrestricted nonlinear fixed messages have exactly the code counts shown when the explicit clique and coloring agree. For example, at worst absolute probability error 0.0005 the 260-state clique requires at least 260 distinct codes, and the archived coloring of all 512 histories uses exactly 260. A fixed nine-bit index therefore suffices given the finite shared decoder. A requested schedule requires at most seven answer bits (plus five bits to identify one of 32 questions). In this finite-menu example the ability to encode arbitrary nonlinear state IDs overturns a simplistic one-scalar-versus-one-scalar communication claim. The preceding affine rank bound remains correct in its stated class.

| Allowed maximum error | Fixed codes (lower, upper) | Fixed payload bits | Worst answer bits once query is known | New histories within fixed tolerance |
|---:|---:|---:|---:|---:|
| .0005 | 260, 260 | 9 | 7 | 13.54% |
| .001 | 118, 123 | 7 | 7 | 32.29% |
| .002 | 53, 55 | 6 | 6 | 59.11% |
| .005 | 21, 21 | 5 | 5 | 81.25% |
| .01 | 11, 11 | 4 | 4 | 89.84% |
| .02 | 6, 6 | 3 | 3 | 92.45% |
| .04 | 3, 3 | 2 | 2 | 92.97% |

Both types of finite codebook were constructed with the complete original bank. The shifted 384 histories were generated only after the protocol was registered. The fixed coder selects the nearest archived decoder vector using all query answers. Its failures on new histories show that the training-bank guarantee is not uniform over all physical states. The per-query quantized decoder also has a finite calibration range. See rate_results.json for both extrapolation fractions and decoder byte counts. No general lower bound follows for uncharged shared external memory. The physical exact-on-grid response can instead be calculated for a new input state and then quantized on [0,1], which trades a worst-case code size for extrapolation coverage.

rate_witnesses.npz supplies clique members, color assignments, centers, one-dimensional code allocations, and the new answers for independent checks of distances and coverage. Distances are calculated on the double-precision archived model matrix; the gap at each comparison threshold can be checked directly. The theorem relates the exact finite graph to the stated maximum-absolute-error objective.
