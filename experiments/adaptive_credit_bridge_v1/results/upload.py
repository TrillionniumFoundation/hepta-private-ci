"""Publish the byte-verified signed-credit evidence with a measured transfer receipt."""

import json
from pathlib import Path
import subprocess
import sys

from experiments.adaptive_neuron_v2.ledger import measured_stage
from experiments.adaptive_neuron_v2.ledger import sha
from experiments.adaptive_neuron_v2.ledger import write_json_exclusive


def main():
    archive = Path(
        "/workspace/scratch/07399998a2e3/deliverables/"
        "hepta_authenticated_credit_bridge_v1.tar.gz"
    )
    helper = Path("/tmp/hepta-library-transfer-EOluCP/library_upload.py")
    private_output = helper.with_name("signed-credit-upload-output.json")
    private_error = helper.with_name("signed-credit-upload-error.log")
    destination = Path(__file__).with_name("upload001")
    with measured_stage(
        destination,
        identity={"stage": "deliver-signed-credit-evidence"},
        scope=(
            "Validate the exact already member-verified archive SHA, execute the unmodified "
            "provided transfer helper including its child process, and save a public receipt "
            "containing only file identity, status and content hash. Interpreter startup and "
            "the final cost receipt write are outside this interval."
        ),
    ) as facts:
        expected = "b860b10029ca9db3c053846933d117cac158ff971a04949cdd353862a7ca513b"
        assert sha(archive) == expected
        request = {
            "uploads": [
                {
                    "local_path": str(archive),
                    "purpose": "create_library_file",
                    "library_artifact_type": "other",
                }
            ]
        }
        with private_output.open("x") as stdout, private_error.open("x") as stderr:
            result = subprocess.run(
                [sys.executable, str(helper)],
                input=json.dumps(request),
                text=True,
                stdout=stdout,
                stderr=stderr,
                check=False,
            )
        facts["helper_exit_code"] = result.returncode
        if result.returncode:
            raise RuntimeError(
                "Transfer helper failed; retain private diagnostics before retry"
            )
        rows = json.loads(private_output.read_text())["results"]
        assert len(rows) == 1
        row = rows[0]
        public = {
            key: row[key]
            for key in (
                "local_path",
                "status",
                "library_file_id",
                "current_version_number",
                "local_metadata_applied",
            )
        }
        assert row["status"] == "succeeded" and row["local_metadata_applied"]
        public.update(bytes=archive.stat().st_size, sha256=expected)
        write_json_exclusive(destination / "DELIVERED.json", public)
        facts.update(public)
        print(json.dumps(public))


if __name__ == "__main__":
    main()
