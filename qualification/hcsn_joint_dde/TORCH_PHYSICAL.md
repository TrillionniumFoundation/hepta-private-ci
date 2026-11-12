# CPU physical VJP and real optimizer continuation

The first-order custom autograd bridge evaluates the checked variational DDE
anew on every forward. Backward computes its full physical VJP. Its host-array
conversion is inside this explicit custom differentiation contract; it is not
a detached forward presented as native automatic differentiation. Only the
five CPU FP64 physical parameters are differentiable. Initial probability and
signed content must be fixed NumPy arrays; Tensor initial laws are rejected.
Episode-prior, trainable content-network and second derivatives are unsupported.

The bridge saves both the original parameter Tensor and an immutable value
snapshot with its Jacobian. Normal in-place updates trigger Torch's version
guard, and unsafe `.data` changes trigger a value check. A separate actual
desktop RED reproduced the old bridge accepting a changed theta with its old
Jacobian (one forward/VJP, zero optimizer updates); the reviewed bridge refuses
both mutation routes. Forward values and the entire Jacobian must be finite.

Two native attempts are separate. Attempt 001 passed Torch gradcheck and a
small physical fit/replay but predated the parameter mutation repair. Attempt
002, desktop job 1a1ce769bb9-2564-1696, has authoritative succeeded/exit-zero,
complete durable output and confirmed terminal publication. It passed native
Torch gradcheck, both mutation controls, trainable-initial-state refusal, and
source-mismatch checkpoint refusal. It executed four Adam updates: a two-step
continuous fit versus a one-step fit followed by a new Python process for the
second step. Parameters, complete Adam state, Torch RNG and recorded losses,
targets and gradients agree exactly. All five physical gradients are nonzero.
This is a fixed-prior three-feature physics fit, not an agent task or full HCSN
network training. It does not increase original full-C2 replay counts.

Attempt 002 used Python 3.12.3, NumPy 2.3.5, SciPy 1.17.0 and Torch 2.8.0+cu128
on CPU with one thread. Main probe wall time was 25.630582238081843 seconds;
parent imports, remote transfer, packaging and the earlier attempt are outside
that timer; child-interpreter imports are included. The resource-counter probe
is POSIX-specific. Source hashes are verified before/after. The new-process actors use
the same executable and libraries; cross-runtime checkpoint replay is not
qualified. Checkpoints bind source identities, not arbitrary runtime upgrades.

Original source bundles, native result/logs/actor checkpoints and authoritative
receipts are retained under evidence/physical-sensitivities-20261112. The
preformat numeric/native source and final AST-equivalence mapping are explicit.
New exact-source hosted CI is separate and its result must be read directly.

```bash
python -B -m qualification.hcsn_joint_dde.native_gradient_probe probe --output NEW_DIRECTORY
```

The uniform-grid forward model still has short-gap first-hit bias. This bridge
does not qualify graded-grid gradients, continuum accuracy, relative rare tails,
full network/prior AD, task benefit, energy or adoption. HOLD_NO_GO.
