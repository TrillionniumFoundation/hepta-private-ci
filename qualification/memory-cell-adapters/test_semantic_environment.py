"""Offline control-path checks; no downloaded package is installed by this test."""
import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import ssl
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import urllib.error

from prepare_semantic_environment import (
    Bootstrap, METADATA_CACHE_MANIFEST, OfficialMetadataCache, OfficialMetadataRedirect,
    PINS, default_environment, encode, official_url, sys_tags,
)


def metadata_bootstrap(directory, offline=False):
    bootstrap = Bootstrap.__new__(Bootstrap)
    bootstrap.deadline = time.monotonic() + 60
    bootstrap.args = argparse.Namespace(metadata_offline=offline)
    bootstrap.metadata_dir = directory / "receipt-json"; bootstrap.metadata_dir.mkdir()
    bootstrap.metadata_cache = {}; bootstrap.official_cache = None
    bootstrap.receipt = {"metadata_attempts": [], "metadata_sources": []}
    return bootstrap


def pinned_cache(directory, raw, filename="tokenizers-0.22.1.json"):
    directory.mkdir(exist_ok=True)
    (directory / "tokenizers-0.22.1.json").write_bytes(raw)
    manifest = {"schema":"hepta.memory.official-pypi-json-cache.v1", "entries":[{
        "url":official_url("tokenizers", "0.22.1"), "file":filename,
        "bytes":len(raw), "sha256":hashlib.sha256(raw).hexdigest()}]}
    data = encode(manifest); (directory / METADATA_CACHE_MANIFEST).write_bytes(data)
    return hashlib.sha256(data).hexdigest()


class EnvironmentIsolation(unittest.TestCase):
    def test_original_environment_and_children_are_rejected(self):
        for destination in (Path(sys.prefix), Path(sys.prefix) / "nested-new-env"):
            args = argparse.Namespace(environment=destination, total_seconds=60)
            with self.assertRaisesRegex(ValueError, "isolated"):
                Bootstrap(args)

    def test_unrelated_existing_directory_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as directory:
            bootstrap = Bootstrap.__new__(Bootstrap)
            bootstrap.root = Path(directory)
            bootstrap.science_site = Path("/test/science/site-packages")
            bootstrap.args = argparse.Namespace(resume=False)
            bootstrap.owned = False
            with self.assertRaises(FileExistsError): bootstrap.create()
            self.assertFalse(bootstrap.owned)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_resolver_reuses_exact_science_packages_and_overlays_requested_pins(self):
        with tempfile.TemporaryDirectory() as directory:
            bootstrap = Bootstrap.__new__(Bootstrap)
            bootstrap.deadline = time.monotonic() + 60
            bootstrap.metadata_dir = Path(directory)
            bootstrap.marker_environment = default_environment()
            bootstrap.tags = {tag: i for i, tag in enumerate(sys_tags())}
            bootstrap.source = {name: {"version": version, "requires": [], "metadata_sha256": "0" * 64}
                                for name, version in {"numpy":"2.3.5", "scipy":"1.17.0", "tokenizers":"0.23.3", "joblib":"1.5.2"}.items()}
            def metadata(name, version=None):
                if version is None: return {"releases":{"3.6.0":[]}}
                filename = name.replace("-", "_") + "-" + version + "-py3-none-any.whl"
                requires = ["numpy>=1.24", "scipy>=1.10", "joblib>=1.3", "threadpoolctl>=3.2", "torch>=1; extra == 'test'"] if name == "scikit-learn" else []
                value = {"info":{"name":name,"version":version,"requires_dist":requires}, "urls":[{"filename":filename,
                    "packagetype":"bdist_wheel","yanked":False,"size":1,"requires_python":">=3.9",
                    "url":"https://files.pythonhosted.org/packages/"+filename,"digests":{"sha256":"0"*64}}]}
                (Path(directory) / f"{name}-{version}.json").write_bytes(encode(value))
                return value
            bootstrap.metadata = metadata
            selected = bootstrap.resolve()
            self.assertTrue(selected["numpy"]["reuse"]); self.assertTrue(selected["scipy"]["reuse"])
            self.assertTrue(selected["joblib"]["reuse"]); self.assertNotIn("torch", selected)
            for name, version in PINS.items():
                self.assertEqual(selected[name]["version"], version); self.assertFalse(selected[name]["reuse"])
            self.assertEqual(selected["threadpoolctl"]["version"], "3.6.0")
            with self.assertRaisesRegex(ValueError, "Torch"):
                bootstrap.resolve(["torch>=1"])
            with self.assertRaisesRegex(ValueError, "cannot satisfy"):
                bootstrap.resolve(["numpy>9"])

    def test_corrupt_cached_wheel_fails_before_any_install_or_network(self):
        with tempfile.TemporaryDirectory() as directory:
            bootstrap = Bootstrap.__new__(Bootstrap); bootstrap.wheels = Path(directory)
            path = Path(directory) / "fake-1-py3-none-any.whl"; path.write_bytes(b"bad")
            choice = {"name":"fake","version":"1","artifact":{"filename":path.name,"size":3,"digests":{"sha256":hashlib.sha256(b"yes").hexdigest()}}}
            with self.assertRaisesRegex(ValueError, "identity differs"):
                bootstrap.download(choice)

    def test_metadata_retries_transient_failure_with_20_then_30_seconds(self):
        with tempfile.TemporaryDirectory() as directory:
            bootstrap = metadata_bootstrap(Path(directory))
            bootstrap.fetch = Mock(side_effect=[urllib.error.URLError(TimeoutError("handshake timed out")), b"{}"]) 
            with patch("prepare_semantic_environment.time.sleep"):
                self.assertEqual(bootstrap.fetch_official(official_url("tokenizers", "0.22.1")), b"{}")
            self.assertEqual([call.kwargs["attempt_seconds"] for call in bootstrap.fetch.call_args_list], [20, 30])
            self.assertTrue(all(call.kwargs["official"] for call in bootstrap.fetch.call_args_list))
            self.assertEqual([row["status"] for row in bootstrap.receipt["metadata_attempts"]], ["failed", "received"])

    def test_metadata_retry_limit_and_permanent_errors(self):
        url = official_url("tokenizers", "0.22.1")
        errors = [
            (urllib.error.URLError(TimeoutError("handshake timed out")), 2),
            (urllib.error.HTTPError(url, 503, "temporary", {}, None), 2),
            (urllib.error.HTTPError(url, 404, "absent", {}, None), 1),
            (urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate differs")), 1),
            (urllib.error.URLError(PermissionError(1, "Operation not permitted")), 1),
        ]
        for error, expected_attempts in errors:
            with self.subTest(error=str(error)), tempfile.TemporaryDirectory() as directory:
                bootstrap = metadata_bootstrap(Path(directory)); bootstrap.fetch = Mock(side_effect=error)
                with patch("prepare_semantic_environment.time.sleep"), self.assertRaises(type(error)):
                    bootstrap.fetch_official(url)
                self.assertEqual(bootstrap.fetch.call_count, expected_attempts)

    def test_metadata_retry_honors_global_deadline_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            bootstrap = metadata_bootstrap(Path(directory)); bootstrap.deadline = time.monotonic() - 1
            bootstrap.fetch = Mock()
            with self.assertRaisesRegex(TimeoutError, "deadline"):
                bootstrap.fetch_official(official_url("tokenizers", "0.22.1"))
            bootstrap.fetch.assert_not_called()

    def test_pinned_offline_metadata_verifies_json_and_provenance_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bootstrap = metadata_bootstrap(root, offline=True)
            raw = encode({"info":{"name":"tokenizers", "version":"0.22.1"}, "urls":[]})
            cache = root / "cache"; digest = pinned_cache(cache, raw)
            bootstrap.official_cache = OfficialMetadataCache(cache, digest); bootstrap.fetch_official = Mock()
            self.assertEqual(bootstrap.metadata("tokenizers", "0.22.1")["info"]["version"], "0.22.1")
            bootstrap.fetch_official.assert_not_called()
            self.assertEqual(bootstrap.receipt["metadata_sources"][0]["cache_manifest_sha256"], digest)
            self.assertEqual((bootstrap.metadata_dir / "tokenizers-0.22.1.json").read_bytes(), raw)
            with self.assertRaisesRegex(ValueError, "manifest SHA256 differs"):
                OfficialMetadataCache(cache, "0" * 64)

    def test_corrupt_wrong_package_and_missing_metadata_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bootstrap = metadata_bootstrap(root, offline=True)
            raw = encode({"info":{"name":"tokenizers", "version":"0.22.1"}, "urls":[]})
            cache = root / "cache"; digest = pinned_cache(cache, raw)
            bootstrap.official_cache = OfficialMetadataCache(cache, digest); bootstrap.fetch_official = Mock()
            (cache / "tokenizers-0.22.1.json").write_bytes(raw.replace(b"tokenizers", b"TOKENIZERS"))
            with self.assertRaisesRegex(ValueError, "JSON SHA256 differs"):
                bootstrap.metadata("tokenizers", "0.22.1")
            wrong = encode({"info":{"name":"other-project", "version":"0.22.1"}, "urls":[]})
            bootstrap.official_cache = OfficialMetadataCache(cache, pinned_cache(cache, wrong))
            with self.assertRaisesRegex(ValueError, "name/version differs"):
                bootstrap.metadata("tokenizers", "0.22.1")
            with self.assertRaisesRegex(FileNotFoundError, "no entry.*onnxruntime"):
                bootstrap.metadata("onnxruntime", "1.23.2")
            bootstrap.fetch_official.assert_not_called()

    def test_metadata_cache_paths_and_redirect_origins_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory); digest = pinned_cache(cache, b"{}", filename="../escape.json")
            with self.assertRaisesRegex(ValueError, "basename"):
                OfficialMetadataCache(cache, digest)
        handler = OfficialMetadataRedirect()
        for url in ("http://pypi.org/pypi/tokenizers/json", "https://mirror.example/pypi/tokenizers/json", "https://pypi.org:444/pypi/tokenizers/json"):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "HTTPS pypi.org"):
                handler.redirect_request(None, None, 302, "redirect", {}, url)

    def test_cache_helper_builds_and_extends_verified_transfer_manifest(self):
        from cache_semantic_metadata import main
        def official_reply(url):
            parts = url.split("/")
            name, version = parts[4], parts[5] if len(parts) == 7 else "3.6.0"
            return encode({"info":{"name":name, "version":version}, "urls":[], "releases":{"3.6.0":[]}})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); first, second = root / "first", root / "second"
            with patch.object(sys, "argv", ["cache_semantic_metadata.py", "--output", str(first)]), \
                    patch.object(Bootstrap, "fetch_official", side_effect=official_reply), redirect_stdout(io.StringIO()):
                main()
            receipt = json.loads((first / "METADATA_FETCH_RESULT.json").read_bytes())
            self.assertEqual(receipt["entry_count"], 5)
            self.assertEqual(receipt["status"], "ready")
            prior = OfficialMetadataCache(first, receipt["manifest_sha256"])
            for url in prior.entries: self.assertIsNotNone(prior.read(url))
            with patch.object(sys, "argv", ["cache_semantic_metadata.py", "--output", str(second), "--extend-from", str(first),
                    "--extend-manifest-sha256", receipt["manifest_sha256"], "--request", "humanfriendly==10.0"]), \
                    patch.object(Bootstrap, "fetch_official", side_effect=official_reply), redirect_stdout(io.StringIO()):
                main()
            updated = json.loads((second / "METADATA_FETCH_RESULT.json").read_bytes())
            self.assertEqual(updated["entry_count"], 6)
            transferred = OfficialMetadataCache(second, updated["manifest_sha256"])
            for url in prior.entries: self.assertEqual(transferred.read(url), prior.read(url))


if __name__ == "__main__":
    unittest.main()
