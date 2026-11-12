# B source terminal executable fixture repair

The original exact da0f6e55 native run failed both dedicated UID60002 source terminal parents with `Permission denied (os error 13)`. The untouched failure-section JSON is retained here; it also includes the other failures from the same observed run.

The candidate opens the actual already-built test binary while still Root, then executes that exact inode through its inherited read-only descriptor. The child starts in `/run`; it no longer needs to traverse private ancestors of the original build directory. This reuses the existing independent source keeper approach. No executable bytes, global directory modes, product permissions, source UID/GID, original channel bounds, or terminal assertions are changed.

The component still requires real Root and UID60002 processes, source pidfd checks after the real frame ACK, an independent finalized notification, and phase-specific child receipts. Missing notification must still refuse.

Actual formatting and diff checks passed. The new candidate has not run native tests; this patch and its tool completion do not establish that the original failures are resolved. The original failure and subsequent qualification remain distinct. These component cases do not establish signed source admission, independent B execution, or the complete A/B/C chain. Whole positive, evaluated NoUpdate, and whole cold restart counters remain zero.

The Git bundle contains only the repair commit and requires the exact da0f6e55 base. See observation.json for complete identities and hashes.
