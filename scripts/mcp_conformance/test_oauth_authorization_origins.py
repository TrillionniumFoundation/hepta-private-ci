"""Source controls for the trusted fixture sideband and exact config writing."""

import json
import tempfile
import tomllib
import unittest
from pathlib import Path

from codex_conformance_adapter import (
    AdapterFailure,
    TEST_SERVER_NAME,
    _authorization_origins,
    _write_auth_registration,
)


class AuthorizationOriginSidebandTests(unittest.TestCase):
    def test_absent_sideband_and_empty_array_grant_nothing(self):
        self.assertEqual(_authorization_origins(None), [])
        self.assertEqual(_authorization_origins("[]"), [])

    def test_exact_canonical_origins_are_preserved(self):
        values = [
            "http://localhost:43123",
            "http://127.0.0.1:43124",
            "https://[::1]:43125",
            "https://authorization.example",
        ]
        self.assertEqual(_authorization_origins(json.dumps(values)), values)

    def test_metadata_objects_and_malformed_values_are_not_authority(self):
        for raw in [
            "",
            "null",
            "true",
            '{"authorization_servers":["http://localhost:43123"]}',
            '{"MCP_CONFORMANCE_AUTHORIZATION_ORIGINS":["http://localhost:43123"]}',
            '["http://localhost:43123",null]',
            '["http://localhost:43123",7]',
            '"http://localhost:43123"',
        ]:
            with self.subTest(raw=raw):
                with self.assertRaises(AdapterFailure):
                    _authorization_origins(raw)

    def test_noncanonical_origin_aliases_paths_and_credentials_are_rejected(self):
        for value in [
            "http://localhost:43123/",
            "http://localhost:43123/tenant1",
            "HTTP://localhost:43123",
            "http://LOCALHOST:43123",
            "http://localhost:80",
            "http://localhost:0",
            "http://localhost:43123?scope=private",
            "http://localhost:43123#fragment",
            "http://user:secret@localhost:43123",
            "http://127.1:43123",
            "http://2130706433:43123",
            "http://0x7f000001:43123",
            "http://0177.0.0.1:43123",
            "http://[0:0:0:0:0:0:0:1]:43123",
            "http://[fe80::1%lo]:43123",
            " https://authorization.example",
            "https://authorization.example\n",
            "ftp://localhost:43123",
        ]:
            with self.subTest(value=value):
                with self.assertRaises(AdapterFailure):
                    _authorization_origins(json.dumps([value]))

    def test_duplicates_and_bounded_input_overflow_are_rejected(self):
        with self.assertRaises(AdapterFailure):
            _authorization_origins(
                '["http://localhost:43123","http://localhost:43123"]'
            )
        values = [f"http://localhost:{port}" for port in range(43000, 43016)]
        self.assertEqual(_authorization_origins(json.dumps(values)), values)
        with self.assertRaises(AdapterFailure):
            _authorization_origins(json.dumps([*values, "http://localhost:43016"]))
        with self.assertRaises(AdapterFailure):
            _authorization_origins(json.dumps(["x" * 16385]))
        with self.assertRaises(AdapterFailure):
            _authorization_origins(" " * (16 * 16384 + 4097))

    def test_owner_origin_is_written_even_without_a_pre_registered_client(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text(
                'mcp_oauth_credentials_store = "file"\n', encoding="utf-8"
            )
            _write_auth_registration(
                config,
                server_url="http://localhost:43122/mcp",
                oauth_client_id=None,
                authorization_origins=["http://localhost:43123"],
            )
            parsed = tomllib.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(parsed["mcp_oauth_credentials_store"], "file")
            self.assertEqual(
                parsed["mcp_servers"][TEST_SERVER_NAME],
                {
                    "url": "http://localhost:43122/mcp",
                    "oauth": {"authorization_origins": ["http://localhost:43123"]},
                },
            )

    def test_origin_config_retains_client_id_and_secret_environment_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            _write_auth_registration(
                config,
                server_url="http://localhost:43122/mcp",
                oauth_client_id="registered-client",
                oauth_client_secret_env_var="MCP_CONFORMANCE_CLIENT_SECRET",
                authorization_origins=["http://localhost:43123"],
            )
            oauth = tomllib.loads(config.read_text(encoding="utf-8"))["mcp_servers"][
                TEST_SERVER_NAME
            ]["oauth"]
            self.assertEqual(
                oauth,
                {
                    "client_id": "registered-client",
                    "client_secret_env_var": "MCP_CONFORMANCE_CLIENT_SECRET",
                    "authorization_origins": ["http://localhost:43123"],
                },
            )

    def test_empty_origins_preserve_legacy_registration_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            _write_auth_registration(
                config,
                server_url="http://localhost:43122/mcp",
                oauth_client_id=None,
            )
            self.assertEqual(
                tomllib.loads(config.read_text(encoding="utf-8"))["mcp_servers"][
                    TEST_SERVER_NAME
                ],
                {"url": "http://localhost:43122/mcp"},
            )


if __name__ == "__main__":
    unittest.main()
