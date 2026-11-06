# Windows ACL repair evidence checkpoint

This packet preserves 19 original files and 794,707 bytes. It includes the complete original Windows job 127949627315 log, the frozen unit 04 sources and patch, actual local validation receipts, and independent internal source reviews. Repeated blocks in the original job log are not additional native attempts.

The repair was published as draft #5077 at `7bf0472af73eb9fbd92dff44cb15cc9526cb5d80`, tree `b6e3970dff858ffcd1d3537b2ab654e618697539`. The source of the observed failure and its actual checkout share the exact tree recorded in the frozen manifest. The original inventory also names two other job logs; those other logs are not part of this packet.

Run `python -O -B restore.py /absolute/path/to/a-new-directory` with Python 3.12 or later. The destination must not exist. The reader verifies its fixed index, bounded gzip segments, full archive hashes, canonical paths, exact membership and all file bytes before writing inert 0644 regular files. Original modes are retained as evidence. No restored source is executed.

Fixed INDEX SHA-256: `7b0f8bead0875b51d39fbf52a759e264ed74212adebcb8b05992213e4fe84043`. The reader is identical to the published SDK checkpoint reader except for this seal.

After restoration, read the unit README and the independent review. The candidate retains the read-only complete-deny path, verifies volume and 128-bit file identity before mutating an ACL through the new handle, and preserves the original native positive and negative acceptance cases. It does not establish that the pathname remains fixed until process spawn, or resolve the separate legacy token deletion failure.

The actual formatter, source checks and patch round-trip passed. The original attempts to invoke just could not start in the partial workspace and remain in the packet. Windows compilation, execution, Clippy and complete required gates remain pending. Evidence restoration is not native qualification or external audit.
