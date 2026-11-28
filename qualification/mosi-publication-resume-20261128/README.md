# MOSI publication resume integrity

The relay at `7caa89806980928b6adc29893da33f1827e7099b` skipped a scope whenever its local receipt path existed. A preserved controlled probe supplied invalid JSON and wrong-scope receipts without source or prediction objects; both cases returned normally without running a source validator or reading a remote object. This demonstrates a resume defect. It does not establish that actual operator receipts were corrupt or explain a missing result directory.

## Repair

The relay now parses each completion receipt strictly, requires its original schema and expected destination, and reruns the original scope validator. It reconstructs the canonical manifest from current verified inputs and binds the receipt's count, SHA256, and Git blob ID to those bytes. Before skipping, it reads the exact commit and requires every expected original and the manifest to have the matching blob OID and file mode under the expected scope.

The GitHub API reader traverses only the scope subtree. API transport failures may use native Git to fetch that exact commit from the pinned origin and inspect its tree. Logical mismatches remain incomplete. The readback fallback never pushes. Other independently appended scopes are allowed, but cannot stand in for a missing expected original. The same verification now precedes writing a new completion receipt.

Invalid receipts are retained unchanged. Missing originals, failed existing verification, nonexistent commits, malformed or truncated trees, or mismatched objects cannot authorize a skip. The lock closes when validation fails. Python `-O` and `-OO` are refused before helper loading or I/O because the original scientific verifier relies on assertions.

## Verification

At source commit `b233239cfd03e98cc5f4a37203a67d27689a05ed`, **15 controls passed**, with no failures, errors, or skips, in 1.376 seconds (1.512 seconds for the recorded command). The cases include malformed and forged receipts; changed source/manifest pins; absent originals or terminal; a manifest without its weight; a wrong blob; valid resume followed by publication of the next scope; original verifier assertion failures; and real `-O`/`-OO` subprocesses refusing before side effects.

The API protocol is backed by actual small local Git objects in these controls. The native fallback performs real `git init`, `remote`, `fetch`, `rev-parse`, and `ls-tree` calls against a temporary local origin. The trace retains their fixed commit IDs and arguments. Publishing calls are mocks; no remote write or network request occurs in these tests.

Run the regression suite from the repository root on the relay's Linux environment:

```sh
python3 -B -m unittest discover -s qualification/hcsn_sustained_20261128/mosi_recovery -p test_publish_mosi.py -v
```

`evidence.tar.gz` preserves the original counterexample, original publisher and pinned helper, all implementation attempts, exact source preimages, test logs, and the final transport trace. `INDEX.json` binds every other archive member by size and SHA256. All members were read back and compared after packaging. The first implementation attempt failed to import because of an indentation error; that failure is retained alongside the subsequent 13-, 14-, and 15-control passes. See `RESULT.json` for exact hashes, commands, resource measurements, and scope.

## Scientific and operational scope

`recovery_map`, `fresh_map`, the existing Git wrapper, and the original native publisher are unchanged. Recovery reads seals, weights, and archived predictions and checks hashes and saved-score MAE. Fresh verification reads sealed originals, writes derived recounts to a temporary directory, compares their hashes, and removes that directory. It performs no forward pass, backward pass, or fitting.

The new receipt check proves agreement with content-addressed entries in the fixed commit tree. It does not claim current branch ancestry, permanent remote availability, or stronger scientific validation than the original verifiers. No scientific result or gate is revised. No host was restarted and no operator deployment is included. Missing fresh raw custody remains unproven; these controls neither reconstruct missing historical outputs nor turn metadata into raw evidence.
