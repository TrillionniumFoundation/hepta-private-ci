"""Task-local missing-state preview of the real Rust gateway entry.

No database, key or owner is created. This is developer evidence, not an
installed-product or attached-owner qualification path.
"""

import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    binary = Path(os.environ["HEPTA_GATEWAY_EXAMPLE"]).resolve(strict=True)
    if not binary.is_file():
        raise ValueError("Select the source-built gateway example executable")
    spec = importlib.util.spec_from_file_location(
        "product_launcher", ROOT / "tools/run-product.py"
    )
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    bundle = launcher.bundle_arguments(ROOT)
    process = None
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGINT)

    previous = {
        number: signal.signal(number, stop)
        for number in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        with tempfile.TemporaryDirectory(prefix="hepta-ui-missing-owner-") as state:
            if stopping:
                return
            process = subprocess.Popen(
                [
                    str(binary),
                    "--serve-ui",
                    "--listen",
                    "127.0.0.1:4175",
                    "--state-root",
                    state,
                    *bundle,
                ]
            )
            if stopping:
                process.send_signal(signal.SIGINT)
            try:
                code = process.wait()
            finally:
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            if any(Path(state).iterdir()):
                raise RuntimeError(
                    "Read-only preview unexpectedly created runtime state"
                )
            if code != 0:
                raise SystemExit(code)
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


if __name__ == "__main__":
    main()
