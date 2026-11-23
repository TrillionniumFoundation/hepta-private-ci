# Reset position and mark fit on integrated source

Both lanes of [run 45112477537](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45112477537) executed the original ten modules, 45 tests without skips and 120 Adam updates per lane on Torch CPU 2.10. The archived lane used a12f564d and 29 bound files. The current lane used 6a5a0283 and 49 bound files. Both ZIP files match their GitHub artifact SHA-256. Their before and after source inventories match the corresponding frozen manifests.

For each ZIP, compare.py verifies the archive digest and CRCs and compares all 121 optimizer observations. Each contains the relative MSE, reset, signed mark and both gradients. Every one of the 605 binary64 scalars matched between the two hosted Torch 2.10 lanes. Compared to the original #6185 hosted trajectory, 59 of 605 scalars matched bit for bit, with maximum absolute difference 1.265e-13 or less. The separate local Torch 2.15 run matched that historical trajectory on all 605 scalars. These comparisons describe complete runs on their respective machines.

The fitted reset position moved from 0.42 to 0.64949628, approaching the teacher value of 0.65. The mark moved from 0.5 to 1.99585374, approaching 2. The final relative MSE was 0.0000035602013 against a prespecified ceiling of 0.0002. The maximum field discrepancy after the hosted cold restart was below 9e-11. This teacher and student use the same small model and a fixed default boundary.

Use `python compare.py --help` for the independent archive comparison. HOSTED.json records exact sources, run and job identities and artifact digests. The directory retains both original hosted archives, the local raw and result, and the historical guard's original refusal on the integrated tree.
