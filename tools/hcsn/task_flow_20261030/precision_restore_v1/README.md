# HCSN precision-preserving checkpoint V2 (additive follow-up)

The frozen task_flow_20261030/flow/api.py loader converts NumPy float64
data directly to JAX, silently reducing it to float32 when receiving process
jax_enable_x64=False. This makes a successful FP64 numerical certificate or
checkpoint replay inapplicable without a precision check.

Use load_checked(path, expected_precision="float64") instead. It refuses
restore *before creating JAX arrays* if x64 is disabled. Alternatively
explicitly request float32. Both legacy V1 snapshots and new V2 snapshots
are structurally validated. V2 adds a domain-separated SHA256 checksum
and an explicit precision field. The checksum is NOT a signature or an
authority credential; verify repository/owner provenance separately.

    import jax
    jax.config.update("jax_enable_x64", True)
    from tools.hcsn.task_flow_20261030.precision_restore_v1 import load_checked, save_v2
    save_v2("NEW_CHECKPOINT.npz", params, state, precision="float64")
    params2, state2 = load_checked("NEW_CHECKPOINT.npz", expected_precision="float64")

The contract checks exact names and shapes of ten parameter arrays/nine state
arrays; uniform specified floating dtype, int32 observation counter, finite
values and physical domain, conserved active/refractory probability mass,
positive decay and cost, nonnegative counters, uncompressed-size cap, duplicate
ZIP member rejection, and a create-only save. No silent repair or ignored keys.

The entrypoint does NOT mutate any historical snapshot, source freeze, failure
verdict, original flow/api.py, or native authority. Original callers still
using api.load_checkpoint may downgrade precision; migrating them is a
separate blocker. All original 28 FP64 scientific flow checks remain historical.

From the repository root:

    JAX_ENABLE_X64=1 python -m unittest -v tools.hcsn.task_flow_20261030.precision_restore_v1.test_checkpoint

The suite includes a separate Python process with JAX_ENABLE_X64=0 to prove
fail-closed behavior at restore and integration against the real flow/api.py.
It does not certify default FP32 kernel error, mixed-precision training,
task utility, secure source custody, or foundation-model performance.
