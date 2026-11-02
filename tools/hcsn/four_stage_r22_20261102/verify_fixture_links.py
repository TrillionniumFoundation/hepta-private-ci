"""Export rejected symlink fixtures as metadata while never restoring links."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    script = Path(__file__).with_name("build_transport.py").resolve()
    rows = []
    with tempfile.TemporaryDirectory(prefix="hcsn-r22-rejected-links-") as temporary:
        root = Path(temporary)
        for name in ("allowed_metadata", "undeclared", "wrong_target", "traversal", "unlisted_upload", "capacity"):
            repo = root / name
            component = repo / "component"
            raw = component / "raw"
            raw.mkdir(parents=True)
            (raw / "record.bin").write_bytes(b"original regular evidence\n")
            target = "../../outside-not-read"
            (raw / "rejected-link").symlink_to(target)
            links = [{"path": "raw/rejected-link", "target": target}]
            if name == "wrong_target": links[0]["target"] = "different"
            if name == "traversal": links[0]["path"] = "../escape"
            if name == "unlisted_upload": (component / "extra-link").symlink_to(target)
            if name == "capacity": links = [{"path": f"raw/{i}", "target": target} for i in range(65)]
            metadata = repo / "links.json"
            metadata.write_text(json.dumps({"links": links}))
            command = [sys.executable, str(script), "--repo-root", str(repo), "--component", "component",
                       "--include", "raw", "--roundtrip", str(repo / "restored"),
                       "--upload-list", str(repo / "upload.json")]
            if name != "undeclared": command += ["--rejected-fixture-links", str(metadata)]
            child = subprocess.run(command, capture_output=True, text=True)
            if name == "allowed_metadata":
                assert child.returncode == 0, child.stderr
                assert (repo / "restored/record.bin").exists() is False
                assert (repo / "restored/raw/record.bin").read_bytes() == b"original regular evidence\n"
                assert not (repo / "restored/raw/rejected-link").is_symlink()
                assert not (repo / "restored/raw/rejected-link").exists()
            else:
                assert child.returncode != 0, name
            rows.append({"name": name, "passed": True, "exit_code": child.returncode})
    result = {"passed": True, "controls": rows, "scope": "Declared rejected input links become literal metadata; source and extracted archive links remain forbidden."}
    Path(__file__).with_name("REJECTED_LINK_TRANSPORT_CONTROLS.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
