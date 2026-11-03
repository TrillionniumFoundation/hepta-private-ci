# Exact native authorized-read qualification

Draft / HOLD_NO_GO / DENY_ALL. Product commit aaf74551dccf99f2d0d1525d02337cf804233817 is unchanged.

Run 41717707968 completed all three original native scopes. Windows MSVC passed 252 original unit cases plus the original capability/denial RPC; macOS ARM64 passed 275 plus the RPC; Linux passed 261 plus the RPC. Total: 791 native executions, zero ignored/filtered cases. Each original empty file-system wrapper executed but contributes zero Rust coverage. All three corresponding Clippy target sets passed; Linux checked the committed lock first. Original 30-minute budgets and assertions remain.

The complete original ZIPs and independent verifier bind every output and all 189 exact Git source paths per artifact, before/after equality, original commands, actual uncached 3-of-3 target execution, individual Rust case completions and XML. Two Unix process tests emit child kill diagnostics before their final success; those original lines are retained. The verifier also rejects optimized Python. No archived code is executed during replay.

From a checkout with the product commit available:

```sh
python3 qualification/authorized-read-20261103/hosted-aaf/verify.py --repository . --artifacts qualification/authorized-read-20261103/hosted-aaf --output /tmp/authorized-read-aaf-verified.json
```

Compare the generated report bytes with VERIFIED.json. Earlier complete negative ZIPs remain in qualification/authorized-read-20261103/original-negative at the product commit. Full repository CI and final combined-source qualification remain separate open gates.
