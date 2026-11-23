"""Check the Python consumer scopes against the native participant command."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

BINARY = Path(sys.argv.pop()).resolve()
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from cell_experiments import data, paired_consumer


def printed(study, scope):
    result = subprocess.run(
        [BINARY, "--print-statement"],
        input=data.canonical({"study_sha256": study, "scope": scope}),
        capture_output=True, check=True, timeout=15,
    )
    return result.stdout, hashlib.sha256(result.stdout).hexdigest()


class JoinedContract(unittest.TestCase):
    def test_native_statement_binds_python_operation_answer_and_decision(self):
        d = data.digest
        study = d("engineering study without people")
        admission = d("fixture admission")
        selection = d("fixture selection")
        task = d({"input": "fixture subsequent task"})
        release = {"request_sha256": d("frozen pair"), "candidate_sha256": d("selected weights")}
        request = paired_consumer.request_scope(admission, release, task, selection)
        raw, request_digest = printed(study, request)
        expected_context = [
            "Hepta paired consumer use v1", f"Study SHA-256: {study}",
            f"Operation SHA-256: {request['operation']}",
            f"Paired request SHA-256: {release['request_sha256']}",
            f"Selected model manifest SHA-256: {release['candidate_sha256']}",
            f"Subsequent task SHA-256: {task}",
        ]
        self.assertEqual(raw.decode().splitlines()[:-1], expected_context)
        signed_material = {request_digest}
        output = hashlib.sha256(b"fixture answer bytes").hexdigest()
        run = {"output_sha256": output, "nonce": d("fixture nonce")}
        for decision in ("accepted", "rejected"):
            effect = hashlib.sha256(("fixture human report " + decision).encode()).hexdigest()
            scope = paired_consumer.outcome_scope(request, run, effect, decision)
            statement, digest = printed(study, scope)
            rows = statement.decode().splitlines()
            self.assertEqual(rows[:6], expected_context)
            self.assertEqual(rows[-4:], [
                f"Run receipt SHA-256: {d(run)}", f"Output bytes SHA-256: {output}",
                f"Outcome material SHA-256: {effect}", f"My decision: {decision}",
            ])
            self.assertNotIn(digest, signed_material)
            signed_material.add(digest)
            missing = subprocess.run([BINARY, "1", "/invalid/private-home", "/invalid/route"],
                                     input=json.dumps({"study_sha256": study, "delivery_id": d(decision),
                                                       "scope": scope}).encode(),
                                     capture_output=True, close_fds=True, timeout=15)
            self.assertNotEqual(missing.returncode, 0)
            self.assertEqual(missing.stdout, b"")


if __name__ == "__main__":
    unittest.main(verbosity=2)
