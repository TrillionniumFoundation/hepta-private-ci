# Publish the bytes that passed the original MOSI validation

## Defect and fix

The prior publisher validated live task paths, read those paths again to create
its manifest, then hardlinked them into a staging directory. A deterministic
counterexample changed the data manifest after the original mapper returned
and before the manifest read. The first publication completed with a data SHA
that contradicted its own published seal. Immutable Git readback accepted the
new manifest's objects. A later resume rejected the current data, but that did
not prevent the first incorrect completion receipt.

The retained counterexample is an explicitly synthetic publisher fixture using
real local Git objects. It does not establish corruption of any historical
scientific result. Its first wrong receipt, local commit, driver, source
preimages and fixture objects are archived without modification.

This change is based on commit 41aae3602f9f24e80ccf70dcea1bbcaa99774cb3. Both new
publication and receipt resume now follow the same sequence:

1. Capture small metadata once and derive all other canonical relative paths
   from those captured bytes. Read through directory descriptors without
   symlinks, reject nonregular files, and enforce finite byte and file-count
   bounds. Source hardlinks remain valid. A final component is opened
   nonblocking so a FIFO cannot stall before the regular-file check.
2. Materialize independent ordinary files in a new private directory. The
   directory is mode 0700, the input files are mode 0400, and no source hardlink
   is reused. Verify file identity and contents before the original validators
   run and again after they finish.
3. Run the original recovery mathematics or the original saved-prediction
   verifier against that private copy. Required task-local algorithm modules
   are compiled from the same hash-checked bytes, without reusing task module
   caches or changing global import paths.
4. Require every mapper output to refer to the captured dependency closure.
   Create the canonical manifest and Git IDs from the captured immutable byte
   values. The private validation directory is removed.
5. Give those same bytes to the original API publisher or to native Git.
   FrozenFile implements the API helper's existing read_bytes/relative_to
   protocol without reading a path. Native Git hashes stdin bytes. Retries
   retain the same values. Final fixed-commit readback remains mandatory before
   a completion receipt is saved.

A producer may change after capture without changing the already validated
publication. Replacement of a private validation input before or during
validation is rejected by the original seals or the before/after identity and
content checks. Replacing a private path after the final check cannot change
the byte values subsequently hashed or uploaded.

## Dependency and source identity

Recovery captures the historical seal, reconstruction result and candidate
hash seal first. It then captures the enrolled saved predictions and selected
weights, the recovery and source-transfer records, and the optional custody
audit. The original recovery mathematical function is unchanged.

Fresh capture covers the fresh seal and terminal, all terminal-enrolled
models/cold/result objects, the exact data manifest, AV provenance, protocol,
fresh driver, recovery record and original verifier source. Fresh math uses
the original verifier with the same enrolled designs as the original driver.

The original verifier is SHA256
bdbb45e0ad4227ef2750bb7d35ca4d2035b1c9fd8257d2c4e2c7ed7fa76b17af,
from commit 4f80d069218e5416be0f51323a9db46b461d07dd. The driver is
e7537324fb45f9bfbde4dc0078265442dd46d41e72a87eee5bdcaa12ba9fe0cd.
The source audit confirms the driver's module-level imports are all standard
library imports. NumPy, cold and verify imports inside its other functions
are not executed by this loader; none of its training, scoring or run
functions is called.

The unchanged publishing helper is pinned to
0f182311ca3e2904e469580ecab2b58240991fbac2d3254e3286f3e5570ac60d.
Its only local dependency, archive.py, is separately pinned to
be141f99e01d06eaee8febbf215cc13646f0de893f474816bf55cc4abe5c54a2
and bound within the helper's own import namespace. Global module cache
entries for archive, verify and fresh_study cannot replace those modules.
The original verifier's NumPy runtime is an explicit runtime dependency;
this is not an attestation of the entire interpreter environment.

## Actual controls

All 37 methods passed, with zero failures, errors or skips, in 54.433833
seconds. The original 21 control names are retained and adapted to the actual
capture/private-validation/immutable-byte flow. Freeze is not mocked.
The original mathematical verifier executes on clearly labeled synthetic
saved predictions. Module loading and temporary paths are observed; the
original main function is not replaced.

The additional controls cover mutation after capture and after validation,
replacement of private files before and after validation, replacement with the
same bytes but a different inode, private symlink/hardlink substitution,
legitimate source hardlinks, source directory escapes, a real FIFO with a
bounded subprocess, actual growth during a descriptor read, byte and
file-count bounds, duplicate or unsafe metadata, closure escapes, task module
cache poisoning, changed algorithm source, and immutable destination binding.
The original API helper and the changed native stdin path both operate on
real isolated Git repositories. No real remote publication occurs in these
controls.

The first terminal write had an UNKNOWN outcome. A separate scoped read
observed only the known shell and no attempt directory at that time. The
parent authorized one retry with the identical session, request ID and input.
The runner additionally creates its attempt directory exclusively before any
tests. The acknowledgement and the complete actual 37-control result are
retained. The first write remains UNKNOWN; no assertion is made that it never
executed, and no unknown external task was restarted.

## Actual original-input compatibility

A separate necessary compatibility run used the already retrieved originals
from fixed raw commit
[4b84b0431b089ccac84c75ac3ac19f96ad804fe4](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/4b84b0431b089ccac84c75ac3ac19f96ad804fe4/qualification/hcsn_sustained_20261128)
and the genuinely recovered data manifest
968dfb23d19f7ba50c9907b2146810e09922283b4b4342618e8d2eac151c4f70.
It used 190 copied original input files totaling 15,881,944 bytes. Every copied
input retained its hash. The producer's original scientific directories and
hardlinks were not read.

| Scope | Actual validation | Payload objects | Including canonical index | Payload bytes |
| --- | --- | ---: | ---: | ---: |
| Recovery | Original recovery math once | 24 | 25 | 568,777 |
| Fresh | Original saved-prediction verifier once | 166 | 167 | 15,306,173 |

Both passed. The recovery manifest is byte-identical to the original fixed
Git blob 562d179a273d674979b75c7e382009b187930d4d. The fresh manifest is exactly
the original 165-object manifest plus the original recovered data file; its
SHA256 is
10b2bb6d64bb2bb4ffe3410aa30a5efc9ee0694a1dcb67300a353077a0f25da1
and Git blob is 1fb5117e94105c84e18f1783b53eaccdb228f93c.

The two-scope compatibility operation took 2.280853 seconds. This is validation
runtime, not model training time. It performed no model forward inference,
training, new experiment, physical retiming or remote publication. These
results do not alter any scientific quality or matched-quality speed gate.

## Bounds, format and limits

This is a fixed MOSI publishing profile: at most 64 MiB of captured source
bytes, 16 MiB per ordinary input, 1 MiB per metadata object, 64 KiB per local
algorithm/helper source and 1,024 captured inputs. A repeated input still has
to satisfy a later stricter limit. These bounds do not claim to support
arbitrary model archives.

The real fresh set has a largest object of 391,018 bytes; the real recovery
set has a largest object of 51,750 bytes. Both are well within the profile.
All input discovery and publication scope checks remain fail-closed.

The parent ran the exact original just fmt driver in a separate thin Git
inventory with these two candidate files and the seven required fixed-byte
fixtures. It exited zero in 0.106332177 seconds, reported no changed files
needed formatting, and left both tested SHA256 values unchanged. The driver's
language scope excludes qualification Python; this is neither a Python-format
qualification nor a full-repository formatting claim. No tests were rerun
after that formatting invocation.

The guarantee covers this local process's publication flow and filesystem
mutation boundary. It does not claim resistance to an attacker who can
arbitrarily rewrite the same process's memory, change its trusted runtime,
or control the host kernel. It is also separate from scientific usefulness
and distributed consensus. The earlier missing-data patch, its successful
original replay, and all historical missing/wrong-manifest observations remain
unchanged.
