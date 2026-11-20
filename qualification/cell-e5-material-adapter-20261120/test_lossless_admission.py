"""Read-only evidence tampering controls. No native tests or training are run."""

import argparse
import copy
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import lossless_admission as gate


def coherently_rename_after_case(row, blobs):
    evidence = row["native_receipts"]["after"]
    xml = ET.fromstring(gate.checked_blob(evidence["junit.xml"], blobs))
    first = next(xml.iter("testcase"))
    name = first.get("name") + "[forged_parameter]"
    first.set("name", name)
    raw = ET.tostring(xml)
    blobs[gate.sha(raw)] = raw
    evidence["junit.xml"] = {"sha256": gate.sha(raw), "bytes": len(raw)}
    receipt = gate.decode(gate.checked_blob(evidence["EXIT.json"], blobs))
    receipt["junit_sha256"] = gate.sha(raw)
    receipt["cases"][0]["name"] = name
    raw = json.dumps(receipt).encode()
    blobs[gate.sha(raw)] = raw
    evidence["EXIT.json"] = {"sha256": gate.sha(raw), "bytes": len(raw)}


def controls(root, prefix):
    positive = gate.verify(root, prefix)
    frozen = gate.decode(prefix.read_bytes())["materials"]
    index = gate.decode((root / "MATERIAL_INDEX.json").read_bytes())
    rows = [gate.decode((root / x["path"]).read_bytes()) for x in index["materials"]]
    blobs = {p.name: p.read_bytes() for p in (root / "blobs").iterdir()}
    cases = []
    for name, source_index, mutation in [
        ("revision substitution", 0, lambda r, b: r.update(before_commit="0" * 40)),
        ("invented agent trajectory", 0, lambda r, b: r.update(trajectory=[{"action": "invented"}])),
        ("invented numeric features", 0, lambda r, b: r.update(features=[1.0])),
        ("incorrect training admission", 0, lambda r, b: r.update(training_execution_admitted=True)),
        ("runtime preimage changed", 0, lambda r, b: b.__setitem__(r["runtime_patches"][0]["before"]["sha256"], b"tampered")),
        ("patch replacement missing", 0, lambda r, b: b.pop(r["runtime_patches"][0]["edits"][0]["replacement"]["sha256"])),
        ("patch span shifted", 0, lambda r, b: r["runtime_patches"][0]["edits"][0].update(before_start=0)),
        ("full runtime file omitted", 0, lambda r, b: r["snapshots"]["before"].pop()),
        ("Cython counterpart omitted", 7, lambda r, b: r["runtime_patches"].pop()),
        ("native original missing", 0, lambda r, b: r["native_receipts"]["before"].pop("junit.xml")),
        ("native after output changed", 0, lambda r, b: b.__setitem__(r["native_receipts"]["after"]["STDOUT.txt"]["sha256"], b"forged pass")),
        ("coherent JUnit and EXIT parameter rename", 0, coherently_rename_after_case),
        ("selected full test missing", 0, lambda r, b: r["native_test_files"].clear()),
        ("complete test function omitted", 0, lambda r, b: r["native_test_files"][0]["original_functions"].clear()),
        ("license notices missing", 0, lambda r, b: r["license_notices"].clear()),
        ("one of two license notices omitted", 7, lambda r, b: r.update(license_notices=[x for x in r["license_notices"] if x["path"] != "data/NOTICE.md"])),
        ("runtime roots weakened", 0, lambda r, b: r.update(runtime_roots=[])),
        ("native test selector weakened", 0, lambda r, b: r.update(native_test_selector="one_case_only")),
        ("parameter class normalization changed", 0, lambda r, b: r["native_case_class_prefixes"].update(before="")),
        ("unbound separate license revision", 6, lambda r, b: r["license_notices"][0].update(commit="0" * 40)),
        ("context size understated", 0, lambda r, b: r["context_bytes"].update(runtime_before=1)),
        ("source selection audit omitted", 0, lambda r, b: r.update(selection_and_source_provenance=[p for p in r["selection_and_source_provenance"] if not p["original_path"].endswith("SELECTION_AUDIT.json")])),
    ]:
        row, data = copy.deepcopy(rows[source_index]), dict(blobs)
        mutation(row, data)
        try:
            gate.verify_material(row, frozen[source_index], data)
        except ValueError as error:
            cases.append({"name": name, "rejected": True, "reason": str(error)})
        else:
            raise AssertionError("tampering admitted: " + name)
    return {"schema": "hepta.e5.lossless-admission-controls.v1", "positive_materials": positive["material_count"],
            "negative_controls": cases, "negative_controls_rejected": len(cases), "new_native_children": 0,
            "model_calls": 0, "training_updates": 0, "control_scope": "In-memory copies; original bytes never modified"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = controls(args.root, args.prefix)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k != "negative_controls"}, sort_keys=True))
