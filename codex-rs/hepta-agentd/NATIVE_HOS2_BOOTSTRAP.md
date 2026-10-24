# Original HOS2 adapter: explicit G2 image attachment

The original `AgentdHos2Device` now has separate entry points for the two
management-image discovery profiles supplied by the desktop kernel. They
reuse the existing device transport, immutable install request, observation,
history query and retirement-permit path. They do not construct a writer,
issuer, Registry record, Supervisor generation or FinalUse grant.

| API on the existing Linux-exported `AgentdHos2Device` | Accepted discovery record |
| --- | --- |
| `from_bootstrap` | Original G1-d HOS2BOOT version 2, declared size 192; existing behavior retained |
| `from_g2_initial_bootstrap` | G2 initial Manager or Recovery, version 3, declared size 200 |
| `from_g2_successor_bootstrap` | G2 management successor, version 4, declared size **240** |

The API selection is explicit. The old constructor does not automatically
recognize new profiles. G2 constructors take the already-open control `File`
of the current image and the sealed bootstrap discovery bytes. They check the
actual `getpid`/`getppid`, Root PID 1, distinct valid role PIDs, exact original
slot/generation layout, 50 ms write ceiling, 100 ms period and finite 300 s
initial grant. Version 4 additionally checks the actual self PID, local
capability space, nonzero launch generation and zero reserved bytes 232–239.
Both reject nonzero padding and records exceeding the 4096-byte page bound.

After those checks the original QueryAbi exchange must match this image's
namespace, boot identity, bounds and five operations. No management operation
is sent during attachment. The kernel still checks the actual `Process` and
image epoch on every ioctl; copying a page or receiving a file from another
process never grants a capability. QueryAbi is not an attestation of a build
profile or proof of a durable Hepta transaction. A real run must also bind its
kernel source/profile, embedded original ELF and actual guest evidence.

Root role 4, Workload role 2 and version-4 history-only role 5 are rejected by
both management constructors. In particular, a history successor has its own
local namespace at offset 208 while offsets 112/128 refer to retained old D
namespaces; those old namespaces must not be treated as new effect authority.
A separate history-only composition remains necessary. The kernel launch
generation is also not the original Supervisor's Registry generation, and a
launcher receipt is not proof that Root persisted it before `AckSaved`.

## Implementation and validation

The new profile checks live in [hos2_device_bootstrap.rs](src/hos2_device_bootstrap.rs),
called from the existing [device adapter](src/hos2_device.rs). The
[regressions](src/hos2_device_bootstrap_tests.rs) exercise that real adapter with
a bounded QueryAbi transport. They cover matching initial/successor Manager
and Recovery, unchanged immutable install requests, wrong actual process or
parent, aliased PIDs, wrong slots, profile confusion, 232 versus 240 bytes,
truncation, extra bytes, reserved fields and mismatched QueryAbi namespaces.
Invalid discovery does not reach the transport. These tests are library
regressions and cannot establish that the kernel or an original owner ran.

Run the owning crate with the original Rust 1.96.0 environment and original
dependency graph:

```sh
cd codex-rs
just test -p codex-hepta-agentd --lib hos2_device
just fmt
```

The finite G2 executable still needs to compose the original Supervisor,
Registry, protected Root Current/issuer, durable writer, synchronous FinalUse
device and actual retained storage. This interface change is a prerequisite;
the old peer qualification example and a successful ReadUsage probe cannot
replace that executable or its native writer/recovery evidence.
