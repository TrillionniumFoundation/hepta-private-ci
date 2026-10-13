# Group state must influence relative action order

This amends `FIVE_GROUP_SEARCH.md` after review of the initial implementation
at `735dfe7b90624baad140f5eb8710d6cec36538ac`. No training result from that
initial implementation is claimed or reinterpreted.

The original proposal readout was `sigmoid(w_s*s + w_x*phi(x_a) + b)`.
For a fixed state s, the term `w_s*s+b` is common to every candidate a; since
sigmoid is monotone, changing state cannot change candidate order. A GRU that
updates its hidden tensor therefore does not by itself establish stateful
routing. It could change estimated stop thresholds but not the relative route.

The corrected proposal readout uses

    phi(x) = tanh(project(x))
    score(s,x) = sigmoid(w_s*s + w_x*(phi(x)*(1+tanh(s))) + b)

with elementwise multiplication. This creates state-candidate interaction
without another weight matrix or any additional parameters. At zero state the
candidate path is unchanged. The 384-input/32-state controller remains 18,786
parameters by structural count; this is not measured native deployment cost.

Five additional regression definitions check actual order reversal with the
SAME candidate tensors and weights, zero-state parity, nonzero state-gradient
of a pairwise score difference, parameter count, and rejection of an old
unversioned descriptor. These are submitted test definitions, not passing
results: the local runtime remains unavailable with infrastructure ClientError.

`controller.architecture=state-candidate-interaction-v2` is now mandatory in
Group descriptors. Training and execution receipts include the same explicit
architecture identity. Although tensor shapes are unchanged, old unversioned
weights are not silently admitted under new forward semantics. A new descriptor
changes the content hash and must pass the existing independent admission.
Existing utility PROFILE, action menu, Reader implementation, controls and
independent outcome requirements remain unchanged.

This correction establishes an architecture capable of history-conditioned
ranking; it does not prove the trained controller learns a useful ordering or
that a recurrent group outperforms stateless/search controls on natural tasks.
