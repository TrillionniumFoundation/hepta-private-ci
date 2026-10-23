"""Build an explicit derived SDK in a fresh directory, never install or auto-enable it."""
import argparse
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

CODE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch_agent(original):
    start = original.index("def _fix_tokenizer_config(")
    end = original.index("def _verify_compatibility(", start)
    changed = original[:start] + "from .readonly_tokenizer import load_readonly_tokenizer\n\n\n" + original[end:]
    start = changed.index("def _load_tokenizer(")
    end = changed.index("def _amp_context(", start)
    changed = changed[:start] + '''def _load_tokenizer(tok_dir: str, cfg: Dict) -> Any:
    """Derived local-only, no-write profile; no change to calibration or model code."""
    return load_readonly_tokenizer(tok_dir)


''' + changed[end:]
    if changed.count("        _fix_tokenizer_config(model_dir)\n") != 1:
        raise ValueError("expected exactly one official tokenizer repair call")
    return changed.replace("        _fix_tokenizer_config(model_dir)\n", "")


def build(source, output):
    expected = json.loads((CODE / "upstream.json").read_text())
    source_files = {str(p.relative_to(source)): digest(p) for p in sorted(source.rglob("*.py"))}
    if source_files != expected["source_files"]:
        raise ValueError("installed Laya source differs from the pinned official wheel")
    license_path = source.parent / "laya-0.4.14.dist-info/licenses/LICENSE"
    if digest(license_path) != expected["license_sha256"]:
        raise ValueError("official license identity mismatch")
    original = (source / "agent.py").read_text()
    changed = patch_agent(original)
    patch = "".join(difflib.unified_diff(original.splitlines(True), changed.splitlines(True), fromfile="official-laya-0.4.14/agent.py", tofile="derived-laya-readonly-v1/agent.py"))
    if hashlib.sha256(patch.encode()).hexdigest() != expected["patch_sha256"]:
        raise ValueError("derived patch differs from the reviewed patch")
    output.mkdir(parents=True, exist_ok=False)
    vendor = output / "vendor/laya"
    shutil.copytree(source, vendor, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(license_path, output / "LICENSE")
    shutil.copy2(CODE / "readonly_tokenizer.py", vendor / "readonly_tokenizer.py")
    (vendor / "agent.py").write_text(changed)
    (output / "sdk-source.patch").write_text(patch)
    derived_files = {str(p.relative_to(vendor)): digest(p) for p in sorted(vendor.rglob("*.py"))}
    if derived_files != expected["derived_files"]:
        raise ValueError("derived SDK differs from reviewed source pins")
    changed_files = [p for p in derived_files if derived_files[p] != source_files.get(p)]
    if changed_files != ["agent.py", "readonly_tokenizer.py"]:
        raise ValueError("unexpected SDK changes")
    manifest = {**expected, "derived_files": derived_files, "changed_files": changed_files, "builder_sha256": digest(Path(__file__)), "installed_package_modified": False, "calibration_code_changed": False, "strict_bakeoff_changed": False}
    (output / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="fresh diagnostic workspace")
    args = parser.parse_args()
    spec = importlib.util.find_spec("laya")
    if spec is None or spec.origin is None:
        raise SystemExit("install the pinned official Laya wheel in an isolated environment first")
    manifest = build(Path(spec.origin).parent, args.output.resolve())
    print(json.dumps({k: v for k, v in manifest.items() if k not in ("source_files", "derived_files", "upstream_wheel")}, indent=2))


if __name__ == "__main__":
    main()
