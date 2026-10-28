# Native ACL normalization and idempotence

The exact Windows observation in `../windows_acl_native_b076/` reproduced two
separate problems. Windows stores a recursive generic deny as an effective mapped
ACE plus an inherit-only ACE, and a file deny as an effective ACE. The previous
single-ACE/exact-flags query therefore appended complete denies repeatedly.

This change recognizes the union of matching-SID leading explicit denies for
three separate scopes: current object, recursive directories and recursive files.
Every required right must be present in each relevant scope. An effective-only
directory deny, wrong identity, no-propagate, inherited-only, or allow-separated
coverage cannot certify the recursive directory contract. Public raw-ACL queries
retain that directory contract; only a native handle establishes file-only scope.

The repair reads type and ACL from one READ_CONTROL object handle. Only a real
repair reopens that object with READ_CONTROL|WRITE_DAC, rereads its DACL, and calls
SetSecurityInfo on the handle. This avoids pairing a separately queried file type
with an ACL obtained later through a replaceable path. Existing correct ACLs do
not require WRITE_DAC. Token flags and installed permission masks are unchanged.

The original Rust tests remain an exact byte prefix. Three additional tests
cover missing rights/scope/order and real Windows directory/file DACL byte
idempotence. The probe still runs the original 26 expectations; its only harness
change binds and copies the new production module. Four source/parser integrity
tests pass. Required local Rust test/fix commands stop before compilation because
the workspace aws-auth manifest is absent. Scoped rustfmt/check, spelling and diff
checks pass. Native Windows compilation and execution are still required.

The independent native evidence also proves that parent DELETE_CHILD can permit
outside and protected-child deletion. This ACL normalization fix does not close
that permission defect. Outside-deletion refusal, full-read and allowed-workspace
operations remain unchanged gates. A completed diagnostic is never a permission
qualification, and this patch makes no broader sandbox security claim.
