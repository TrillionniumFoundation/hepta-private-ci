"""Create a fresh verifier freeze from source and native execution protocol only.

This command never opens native corpus results. Use a new working copy/output
for an independent rerun; do not overwrite the published freeze or evidence.
"""
import argparse
import datetime
from pathlib import Path
from bridge_io import raw_bytes, read, sha, write


parser = argparse.ArgumentParser()
for name in ("acceptance", "native-protocol", "exported", "output"):
    parser.add_argument("--"+name, type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parent
acceptance = read(args.acceptance)
assert acceptance["status"] == "FROZEN_EXPORT_AND_REPLAY_ACCEPTANCE_BEFORE_NATIVE_EXECUTION"
native = read(args.native_protocol)
assert native["schema"] == "hepta.native-bellman-execution-protocol.v1" and native["planned_worlds"] == 320
toy = read(root/"VERIFIER_TOY_CHECK.json")
assert toy["passed"] and not toy["checkpoint_or_native_corpus_accessed"]
verifier_sha = sha((root/"verify_native.py").read_bytes())
assert toy["source_sha256"]["verify_native.py"] == verifier_sha
record = dict(schema="hepta-native-bellman-verifier-freeze-v1",
    frozen_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    acceptance_protocol_sha256=sha(args.acceptance.read_bytes()),
    native_execution_protocol_sha256=sha(args.native_protocol.read_bytes()),
    export_manifest_sha256=sha(raw_bytes(args.exported/"EXPORT_MANIFEST.json")),
    verifier_source_sha256=verifier_sha, bridge_io_sha256=sha((root/"bridge_io.py").read_bytes()),
    toy_check_sha256=sha((root/"VERIFIER_TOY_CHECK.json").read_bytes()),
    freeze_builder_sha256=sha(Path(__file__).read_bytes()),
    builder_reads_native_corpus_results=False,
    scope="local code/identity freeze; acceptance tolerance and exact actions remain in the earlier frozen protocol; not external preregistration")
write(args.output, record)
print(record)
