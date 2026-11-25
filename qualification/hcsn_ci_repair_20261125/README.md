# Scoped Rust CI repair — 2026-11-25

This repair reuses five reviewed source files to address the strict Rust errors
in PR #7067. It does not change the research models, thresholds, workflow gates,
SDK timeouts, or the recorded experiments.

## Source provenance and behavior

- PR #7052 at `78c1012d1b6d63a2cd3d67e2534ba8b8d62e34b6` supplies the
  Bellman qualification example and canonical CNS route digest delegation.
  The example propagates setup failures instead of calling `expect` or `unwrap`.
  Its cases, work budgets, assertions, success output, and performance limits
  remain the same. The route delegation uses the same byte encoding.
- The three publication-constructor files match PR #6799 at
  `8ca01613a91ddf310fad6decaba7452d46df519e`. Only these files are reused.
  The named payload groups the existing digest and bytes, then the constructor
  applies the original validation statements in their original order.
- This changes the public Rust constructor from eight arguments to seven.
  It is a source API migration: external Rust consumers, if any, must pass the
  named payload. It is not a claim of unchanged Rust source compatibility.
  The stored publication fields, record encoding and decoding, digest function,
  and authorization checks are unchanged.

## Closure and validation evidence

The exact base is `b1af67a38f8cf9cee700cc067da1e6001ce220a8`.
The complete tracked Rust search covers 9,311 files and 9,296 distinct blobs.
`CALLERS.txt` records every occurrence of `ControlRuntimePublicationV1`:
there are two constructor calls, in the production owner and the existing
publication test helper. Both are migrated. No alias or additional Rust caller
appears in that exact repository snapshot. This is a repository-wide source
search, not a claim about unpublished external consumers.

`SOURCE_REVIEW.json` binds the reused files, unchanged wire/IO functions,
and full prior source/merge job logs. `LOCAL_VALIDATION.json` records the actual
format, diff and scoped test status. A preparation failure is not a test pass.

The prior #7052 exact-source job `138035883196` and deterministic-merge job
`138035883092`, from run `45272005010`, both reached the same remaining strict
error: the eight-argument publication constructor. Their full decoded logs
are retained as genuine gzip files. Their failure is preserved; it is not
relabelled as a successful whole qualification run.

`PREPARATION.json` records the bounded checkout/partial-fetch failures before
the successful source closure. The private checkout and its logs are isolated
from the active research jobs and other worktrees.

GitHub CI on the final PR head remains the integration authority. A successful
local format or crate test does not certify all Windows, SDK, Bazel, or learning
qualification jobs. No unrelated failure is waived by this repair.
