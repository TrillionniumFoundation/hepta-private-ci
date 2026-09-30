import subprocess
import unittest
from pathlib import Path


class BuildContractTest(unittest.TestCase):
    def test_build_contract_is_closed(self):
        root = Path(__file__).resolve().parents[3]
        subprocess.run(
            [
                "python3",
                str(
                    Path(__file__).with_name(
                        "validate_build_contract.py"
                    )
                ),
            ],
            cwd=root,
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
