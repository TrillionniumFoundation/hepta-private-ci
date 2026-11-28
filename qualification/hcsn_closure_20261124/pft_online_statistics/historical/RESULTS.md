# Historical HCSN training-cache qualification

All nine registered parents passed on the first run of the frozen runner. This is a new engineering consistency check on the exact #7071 training shards, not another run of its scientific budget.

The 36 original NPZ files were read from the existing desktop cache through immutable-version reads. Every chunk and complete file SHA-256 was checked locally against the old ring manifest. Total input size was 2,271,836 bytes. Initial transport failures and successful retries are retained. No final-test or development-set files were accessed.

| Check | Result |
| --- | --- |
| Parent grid | `n8/n32/n64` × seeds `17011/27011/37011`; 9/9 passed |
| Features and outputs | 41, 161 or 321 fixed features; 3 outputs; 192 rows per parent |
| Forward versus reverse admission | Same full candidate object and head |
| Cold independent process | Same full candidate object; distinct process PID and exit zero |
| Independent augmented least squares | Maximum absolute weight difference `4.451078394751562e-12` |
| Original archived `SOLUTIONS.npz/full` | Maximum absolute weight difference `6.179154410368426e-12` |
| Optimizer steps / final-test reads | 0 / 0 |
| Outer execution wall time | 12.8383 seconds on one BLAS thread, including validation and output writes |

The unchanged registered comparison tolerance is `rtol=atol=1e-7`. The independent reference solves an augmented least-squares problem, rather than reusing the normal-equation solver. The deliberately incorrect duplicate-statistics, per-shard-regularizer and mixed-normalization controls all increased the original training objective; every numeric result is retained in `RESULTS.json` and the archive. These controls diagnose accounting errors and do not measure generalization or scientific usefulness.

`historical-evidence-compact.tar.gz` has SHA-256 `f82a4f8d93ee940dff82c2c06a5c9492348bf6f589ae594d538aa40d42f79b28` (5,588,877 bytes). It contains all 36 exact inputs, the original manifests and reference solutions, all new per-parent statistics, forward/reverse/cold candidate exports, admission receipts, result records, raw logs and transfer history. The inventory records hashes for the redundant local SQLite files and contribution JSON; their logical contents can be reconstructed from the included inputs and frozen code. Those 27 redundant files are not added to Git.

Candidate code was frozen at `4c0e781e0cb1abb3b2412db0d3c116b75808349b`; protocol commit is `2f1550b2e05505a2940687c2a9d7dbb08ef2fd31`. The parent source is `88414dda04443897def179754779aecdca6f0296`. The preceding ledger change retains exact execution-time source and the formatting/AST-equivalence receipt. No tests were rerun after formatting.

The source groups in these historical caches were synthetic. Passing establishes accounting, persistence and fixed-feature solver consistency for those cached objects. It does not change the old A-to-B rejection, demonstrate new-user retention, learn a Neural Circuit, train a new representation, or create Chain adoption/payment eligibility.
