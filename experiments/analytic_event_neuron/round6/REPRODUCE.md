# Round6: verify, restore and replay

Use the published research checkout, with the complete source closure and inherited
freeze metadata. Run the commands below from its repository root. The transport
helper [artifact_bundle.py](artifact_bundle.py) is outside the scientific freeze.
Its raw parts contain binary bytes; connector base64 responses must be decoded
before saving them as part files.

## Registered preparation bundle

Obtain `BUNDLE.json` and its 51 declared `part-*.bin` files from the prepared-bundle
publication location. The default and maximum part size is 786,432 bytes (768 KiB).

| Identity | SHA256 |
| --- | --- |
| Prepared `BUNDLE.json` | `8fc4b70225c9ec0afc5037754d90c1b1263199927d48802276704f797c9acb88` |
| Complete prepared archive, 39,854,687 bytes | `97de2997f0c1d5a971438944f804116beb62caa34aa9296109b92e4830dd1556` |
| Restored `FREEZE.json` | `1f4d994da28d3bd61853a904d3e9da03b6ea6c90fe9d680e217f976656450ca1` |
| Restored `PREPARED.json` | `01cd90245b3d024d5be8676a684266c44a2e8e608fd9d175625db979d48d688a` |

Choose an existing downloaded bundle and create a new restore parent:

```bash
hepta_bundle=/absolute/path/to/downloaded_prepared_bundle
hepta_replay_parent=$(mktemp -d -t hepta-round6-replay.XXXXXX)
python -B -m experiments.analytic_event_neuron.round6.artifact_bundle verify \
  "$hepta_bundle" --expected-manifest-sha256 8fc4b70225c9ec0afc5037754d90c1b1263199927d48802276704f797c9acb88
python -B -m experiments.analytic_event_neuron.round6.artifact_bundle restore \
  "$hepta_bundle" "$hepta_replay_parent/registered_001" \
  --expected-manifest-sha256 8fc4b70225c9ec0afc5037754d90c1b1263199927d48802276704f797c9acb88
```

Restore checks every chunk's SHA256 and Git blob SHA1, the reassembled archive and
every member before creating the destination. It rejects unsafe paths, symlinks,
duplicates and existing destinations, and preserves executable modes. Temporary
reassembly needs writable space beside the downloaded bundle. The optional
`archive.tar.gz` is a convenience download; the restore command uses the declared
raw parts. A complete archive present in that folder is also checked against them.

## Numerical environment and original native binary

The freeze records CPython **3.12.14**, NumPy **2.3.5**, SciPy **1.17.0**, Pillow
**12.3.0**, Linux x86_64/glibc **2.39**, and the complete NumPy/SciPy OpenBLAS
**0.3.30** build reports, SIMD information and thread environment. Package version
strings alone do not establish an identical numerical environment.

In the recorded environment, perform the complete source/preparation/environment
check with its recorded interpreter:

```bash
hepta_python=/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python
"$hepta_python" -B -m experiments.analytic_event_neuron.round6.lifecycle verify \
  --run-dir "$hepta_replay_parent/registered_001" \
  --expected-freeze-sha256 1f4d994da28d3bd61853a904d3e9da03b6ea6c90fe9d680e217f976656450ca1
```

This compares the exact environment snapshot, including executable/platform and
build details, and verifies the inherited/current source hashes, prepared bytes,
passed review and freeze. A mismatch requires a separately recorded replay or
new experiment identity; preserve the original freeze.

`native/analytic_event` is the recovered original executable with SHA256
`b519cae26325f818d9596aab34504490a0b5355b9eb633369878e6f07a50e179`, originally built
from `0acfd9b27db910c180b0d8911f39aea469b7f864`. Retain its `BUILD_RECEIPT.json` and
`REUSE.json`. The build receipt's `fresh_build` flag describes that historical
build. Round6 reuses those exact bytes for new executions; it claims no new Rust
compilation. Restore preserves the executable permission.

## Development/qualification evidence and tests

Selected readable Git JSON files are indices and gates. The full smoke and native
qualification files are in the earlier development archive. Its format differs
from the prepared `BUNDLE.json` format. All six development parts were read back
at commit `87f69f40ff48a8abb3486aca0bdd2f1ec9468762`; the complete archive is also
present from commit `1db516cee8782e4c3f3f5b9f329c35dec7407f2c` onward.

In `round6/evidence`, obtain:

- `DEVELOPMENT_EVIDENCE_001_MANIFEST.json` (member manifest).
- Either `ROUND6_DEVELOPMENT_EVIDENCE_001.tar.gz`, or
  `ROUND6_DEVELOPMENT_EVIDENCE_001_PARTS.json` and
  `ROUND6_DEVELOPMENT_EVIDENCE_001.part0000` through `.part0005`.

Use a **new extraction directory outside the checkout**. This checked adapter
handles the earlier format and leaves existing readable gate files untouched:

```bash
hepta_dev_source=/absolute/path/to/downloaded_development_files
python -B - "$hepta_dev_source" "$hepta_replay_parent/development" <<'PYDEV'
import hashlib, io, json, shutil, stat, sys, tarfile
from pathlib import Path
from experiments.analytic_event_neuron.round6 import artifact_bundle as ab
source, out = map(Path, sys.argv[1:])
member_path = source / 'DEVELOPMENT_EVIDENCE_001_MANIFEST.json'
ab.require(ab.sha(member_path) == '31f50587439ffbb75385297860824d1f9e8fafb5cdd232c48e662caada61bbab', 'Member manifest changed')
manifest = json.loads(member_path.read_text(), object_pairs_hook=ab.unique)
complete = source / 'ROUND6_DEVELOPMENT_EVIDENCE_001.tar.gz'
if complete.exists():
    data = complete.read_bytes()
else:
    parts = json.loads((source / 'ROUND6_DEVELOPMENT_EVIDENCE_001_PARTS.json').read_text(), object_pairs_hook=ab.unique)
    ab.require(parts['schema'] == 'hepta.round6.binary-parts.v1' and len(parts['chunks']) == 6, 'Unknown development parts')
    chunks = []
    for i, part in enumerate(parts['chunks']):
        name = f'ROUND6_DEVELOPMENT_EVIDENCE_001.part{i:04d}'
        ab.require(Path(ab.safe(part['path'])).name == name, 'Unexpected part path')
        payload = (source / name).read_bytes()
        actual = ab.part_identity(name, payload)
        ab.require(len(payload) == part['bytes'] and actual['sha256'] == part['sha256']
                   and actual['git_blob_sha1'] == part['git_sha'], 'Part identity mismatch')
        chunks.append(payload)
    data = b''.join(chunks)
ab.require(len(data) == 3984039 and hashlib.sha256(data).hexdigest() ==
           '6be4c5bfc0d2ae329ca735f04d909f78459e43cdd627ba1c8235e1a719b1ea47', 'Development archive changed')
expected = {name: dict(entry, kind='file') for name, entry in manifest['files'].items()}
for name, entry in manifest['directories'].items():
    ab.require(name not in expected, 'Duplicate manifest member')
    expected[name] = dict(entry, kind='dir', bytes=0, sha256=None)
ab.check_tar(io.BytesIO(data), expected)  # All paths/types/modes/hashes checked first.
out.mkdir()  # Existing paths, including symlinks, are refused; parent must exist.
with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
    for item in archive:
        target = out / ab.safe(item.name)
        if item.isdir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(item) as incoming, target.open('xb') as saved:
                shutil.copyfileobj(incoming, saved)
            target.chmod(item.mode)
for name, entry in sorted(manifest['directories'].items(), reverse=True):
    (out / name).chmod(entry['mode'])
for name, entry in expected.items():
    target = out / name
    ab.require(stat.S_IMODE(target.stat().st_mode) == entry['mode'], 'Restored mode mismatch')
    if entry['kind'] == 'file':
        ab.require(target.stat().st_size == entry['bytes'] and ab.sha(target) == entry['sha256'], 'Restored bytes mismatch')
print('Verified development evidence:', out)
PYDEV
```

The restored members retain their repository-prefixed layout. Run the retained
qualification tests through their supported fixture-path option:

```bash
HEPTA_QUALIFICATION_RESULT="$hepta_replay_parent/development/experiments/analytic_event_neuron/round6/evidence/native_qualification_001/results" \
  python -B -m unittest experiments.analytic_event_neuron.round6.test_qualifier -v
```

`test_qualifier.py` requires the complete retained result directory, including
`OWNERS.zip`, its manifest, native attempts and restart files. A selected
`RESULT.json` alone is insufficient. The other four Round6 modules build their
own development fixtures:

```bash
python -B -m unittest \
  experiments.analytic_event_neuron.round6.test_math \
  experiments.analytic_event_neuron.round6.test_broker \
  experiments.analytic_event_neuron.round6.test_study \
  experiments.analytic_event_neuron.round6.test_summary -v
```

These are the advertised test commands. Broader repository discovery can require
older-round archives at fixed repository-relative paths; those additional
artifacts are outside this recipe. Keep archival extraction separate from a
checkout's readable gates. The qualifier override avoids any overlay or overwrite.

## Replay scope and new experiments

Byte verification reproduces immutable archived evidence. Fresh execution has
new timing and memory measurements; native digests incorporating those values
can change. Numerical replay compares the declared semantic fields and records
its own operating measurements and unused output namespace.

The runtime exercises the original NeuronRuntime/SparseJournal through a local
research owner with DENY_ALL posture. It grants no production Agentd activation.
The continued execution used tmpfs after the recorded storage migration; latency
figures apply to that environment. Power-loss durability, production disk/network
performance and atomic commits across owners require separate evidence.

Refitting, changing calibration/candidates/seeds/source/environment, or repeating
confirmation under a revised design creates a new experiment identity, with its
own registration, preparation, review and freeze. Preserve the existing run and
its failures, migration records and successful receipts. Review the event and
measurement boundaries in [CONTRACT.md](CONTRACT.md).

**Final confirmation bundle and result identities: pending.** This guide supplies
the prepared and development identities; the final publication index will add
actual confirmation/audit/summary artifacts when completed.
