# Rust consolidation, round 07

This increment merges the reviewed NDU ordinary-kernel branch and repairs the
Core/App Server interrupted-turn recovery race on the existing consolidation
candidate. It is not a completed main merge or branch cleanup.

## Source and branch boundary

Base: `6c6cf2f0aa296fb27d2e120a648dd961b79f9d9b`.
Additional merge parent: `1b75bb2fbedff792ec3a9fafa8f5a0177b2ade83`.
The actual NDU Git merge produced tree
`05e541938e6d8edcc40a1febfa2e8fb41816b37c`, exactly matching the reviewed and
tested source composition. No ancestry-only merge was used.

The initial inventory contains 7,526 branch refs. The protected HIA boundary
contains 303 refs, including descendants and aliases whose names omit HIA.
The attached protected-ref manifest records their original identities. HIA PR
base dependencies also require preservation during any later cleanup. No HIA
ref is modified and no branch is deleted by this increment.

The candidate's ancestry covers 2,062 ordinary branch names in that snapshot,
three more than the previous candidate. This is ancestry coverage of the
candidate, not evidence that those branches have reached main. Main remains
`732e934ba496d90fbe042b8d41d479ef901643e5` until its required checks pass.

## Changes and verification

The recovery path waits only for the exact retained Finish/Abort terminalizer.
It preserves turn identity, attach epoch, shutdown cancellation and the existing
idle/persistence fence. It refuses running tasks, start reservations, Suspend,
unrelated IDs and replacement terminalizers. Four deterministic Core regression
tests and the unchanged failing App Server end-to-end case passed on the exact
five-file patch. Scoped `just fix` and `just fmt` also passed. Only test-file
formatting changed after testing; all source hashes and log hashes are recorded
in verification.json.

The NDU change admits the ordinary kernel only for the observed v4,
width-32/depth-1/direct profile and retains model/owner, packet and budget
bindings. The existing source receipts remain historical evidence. Validation
passed 27 native Rust tests and 117 Python tests, including Rust/Torch parity,
delivery/recovery, budget refusal and frozen-parameter checks. The standalone
Rust recipe used Rust 1.96.0; Torch checks used Python 3.14.4/Torch 2.10 CPU.
This does not claim the full training campaign or workflow's exact Python/Torch
environment was rerun. The PR path filter is expanded to cover all 257 source
paths bound by the candidate's source identity; publisher and training policies
are unchanged.

## Work still open

The larger Windows/Rust frontier merge is being reconciled separately; its
unqualified source is not attached as a parent of this increment. Required CI
on the previous candidate still had cargo-deny, GNU/musl and Windows failures.
The chrono advisory, exact 500 ms NextUse diagnosis, other failing original
regressions and the unqualified Windows elevated admission mechanism require
resolution. Required CI and Architecture checks remain enforced. No advisory
ignore, weakened test, relaxed deadline or sandbox exception is introduced.

Further branch integration and deletion must use refreshed refs, preserve the
HIA boundary and prove that each removed ordinary tip is retained in main.
