# Four-amplitude Adam restart on the integrated CPU runtime

The candidate starts from de4ef594bfefec05a64fc2ae3b717a640a57b263.
The preceding integration inventory expects the workflow that installs Torch
2.8.0. On the parent, all other 17 inventory members match. The current job
installs Torch CPU 2.10.0, NumPy 2.3.5 and SciPy 1.17.0 with Python 3.12.
The previous inventory, request and intent are preserved byte for byte under
`history/20261115-current-integration-v1/`.

The new identity binds the actual workflow, package inputs and preceding
metadata before execution. It uses the existing controller and actor. The
only executable change from the parent is the protocol constant used for
checkpoint source binding and admission identity. The original loss, fixed
N7/N12 geometries, four initial-amplitude tensors, Adam settings, CPU RNG
streams, restart checks and cost limits apply. The original SPEC and request
remain available in this directory.

An independent source review precedes the hosted numerical admission. The
job retains each fresh process, its exit and cost, its complete checkpoint,
and the next stochastic loss and gradient on the continuous and resumed paths.
Expected total work is 13 forwards, 13 adjoints and 9 updates, including the
unpublished crash update. Completion and failed launches are accounted separately.
The result covers this bounded synthetic recovery experiment.
