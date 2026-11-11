# Original five-lane static size failure 08

Original default Rust1.96 release build and repository strip completed.
Host is8344952B; complete five-lane peer is9144680B, exceeding the unchanged
8MiB file limit by756072B. It was rejected and never executed.
Original default features/profile and8MiB file/16MiB LOAD gates are unchanged.
Original source before/after bytes are identical; exact unstripped/packaged
ELF hashes and retained external paths are in [the actual result](result.json).

07 uses the original local Tokio runtime, including I/O, time and blocking
work. 08 explores type-erased typed JSON decoding with the same bounded DTOs
and assertions, but its actual binary grows; it is not imported into main.
Neither result qualifies semantic behavior, native five-lane execution,
Root/Host/Session recovery or persistent CPU G2. No earlier component result
is transferred to these candidate sources. [Original bytes](publication.json).
