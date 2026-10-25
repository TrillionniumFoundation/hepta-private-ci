"""Run the Rust desktop preview from a verified resource-complete staged workspace."""
import argparse
from contextlib import contextmanager
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

@contextmanager
def staged_workspace(source, prepare):
    """Own only this invocation's resources until its child process exits."""
    parent = source / "target"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="desktop-font-workspace-", dir=parent) as temporary:
        staged = Path(temporary)
        for name in ("core", "web", "robrix-ui"):
            shutil.copytree(source / name, staged / name)
        for name in ("Cargo.toml", "Cargo.lock"):
            shutil.copyfile(source / name, staged / name)
        prepare(offline=True, install=staged / "robrix-ui/resources/fonts")
        yield staged


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    args, remaining = parser.parse_known_args()
    spec = importlib.util.spec_from_file_location("hepta_fonts", ROOT / "tools/prepare-fonts.py")
    fonts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fonts)
    fonts.prepare(offline=args.offline)
    source = ROOT / "rust"
    env = dict(os.environ)
    env["CARGO_TARGET_DIR"] = str(source / "target/desktop-build")
    # subprocess.run waits for (and on interruption terminates) its child before
    # the context removes this invocation's files. Other previews are untouched.
    with staged_workspace(source, fonts.prepare) as staged:
        subprocess.run(["cargo", "+1.95.0", "run", "--locked", "--manifest-path", str(staged / "Cargo.toml"),
                        "-p", "hepta-robrix-ui", "--bin", "hepta-robrix", *(["--offline"] if args.offline else []), *remaining],
                       env=env, check=True)
