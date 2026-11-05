# C4 finite strategy cost tables

All totals below are native **thread CPU** unless the column explicitly says wall. `ms/nonce` divides the complete measured producer cohort, including actual setup and every failed nonce, by all recorded nonces. Arm selection uses one arm over eight samples retrospectively; it is neither a per-attempt oracle nor a future cheapest-work guarantee.

## Legal-v3: 30 matched factorial shards

Target 0 is `7f…ff` (required weight 2); target 1 is `07…ff` (required weight 32). Each row includes eight actual setups and eight × H searches. Shared H prefixes are correlated, not additional independent work.

| Class | Target | H | Observed lowest fixed arm | Nonces / misses | Setup ms | Full CPU ms | Full wall ms | CPU ms/nonce | CPU ms/hit | Eager transposed / best |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full-rank-field | 0 | 1 | lazy-full-limb | 18 / 10 | 3.384527 | 26.148823 | 26.269582 | 1.452712 | 3.268603 | 1.151920 |
| full-rank-field | 0 | 8 | lazy-full-limb | 127 / 63 | 3.360178 | 163.372418 | 163.370082 | 1.286397 | 2.552694 | 1.189269 |
| full-rank-field | 0 | 64 | lazy-full-limb | 997 / 485 | 3.438544 | 1254.372124 | 1254.673455 | 1.258147 | 2.449946 | 1.185938 |
| full-rank-field | 1 | 1 | lazy-full-limb | 222 / 214 | 3.441666 | 284.121040 | 284.131965 | 1.279825 | 35.515130 | 1.174398 |
| full-rank-field | 1 | 8 | lazy-full-limb | 2032 / 1968 | 3.453660 | 2549.564086 | 2549.979127 | 1.254707 | 39.836939 | 1.166157 |
| full-rank-field | 1 | 64 | lazy-full-limb | 15841 / 15329 | 3.420400 | 19962.551981 | 19963.478932 | 1.260183 | 38.989359 | 1.172659 |
| zero | 0 | 1 | eager-full-limb | 20 / 12 | 3.454226 | 28.722619 | 28.723666 | 1.436131 | 3.590327 | 1.168645 |
| zero | 0 | 8 | lazy-full-limb | 112 / 48 | 3.380404 | 142.960375 | 142.959411 | 1.276432 | 2.233756 | 1.189473 |
| zero | 0 | 64 | lazy-full-limb | 997 / 485 | 3.465747 | 1270.076332 | 1270.307935 | 1.273898 | 2.480618 | 1.216205 |
| zero | 1 | 1 | eager-full-limb | 247 / 239 | 3.462055 | 319.396437 | 319.413157 | 1.293103 | 39.924555 | 1.167318 |
| zero | 1 | 8 | eager-full-limb | 1800 / 1736 | 3.459134 | 2294.691613 | 2295.235915 | 1.274829 | 35.854556 | 1.161961 |
| zero | 1 | 64 | lazy-full-limb | 15567 / 15055 | 3.377926 | 19458.288827 | 19460.967530 | 1.249970 | 38.004470 | 1.177399 |
| continuity-maintenance-v1 | 0 | 1 | lazy-full-limb | 18 / 10 | 3.708294 | 28.089793 | 28.090908 | 1.560544 | 3.511224 | 1.180881 |
| continuity-maintenance-v1 | 0 | 8 | lazy-full-limb | 119 / 55 | 3.457552 | 156.314389 | 156.312644 | 1.313566 | 2.442412 | 1.192617 |
| continuity-maintenance-v1 | 0 | 64 | lazy-full-limb | 998 / 486 | 3.387239 | 1259.994512 | 1260.079057 | 1.262520 | 2.460927 | 1.188888 |
| continuity-maintenance-v1 | 1 | 1 | lazy-full-limb | 192 / 184 | 3.435637 | 246.407609 | 246.401504 | 1.283373 | 30.800951 | 1.158887 |
| continuity-maintenance-v1 | 1 | 8 | eager-full-limb | 1740 / 1676 | 3.332752 | 2148.672101 | 2149.157624 | 1.234869 | 33.573002 | 1.182307 |
| continuity-maintenance-v1 | 1 | 64 | lazy-full-limb | 16047 / 15535 | 3.347316 | 19798.148734 | 19801.835415 | 1.233760 | 38.668259 | 1.172130 |
| one-zero-left-rank-one | 0 | 1 | eager-full-limb | 21 / 13 | 3.491543 | 31.147783 | 31.148342 | 1.483228 | 3.893473 | 1.159908 |
| one-zero-left-rank-one | 0 | 8 | lazy-full-limb | 135 / 71 | 3.408430 | 173.988046 | 173.986020 | 1.288800 | 2.718563 | 1.194716 |
| one-zero-left-rank-one | 0 | 64 | eager-full-limb | 1015 / 503 | 3.465076 | 1268.400650 | 1268.661728 | 1.249656 | 2.477345 | 1.196918 |
| one-zero-left-rank-one | 1 | 1 | lazy-full-limb | 312 / 304 | 3.383608 | 396.893534 | 396.910593 | 1.272095 | 49.611692 | 1.165604 |
| one-zero-left-rank-one | 1 | 8 | lazy-full-limb | 2182 / 2118 | 3.375763 | 2714.242903 | 2714.271785 | 1.243924 | 42.410045 | 1.174218 |
| one-zero-left-rank-one | 1 | 64 | lazy-full-limb | 16134 / 15622 | 3.501971 | 20245.601587 | 20251.655204 | 1.254841 | 39.542191 | 1.190466 |
| one-zero-right-rank-one | 0 | 1 | eager-full-limb | 11 / 3 | 3.469345 | 18.059591 | 18.060360 | 1.641781 | 2.257449 | 1.139018 |
| one-zero-right-rank-one | 0 | 8 | lazy-full-limb | 129 / 65 | 3.391832 | 165.757791 | 165.776020 | 1.284944 | 2.589965 | 1.192170 |
| one-zero-right-rank-one | 0 | 64 | eager-full-limb | 1028 / 516 | 3.403527 | 1303.969435 | 1304.043830 | 1.268453 | 2.546815 | 1.177098 |
| one-zero-right-rank-one | 1 | 1 | eager-full-limb | 230 / 222 | 3.440555 | 299.334158 | 299.354896 | 1.301453 | 37.416770 | 1.176129 |
| one-zero-right-rank-one | 1 | 8 | eager-full-limb | 2218 / 2154 | 3.401551 | 2743.771664 | 2743.880435 | 1.237048 | 42.871432 | 1.191247 |
| one-zero-right-rank-one | 1 | 64 | lazy-full-limb | 16938 / 16426 | 3.311694 | 21177.290010 | 21181.695431 | 1.250283 | 41.361895 | 1.176971 |

## Reused-v3: 13 arms, target 0, actual H4

Each eligible row retains eight setups, 32 searches, all failed nonces and 32 candidates. Unsupported constructor calls are paid observations and excluded from the cheapest legal arm selection. These are different challenge domains and timer scopes from legal-v3; the tables are not a cross-suite speedup experiment.

| Class | Observed lowest fixed arm | Supported / unsupported arms | Nonces / misses | Setup ms | Full CPU ms | Full wall ms | CPU ms/nonce | CPU ms/hit | Generic / best |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| periodic-dense-fixture | prepared-generic | 5 / 8 | 62 / 30 | 3.436334 | 106.919520 | 106.959874 | 1.724508 | 3.341235 | 1.000000 |
| full-rank-field | prepared-generic | 5 / 8 | 80 / 48 | 3.372219 | 135.331408 | 135.336606 | 1.691643 | 4.229107 | 1.000000 |
| zero | blocked-zero | 8 / 5 | 62 / 30 | 0.124517 | 99.509695 | 99.529580 | 1.604995 | 3.109678 | 1.096299 |
| identity | prepared-structured | 6 / 7 | 66 / 34 | 0.211551 | 113.779771 | 113.779766 | 1.723936 | 3.555618 | 1.071512 |
| rank-one | prepared-structured | 6 / 7 | 64 / 32 | 0.486103 | 108.775393 | 108.775232 | 1.699616 | 3.399231 | 1.138778 |
| sparse-diagonal | prepared-structured | 6 / 7 | 58 / 26 | 0.222721 | 97.004973 | 97.012353 | 1.672500 | 3.031405 | 1.022772 |
| continuity-maintenance-v1 | maintenance-limb | 9 / 4 | 71 / 39 | 0.490363 | 108.974611 | 108.975483 | 1.534854 | 3.405457 | 1.108029 |
| one-zero-left-rank-one | prepared-structured | 7 / 6 | 58 / 26 | 0.178045 | 94.616958 | 94.617712 | 1.631327 | 2.956780 | 1.037104 |
| one-zero-right-rank-one | prepared-structured | 7 / 6 | 67 / 35 | 0.184428 | 110.257179 | 110.278877 | 1.645630 | 3.445537 | 1.022790 |

## From-zero false trace: full attacker denominator

Each row measures eight real public-prefix setups, 32 false-trace searches and all losing hash trials. The complete attacker total includes those phases, winner-buffer cloning and retained trial evidence. It does not charge acquisition of a valid proof. Each receiver ratio uses only that one verifier label, not the sum of five labels. `production` and `full-limb-experimental` are two invocations of the same arithmetic kernel.

| Class | Nonces / misses | Setup µs | Search µs | Full attacker CPU µs | Full attacker wall µs | Production rejection CPU ms / 32 | Reject / full attacker CPU | Reject / full attacker wall |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| periodic-dense-fixture | 70 / 38 | 1735.088 | 654.419 | 2432.179 | 2468.713 | 47.979138 | 19.726812 | 19.486812 |
| full-rank-field | 65 / 33 | 1564.435 | 412.612 | 2015.752 | 2017.632 | 47.103567 | 23.367739 | 23.375023 |
| zero | 69 / 37 | 1464.332 | 603.070 | 2105.344 | 2107.588 | 47.120829 | 22.381534 | 22.428466 |
| identity | 59 / 27 | 1709.293 | 616.610 | 2373.275 | 2378.224 | 48.358761 | 20.376383 | 20.398301 |
| rank-one | 71 / 39 | 1608.800 | 628.891 | 2278.184 | 2315.864 | 47.499814 | 20.849858 | 20.592607 |
| sparse-diagonal | 47 / 15 | 1544.225 | 533.373 | 2116.411 | 2118.698 | 47.519560 | 22.452898 | 22.494950 |
| continuity-maintenance-v1 | 68 / 36 | 1600.037 | 596.082 | 2236.465 | 2246.061 | 47.395245 | 21.192035 | 21.146547 |
| one-zero-left-rank-one | 72 / 40 | 1677.079 | 667.952 | 2386.244 | 2425.679 | 47.374001 | 19.852958 | 19.579028 |
| one-zero-right-rank-one | 52 / 20 | 1574.338 | 622.935 | 2238.561 | 2275.551 | 47.618651 | 21.271992 | 21.041511 |

Raw bindings, all 120 factorial arm totals, all 117 reused class/arm totals, native outcome counts, per-sample denominators, verifier distributions and CPU/wall phase arithmetic are retained in `independent-strategy-recomputation.json`. Every raw stream hash and complete candidate proof was reconstructed locally before comparison with the saved original reader output. No W1 transcript replay or native measurement was performed by this review.
