# Compiler repair candidate after actual maintenance v8

Status: source integration for a new isolated maintenance run. This is not a qualification PASS or an ordinary business-loop acceptance.

Input is maintenance head 6e345aaef8bcdc2e6acb5e1825172b13e26fb437, tree 70ef80c989c2831ff2acb85f6a2678c001791baf, with all three actual v8 Clippy postimages and the complete failed v8 evidence retained in the parent. Its 197-file source manifest is c4b447e17082a076c998cf71e43d7f006c286b06.

The new source manifest has 199 entries. Twelve source paths change through 27 exact operations: two existing identifier/import corrections, twelve logging sites and five imports, one AsyncFd error conversion, two structural PartialEq derives in an existing source file, and the missing Outcome data adapter plus its module and two actual A/C call sites. The existing profile file and the new Outcome file account for the two additional manifest paths. Root independently GET-checked all pre/post bytes and unique forward/reverse replay. The original profile preimage and absence of the new Outcome path were checked in both complete source-directory trees.

The Outcome adapter preserves all original raw fields and supplied signature bytes. It constructs no Verified value, signs no evidence, reads no clock and reports no business success. Actual original producer identity, payload, Terminal, task publication and signature checks remain required. Five nullable fields require explicit JSON keys; no defaults are supplied. The logging change uses the existing best-effort synchronous stderr pattern and does not claim zero I/O cost. The AsyncFd conversion preserves the complete register error and OwnedFd; its outer io::ErrorKind becomes Other.

Metadata material under metadata-progress is an incomplete checkpoint, preserved for recovery and review. It is not final CALLERS TOML or an original checker result. The new Outcome annex is additive (+1 boundary, +2 protected conjuncts) and targets final totals 1011/600; all prior obligations and forbidden markers must survive final adaptation. Actual v9 formatting/Clippy results must be incorporated before final metadata qualification.

Only the isolated maintenance branch is advanced. PR #6006 source and the original staging head remain fixed; neither main nor any Chain ref is changed. Original checker 7a6709691c372504ca11b5d2a74e14ba819fca8f, typed helper e23bb8aa42241b429ef5dbce5a4660853b66eb2f, and qualification harness 096b5b69c1295560f3a6c9e0da51e2708a0c996c remain unchanged. The original seven-package/Root17 gates and their deadlines are not replaced by maintenance. Additional component gates remain required for Core/AppServer/MCP changes.

Business acceptance remains 0 ordinary complete / 0 positive adoption / 0 NoUpdate-or-rollback. Independent C and actual daemon/Root OS restart remain unaccepted. No fixture, actor, holdout, signature or receipt is manufactured, and no failed execution is counted as NoUpdate.
