"""Bundle reviewed pure JS sources for functions V8; no host or graph input reads."""

import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    protocol = json.loads((root / "cell_graph_native_protocol.json").read_bytes())
    names = ("cell_graph_native_helpers.js", "cell_graph_native_adapter.js", "cell_graph_owner.js")
    checked = {}
    for name, expected in protocol["source_sha256"].items():
        path = root / name
        if not path.exists() and name == "cell_graph_owner.js":
            path = root.parent / "patch" / "qa" / "stem-bakeoff" / name
        data = path.read_bytes()
        if path.is_symlink() or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("reviewed source identity differs: " + name)
        checked[name] = data.decode("utf-8")
    sources = [checked[name] for name in names]
    source = "(() => {\n" + "\n".join(sources) + "\nreturn {create:createCellGraphNativeAdapter,execute:executeCellGraph,recover:recoverCellGraphNode};\n})()"
    data = source.encode("utf-8")
    result = {"schema": "hepta.fixed-cell-graph.native-bundle.v1", "source": source,
        "source_sha256": hashlib.sha256(data).hexdigest(), "source_bytes": len(data),
        "native_protocol_sha256": hashlib.sha256((root / "cell_graph_native_protocol.json").read_bytes()).hexdigest(),
        "wrapper_sha256": protocol["source_sha256"]["cell_graph_native_wrapper.py"],
        "dispatch_sha256": protocol["dispatch_sha256"],
        "source_sha256_map": {name: protocol["source_sha256"][name] for name in names}}
    with args.output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"path": str(args.output), "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "source_sha256": result["source_sha256"], "source_bytes": len(data)}))


if __name__ == "__main__":
    main()
