"""Build a new, source-bound C2 persistence successor; never execute training.

Historical evidence and the original six fits are read-only. A changed program
manifest cannot reuse the original execution decision, and this builder creates
no decision. The archived contract's resource and scientific gates remain intact.
"""

import argparse
import ast
import difflib
import hashlib
import io
import json
from pathlib import Path
import zipfile

from .atomic_io import identity, publish_json

ARCHIVE = (
    "qualification/hcsn_differentiable/evidence/"
    "p0p5-c2-launch-20261110/preparation/v4/"
    "hcsn-c2-execution-candidate-20261110-v4.zip"
)
ARCHIVE_SHA = "5e4e71233548dd0131df36b3a65f0c6afd13c06083960f4a3c458300239789c2"
SOURCE_SHA = "95d53c9a8fd7b6d0d60388b29d58519160c1d04357069bd805e5f4bfa2c91079"


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("frozen source replacement is not unique: " + old[:80])
    return source.replace(old, new, 1)


def replace_function(source, name, replacement):
    nodes = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(nodes) != 1:
        raise ValueError("expected one frozen function: " + name)
    node = nodes[0]
    lines = source.splitlines(keepends=True)
    lines[node.lineno - 1 : node.end_lineno] = [replacement.rstrip() + "\n"]
    return "".join(lines)


def repaired_sources(originals):
    source = originals["c2_io.py"].decode()
    source = replace_once(
        source,
        "import torch\n",
        "import torch\nfrom hcsn_persistence_v1.atomic_io import atomic_publish, publish_json\n",
    )
    source = replace_function(
        source,
        "exclusive_json",
        "def exclusive_json(path, value):\n    return publish_json(path, value)",
    )
    source = replace_function(
        source,
        "immutable_checkpoint",
        """
def immutable_checkpoint(path, value):
    def validate(candidate):
        restored = torch.load(candidate, map_location='cpu', weights_only=True)
        require(state_equal(value, restored), 'checkpoint safe-load round trip differs')
    return atomic_publish(path, lambda stream: torch.save(value, stream), validate)
""",
    )
    source = replace_function(
        source,
        "atomic_alias",
        """
def atomic_alias(source, target):
    source = Path(source)
    expected = identity(source)
    require(expected['bytes'] > 0, 'empty checkpoint alias source')
    def write(stream):
        with source.open('rb') as original:
            for block in iter(lambda: original.read(1024 * 1024), b''):
                stream.write(block)
    def validate(candidate):
        require(identity(candidate) == expected, 'checkpoint alias copy differs')
    return atomic_publish(target, write, validate, replace=True)
""",
    )
    repaired = {"c2_io.py": source}
    for name, view, field in (
        ("c2_runner.py", "events.jsonl", "events"),
        ("c2_controller.py", "commands.jsonl", "commands"),
    ):
        source = originals[name].decode()
        source = replace_once(
            source,
            "import traceback\n",
            "import traceback\nfrom hcsn_persistence_v1.journal import ReceiptJournal, validate_terminal_journal, process_identity\n",
        )
        source = replace_once(
            source,
            f"journal = (out / '{view}').open('x')",
            f"journal = ReceiptJournal(out / '{view}')",
        )
        indent = "            " if field == "commands" else "        "
        source = replace_once(
            source,
            f"{indent}journal.write(json.dumps(row, allow_nan=False) + '\\n')\n{indent}journal.flush()",
            f"{indent}journal.append(row)",
        )
        source = replace_once(
            source,
            "        journal.close()",
            f"        journal.close()\n        report['{field}_receipt_index'] = identity(out / '{view}.receipt-index.json')",
        )
        source = replace_once(
            source,
            "'scientific_admission': 'HOLD'",
            "'persistence_schema': 'hcsn-persistence-v1', 'scientific_admission': 'HOLD'",
        )
        clocks = (
            "        report.update(**epoch_clocks(parent_wall, started), peak_rss_bytes=study.peak_rss())\n"
            if field == "events"
            else "        report.update(controller_full_wall_seconds=time.monotonic() - CONTROLLER_STARTED,\n"
            "            controller_full_cpu_seconds=time.process_time(),\n"
            "            children_cpu_seconds=resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime,\n"
            "            controller_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)\n"
        )
        source = replace_once(source, clocks, "")
        anchor = f"        report['{field}'] = identity(out / '{view}')\n"
        source = replace_once(source, anchor, anchor + clocks)
        if field == "events":
            source = replace_once(
                source,
                "required = {'c2_runner.py'",
                "required = {'hcsn_persistence_v1/__init__.py', 'hcsn_persistence_v1/atomic_io.py', "
                "'hcsn_persistence_v1/journal.py', 'c2_runner.py'",
            )
        else:
            source = replace_once(
                source,
                "        path = Path(path)\n        require(path.is_file()",
                "        require(output.get('process_started') is True\n"
                "                and type(output.get('returncode')) is int\n"
                "                and output.get('child_terminal_unknown') is False\n"
                "                and type(output.get('pid')) is int\n"
                "                and type(output.get('process_identity')) is dict\n"
                "                and type(output['process_identity'].get('pid')) is int\n"
                "                and output['pid'] == output['process_identity']['pid'],\n"
                "                'child exit status is not independently known')\n"
                "        path = Path(path)\n        require(path.is_file()",
            )
            source = replace_once(
                source,
                "            snapshots[row['name']] = dict(row)\n            journal.append(row)",
                "            journal.append(row)\n            snapshots[row['name']] = dict(row)",
            )
            source = replace_once(
                source,
                "        require(isinstance(result, dict), 'terminal result JSON is not an object')",
                "        require(isinstance(result, dict), 'terminal result JSON is not an object')\n"
                "        require(result.get('persistence_schema') == 'hcsn-persistence-v1', 'wrong persistence source')\n"
                "        validate_terminal_journal(path.parent / 'events.jsonl', result.get('status'), output['process_identity'])\n"
                "        require(identity(path.parent / 'events.jsonl.receipt-index.json') == result.get('events_receipt_index'),\n"
                "                'terminal journal index differs')",
            )
            source = replace_once(
                source,
                "                    row.update(process_started=True, pid=process.pid, status='running')\n",
                "                    row.update(process_started=True, pid=process.pid, status='running')\n"
                "                    row['process_identity'] = process_identity(process.pid)\n",
            )
        ast.parse(source)
        repaired[name] = source
    return repaired


def materialize(repository, output):
    archive = Path(repository) / ARCHIVE
    if identity(archive)["sha256"] != ARCHIVE_SHA:
        raise ValueError("original v4 archive identity differs")
    with zipfile.ZipFile(archive) as outer:
        raw = outer.read("cloud-targeted-tests/TESTED-SOURCE.zip")
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise ValueError("original tested-source identity differs")
    with zipfile.ZipFile(io.BytesIO(raw)) as inner:
        originals = {name: inner.read(name) for name in inner.namelist()}
    manifest = json.loads(originals["PROGRAM-MANIFEST.json"])
    for name, expected in manifest["files"].items():
        value = originals[name]
        if {
            "bytes": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        } != expected:
            raise ValueError("archived program member differs: " + name)
    repaired = repaired_sources(originals)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in originals.items():
        path = output / name
        if not path.resolve().is_relative_to(output.resolve()):
            raise ValueError("unsafe archived path")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    (output / "ORIGINAL-PROGRAM-MANIFEST.json").write_bytes(
        originals["PROGRAM-MANIFEST.json"]
    )
    differences = []
    for name, source in repaired.items():
        (output / name).write_text(source)
        differences.extend(
            difflib.unified_diff(
                originals[name].decode().splitlines(True),
                source.splitlines(True),
                fromfile="original/" + name,
                tofile="successor/" + name,
            )
        )
    package = output / "hcsn_persistence_v1"
    package.mkdir()
    for name in ("__init__.py", "atomic_io.py", "journal.py"):
        (package / name).write_bytes(Path(__file__).with_name(name).read_bytes())
    (output / "SUCCESSOR.diff").write_text("".join(differences))
    publish_json(
        output / "SUCCESSOR-PROVENANCE.json",
        {
            "schema": "hcsn-persistence-successor-v1",
            "historical_fits_modified": False,
            "training_launched": False,
            "scientific_admission": "HOLD",
            "original_archive_sha256": ARCHIVE_SHA,
            "original_source_zip_sha256": SOURCE_SHA,
            "builder": identity(__file__),
            "new_decision_required_by_changed_manifest": True,
            "original_program_files": {
                name: manifest["files"][name] for name in repaired
            },
        },
    )
    manifest.update(schema="hcsn-c2-execution-program-manifest-v5-durable")
    manifest["files"] = {
        str(path.relative_to(output)): identity(path)
        for path in sorted(output.rglob("*"))
        if path.is_file() and path != output / "PROGRAM-MANIFEST.json"
    }
    (output / "PROGRAM-MANIFEST.json").unlink()
    publish_json(output / "PROGRAM-MANIFEST.json", manifest)
    return {
        "output": str(output),
        "program_manifest": identity(output / "PROGRAM-MANIFEST.json"),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(materialize(args.repository, args.output), sort_keys=True))
