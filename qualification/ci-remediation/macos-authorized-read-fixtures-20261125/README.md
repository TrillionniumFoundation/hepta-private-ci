# Canonical owned roots for stable-handle read fixtures

The fac3 macOS Intel job 139157914163 ran the authorized-read cases and failed
three positive local stable-handle unit cases, the capability-advertisement RPC
case, and both local/remote exact-bound cases. Its full log is 1,473,183 bytes,
SHA-256 `8964a6d7466046c18d3293b708260ae01702e51142bcf0b8daefbf753fed5f71`.

The Darwin implementation authorizes the final `F_GETPATH` name against the
provided policy. The fixtures previously constructed policy roots under the
logical temporary parent, which can be `/var` while the final name is under
`/private/var`. Only the owned test roots are now canonicalized. All hard-link,
symlink, pathname replacement, deny-glob, missing-file redaction, overflow, and
outside-root assertions remain; using canonical roots also prevents negative
cases from passing merely because the entire root was already denied.

An isolated Darwin synthetic-file probe independently observed an actual
`/tmp` request produce an `F_GETPATH` name under `/private/tmp`, equal to
`realpath` and with the same device/inode. The installed SDK supplied the
F_GETPATH constant; this is an alias-mechanism control, not a CI rerun.

No production policy normalization, permission grant, stable-handle probe,
capability gate, or error contract changes in this commit. Native macOS rerun
is required; source review and formatting are not an execution result.
