# Correct the diagnostic constant's locked API location

The complete original Windows sandbox target at commit 562d63a failed to build
with E0425 before executing any tests. The diagnostic referred to
SE_GROUP_INTEGRITY in Win32::Security; the locked windows-sys 0.52 package exposes
that i32 constant in Win32::System::SystemServices. This successor corrects that
fully qualified path and explicitly converts the constant into the u32 group
attribute field. SystemServices is already an enabled dependency feature.

The full original job log and artifact are retained here. No result from this
compile failure is counted as a permission observation. Production token and ACL
code, dependency inputs, all original tests, timeouts and workflow are unchanged.
The existing full-target workflow must execute again on this exact successor.
