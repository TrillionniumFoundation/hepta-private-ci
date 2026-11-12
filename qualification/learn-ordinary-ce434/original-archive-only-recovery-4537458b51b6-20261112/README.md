# Original archive-only recovery for source 453

Status: **prepared and not executed**. This directory contains an independently reviewable recovery request. It does not report a download, a v3 target identity, a native test, or ordinary LEARN acceptance.

## Observed inputs

The fixed source is `4537458b51b6ca936264aecea7cfe384b941d0d1`, tree `8cbd7b269c9c39df4ee3ffcefed8473060696184`. The preserved older worktree remains at `a6717d7228045e6cb60532966f06e6e02c4a6abe`, tree `647b9e78151299c1e7de455eae9c530ca93b28c9`.

The actual isolated source run passed all 443 methods across 62 modules. Its native driver stopped before helper construction and `just test` because the v2 target directory was absent. The subsequent v3 creation attempt stopped before its first `mkdir` because the private V8 archive was absent. These original failures remain recorded separately; this package does not rewrite them.

The four SDK records in this directory are preserved byte for byte. They establish the observed home archive absence and the observed binding copies. The selected current private binding is device 2067, inode 40370261, 39,884 bytes, regular mode 0400, with the original complete SHA256. The script checks those conditions again at execution, including the exact decimal mtime and ctime values. The home and fallback bindings are not copied or written.

## Narrow recovery

The script requires both worktrees to be clean and fixed, the existing v1 root and private-pins directory to be canonical owned mode 0700, the original /data identity and 64 GiB headroom, and the complete original manifest and history hashes. It refuses a reappearing private archive, home archive, v1 target, or v2 target.

It preserves the original official release URL, existing SOCKS address, curl argument assignment, 20 second connect timeout, 300 second maximum time, five redirects, 29,366,352 byte limit, and SHA256. The only effective download destination change is a partial file within the new exclusive evidence directory.

After complete partial verification, the script opens the existing private directory and creates the archive using `O_CREAT | O_EXCL | O_NOFOLLOW`. It checks complete bytes through the actual new descriptor, sets only that newly created file to mode 0400, fsyncs it, and performs a complete path readback. It checks the original binding, directories, sources, manifest, and history again afterward.

No existing binding or archive is overwritten. No runtime root, private-pins directory, build target, source file, grant, key, policy, service, or dependency version is created or changed. A failure leaves the new evidence, partial, and any actual new archive for reconciliation; there is no cleanup or signal path.

## Review artifacts

- `restore-original-archive-only.py`: exact script embedded by the six-field typed request.
- `frozen-request.json`: a new archive-only idempotency key, with the original host, executable, cwd, environment, and `-B -c` prefix.
- `request-contract.json`: fixed inputs, original observed failures, permitted mutation scope, and completion requirements.
- `exact-edits.json` and `recovery.patch`: complete original-299 to new-script differences. Ten hunks remove 59 lines and add 176 lines; forward and inverse reconstruction recover both complete files exactly.
- `observed-*-sdk.json`: the four original SDK responses, without re-encoding their version strings.

The original 441 script is Git blob `29961b07486dcf1cfd2a4875a7b17733ed06547a`. It is historical input, not a request to recreate the whole v1 root or binding.

## Follow-up remains gated

Root alone may dispatch this reviewed request. A successful archive recovery would establish only the new archive and preserved binding. A separately keyed v3 creation attempt must then produce its own actual identity receipt. Native-only validation remains unbound until that real receipt is fully read and hashed. The earlier failed main result is not replaced by a synthetic success.

All production source, native test selection, time and memory budgets, and ordinary acceptance requirements remain unchanged.
