# Recovery independent readback

This directory contains a new audit after the scratch mount was lost. The original closed r20/r21/r22 archive bytes were restored with their original SHA256 identities. These new report bytes are not the lost prior audit artifacts.

Run from the task root with Python's standard library only:

```sh
python3 recovery-independent-readback/independent_recovery_readback.py --native-results native-validation-results
```

The reader verifies every archive member, transport mode, INDEX row and extracted byte. It rehashes all 1,367 original framework directories from the complete cached original listing, applies only each archive's 187/187/188 raw changed-source files, and independently rebuilds the complete e65356…/e65356…/be34ab… trees. The saved original target commit/root responses are comparisons after reconstruction, never reconstruction inputs.

It also binds full original log/resource hashes to raw process return codes, receipts, source/lock guards and actual controller terminal records. The r21 workspace metadata and default-members identity, compile errors and absence of test execution are checked directly. Complete project log test-ID parsing is separately recorded by differentiation_study in the new recovered-checkpoint groups.

No Cargo, Rust, just, native controller, network, source changes, finalizer, test rerun or active r23 log is used by this reader. Scientific HOLD and authority DENY_ALL are unchanged.
