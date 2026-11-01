# Development before the prospective frozen checks

A single default configuration was probed at dx=.0625/dt=.01. The first banded
matrix row replacement had a storage-index error: residual4.61458 and implausible
FD/reference gap1.12783. That implementation was rejected and exact source is
retained in solver_development_v0.py. Corrected row indexing produced residual
9.99e-16 and FD/reference maximum value gap.003254. Its mode0 reset contact moved
from x=.1875 at remaining.2 to x=-.375 at1.2; high STOP contact from.5 to1.125.
These probes informed development; they are not scientific confirmation.

The registered future checks use three risk profiles and four fixed meshes.
No owner world, fixed-family outcome selection or primary comparison result
has been opened before the source/protocol freeze. Expected model values will
select all fixed policies before owner draws. The unknown total CPU of early
probes is not zero, and the final worker receipt does not cover those probes.
