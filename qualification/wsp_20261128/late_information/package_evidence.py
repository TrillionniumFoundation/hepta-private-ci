"""Package the complete declared experiment, excluding unrelated or private data."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
OUT = ROOT / "publish/late_information"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    direct = ["RESEARCH_RESULT.md", "LATE_INFORMATION_PROTOCOL.md", "PROTOCOL_DEVIATION_01.md",
              "GRAPH_ROLLBACK_PROTOCOL.md", "POSTEXECUTION_AUDIT.json", "temporal_probe.py",
              "bridge_replay.py", "late_cue_experiment.py", "graph_rollback.py",
              "verify_recorded_results.py", "package_evidence.py"]
    paths = [(ROOT / p, "neuron_experiments/" + p) for p in direct]
    for name in ("temporal_results", "late_results", "graph_rollback_results"):
        paths += [(p, str(p.relative_to(WORK))) for p in sorted((ROOT/name).rglob("*")) if p.is_file()]
    for name in ("late_execution.stdout", "late_execution.stderr"):
        paths.append((ROOT/name, "neuron_experiments/"+name))
    prior = WORK/"prior_evidence/nov26/neuron_audit"
    for name in ("frozen_readout_diagnostic.py", "selected_checkpoints.zip", "payload/data/train.npz",
                 "payload/data/dev.npz", "payload/data/retain.npz"):
        p = prior/name
        paths.append((p, str(p.relative_to(WORK))))
    packet = WORK/"prior_evidence/native_mcp/runtime/fullmodel_mcp_qualification_v3/packet/encoded_inputs"
    for name in ("train_raw.bin", "profile47.json"):
        p = packet/name
        paths.append((p, str(p.relative_to(WORK))))
    frozen = WORK/"runtime_trace_evidence/source_frozen"
    paths += [(p, "runtime_source_frozen/"+str(p.relative_to(frozen))) for p in sorted(frozen.rglob("*")) if p.is_file()]
    paths.append((WORK/"runtime_wsp_audit/LICENSE", "runtime_source_frozen/LICENSE"))
    mem = io.BytesIO()
    manifest = []
    with tarfile.open(fileobj=mem, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for p, name in sorted(paths, key=lambda x:x[1]):
            value = p.read_bytes()
            info = tarfile.TarInfo(name)
            info.size = len(value)
            info.mode = 0o755 if name.endswith(("native-trace-frozen", "native-bridge-frozen")) else 0o644
            info.mtime = 0
            archive.addfile(info, io.BytesIO(value))
            manifest.append({"path": name, "bytes": len(value), "sha256": sha(value), "mode": info.mode})
    tarbytes = mem.getvalue()
    compressed = gzip.compress(tarbytes, compresslevel=9, mtime=0)
    chunks = []
    (OUT/"evidence.parts").mkdir()
    for i, start in enumerate(range(0, len(compressed), 450000)):
        value = compressed[start:start+450000]
        name = f"evidence.parts/{i:05}.bin"
        (OUT/name).write_bytes(value)
        chunks.append({"path": name, "bytes": len(value), "sha256": sha(value)})
    payload = {"schema": "hepta.late-information-evidence.v1", "scope": "public research parents plus synthetic late quote; no pocket4 account or trading data",
               "evidence_status": "COMPLETED_WITH_PROTOCOL_DEVIATION", "archive_sha256": sha(compressed),
               "archive_bytes": len(compressed), "uncompressed_tar_sha256": sha(tarbytes),
               "uncompressed_tar_bytes": len(tarbytes), "chunks": chunks, "files": manifest}
    (OUT/"EVIDENCE_MANIFEST.json").write_text(json.dumps(payload, indent=2)+"\n")
    for name in direct:
        shutil.copyfile(ROOT/name, OUT/name)
    for name in ("temporal_results", "late_results", "graph_rollback_results"):
        (OUT/name).mkdir()
        shutil.copyfile(ROOT/name/"RESULT.json", OUT/name/"RESULT.json")
    print(json.dumps({"files": len(manifest), "archive_bytes": len(compressed), "chunks": len(chunks), "archive_sha256": sha(compressed)}))


if __name__ == "__main__":
    main()
