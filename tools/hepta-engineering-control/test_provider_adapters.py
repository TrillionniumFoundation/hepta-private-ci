from pathlib import Path
import json
import os
import stat
import tempfile
import unittest

from control_engineering_v2.provider_adapters import ProviderCommand, invoke_provider


class ProviderAdapterTests(unittest.TestCase):
    def test_bound_json_command_does_not_need_a_shell_or_ambient_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "provider.py"
            script.write_text(
                "#!/usr/bin/env python3\n"
                "import json,sys\n"
                "r=json.load(sys.stdin)\n"
                "json.dump({'schema':'hepta.control-engineering-provider-response.v1',"
                "'providerId':r['providerId'],'operation':r['operation'],"
                "'requestDigest':r['requestDigest'],'payload':{'accepted':True}},sys.stdout)\n",
                encoding="utf-8",
            )
            script.chmod(script.stat().st_mode | stat.S_IXUSR)
            command = ProviderCommand("real-provider", str(script))
            payload, digest = invoke_provider(command, "probe", {"value": 1})
            self.assertEqual(payload, {"accepted": True})
            self.assertEqual(len(digest), 64)

    def test_fixture_identity_is_rejected_in_production(self):
        with self.assertRaisesRegex(ValueError, "production_fixture_provider_forbidden"):
            ProviderCommand("fixture-provider", "/bin/true")


if __name__ == "__main__":
    unittest.main()
