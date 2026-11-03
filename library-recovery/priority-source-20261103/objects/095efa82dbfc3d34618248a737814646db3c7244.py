"""Copy installed official wheel source, apply an explicit isolated patch, retain identities."""
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
SOURCE = Path(importlib.util.find_spec("laya").origin).parent
INSPECTED = ROOT.parent / "laya-release-inspection/0.4.14/agent.py"
VENDOR = ROOT / "vendor/laya"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


if VENDOR.exists():
    raise SystemExit("candidate already exists; do not overwrite prior evidence")
assert digest(SOURCE / "agent.py") == digest(INSPECTED), "installed source differs from inspected official wheel"
shutil.copytree(SOURCE, VENDOR, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
license_path = SOURCE.parent / "laya-0.4.14.dist-info/licenses/LICENSE"
shutil.copy2(license_path, ROOT / "LICENSE")
shutil.copy2(ROOT / "readonly_tokenizer.py", VENDOR / "readonly_tokenizer.py")
original = (SOURCE / "agent.py").read_text()
start = original.index("def _fix_tokenizer_config(")
end = original.index("def _verify_compatibility(", start)
changed = original[:start] + "from .readonly_tokenizer import load_readonly_tokenizer\n\n\n" + original[end:]
start = changed.index("def _load_tokenizer(")
end = changed.index("def _amp_context(", start)
changed = changed[:start] + '''def _load_tokenizer(tok_dir: str, cfg: Dict) -> Any:
    """Derived local-only, no-write profile; no change to calibration or model code."""
    return load_readonly_tokenizer(tok_dir)


''' + changed[end:]
assert changed.count("        _fix_tokenizer_config(model_dir)\n") == 1
changed = changed.replace("        _fix_tokenizer_config(model_dir)\n", "")
(VENDOR / "agent.py").write_text(changed)
patch = "".join(difflib.unified_diff(original.splitlines(True), changed.splitlines(True), fromfile="official-laya-0.4.14/agent.py", tofile="derived-laya-readonly-v1/agent.py"))
(ROOT / "sdk-source.patch").write_text(patch)
source_files = {str(p.relative_to(SOURCE)): digest(p) for p in sorted(SOURCE.rglob("*.py"))}
vendor_files = {str(p.relative_to(VENDOR)): digest(p) for p in sorted(VENDOR.rglob("*.py"))}
changed_files = [p for p in vendor_files if vendor_files[p] != source_files.get(p)]
assert changed_files == ["agent.py", "readonly_tokenizer.py"], changed_files
manifest = {"profile": "laya-0.4.14-local-readonly-extra-special-token-map-v1", "upstream_wheel": json.loads((ROOT.parent / "laya-release-inspection/0.4.14/wheel-manifest.json").read_text()), "source_files": source_files, "derived_files": vendor_files, "changed_files": changed_files, "patch_sha256": digest(ROOT / "sdk-source.patch"), "builder_sha256": digest(Path(__file__)), "installed_package_modified": False, "calibration_code_changed": False, "strict_bakeoff_changed": False}
(ROOT / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps({k: v for k, v in manifest.items() if k not in ("source_files", "derived_files", "upstream_wheel")}, indent=2))
