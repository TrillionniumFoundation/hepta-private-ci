# Exact checkpoint readback

This original run validates only the changed checkpoint files from e4b4eb5028578be87d5cad0829103632f2bff3a3 to 238fc48402f786db3d7f2a80b0abad6c0e5322bb, tree 74478db5dad451c13483dd575cd5d94c0a3e6864. All 27 changed files passed the original 512,000-byte limit without changing its allowlist. The inherited stage filename `original-full-pr-blob-gate` is retained byte for byte; this invocation is incremental checkpoint validation, not the full joint PR range.

RESULT.json SHA256: 58b3836819fdd1b91c81bb49452da153cd73bc0171356cf884297f9fd2f90ef9. Gate wall time 118.319969560 seconds is nested in the 123.327270784-second owner. Repository HEAD, refs, local configuration, index and original gate bytes were unchanged. No model calls, training updates or native task children ran. The original process owner was dpty-97a22653904275714dfc4c090fa5308a74d8c91e4dc6a091890102633007c2b0 on desktop.
