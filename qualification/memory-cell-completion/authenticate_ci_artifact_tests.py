"""Small fake-HTTP checks; these never authenticate or download a real CI run."""

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import authenticate_ci_artifact as auth
from evidence_transport import canonical, identity


class Reply(io.BytesIO):
    def __init__(self, body, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = {} if headers is None else headers


class Endpoint:
    def __init__(self, service, storage=False):
        self.service = service
        self.storage = storage

    def open(self, request, timeout):
        self.service.requests.append((self.storage, request, timeout))
        if self.storage:
            if self.service.storage_status != 200:
                raise HTTPError(request.full_url, self.service.storage_status, "fixture", {}, None)
            return Reply(self.service.zip_bytes, headers={"Content-Length": str(len(self.service.zip_bytes))})
        if request.full_url.endswith("/zip"):
            raise HTTPError(request.full_url, 302, "fixture", {"Location": self.service.redirect}, None)
        route = request.full_url.removeprefix(auth.API)
        return Reply(canonical(self.service.routes[route]))


class Service:
    def __init__(self, directory):
        self.directory = directory
        self.requests = []
        self.redirect = "https://artifact.example.invalid/file.zip?sig=DO_NOT_PRINT"
        self.storage_status = 200
        self.members = [("INDEX.json", b'{"fixture":"index"}\n', stat.S_IFREG),
                        ("receipt.json", b'{"fixture":"not-real-evidence"}\n', stat.S_IFREG),
                        ("memory-v9-evidence.tar.xz", b"fixture-not-an-archive", stat.S_IFREG)]
        self.source = {"commit": "a" * 40, "tree": "b" * 40, "run_id": 123, "job_id": 456}
        self.manifest = {"schema": "hepta.memory.completion.transport.v1", "source": self.source}
        for key, (name, raw, _) in zip(("index", "receipt", "archive"), self.members):
            self.manifest[key] = dict(path=name, **identity(raw))
        self.origin = {"schema": "hepta.memory.completion.github-origin.v1", "repo": auth.REPOSITORY,
                       "artifact_id": 789}
        self.routes = {
            "/actions/runs/123": {"id": 123, "status": "completed", "conclusion": "success",
                "head_sha": self.source["commit"], "head_commit": {"tree_id": self.source["tree"]},
                "path": auth.WORKFLOW},
            "/actions/jobs/456": {"id": 456, "run_id": 123, "name": "verify", "status": "completed",
                "conclusion": "success", "head_sha": self.source["commit"]},
            "/actions/artifacts/789": {"id": 789, "expired": False,
                "name": "memory-v9-verification-" + self.source["commit"],
                "workflow_run": {"id": 123, "head_sha": self.source["commit"]}}
        }
        self.build_zip()

    def build_zip(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data, mode in self.members:
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (mode | 0o644) << 16
                archive.writestr(info, data)
        self.zip_bytes = raw.getvalue()
        self.origin["zip"] = identity(self.zip_bytes)
        self.routes["/actions/artifacts/789"].update(size_in_bytes=len(self.zip_bytes),
            digest="sha256:" + self.origin["zip"]["sha256"])
        self.write_inputs()

    def write_inputs(self):
        self.manifest_path = self.directory / "TRANSPORT.json"
        self.origin_path = self.directory / "GITHUB_ORIGIN.json"
        self.manifest_path.write_bytes(canonical(self.manifest))
        self.origin_path.write_bytes(canonical(self.origin))

    def client(self):
        return auth.GitHubClient("FIXTURE_TOKEN", api_opener=Endpoint(self), download_opener=Endpoint(self, True))

    def authenticate(self):
        return auth.authenticate(self.manifest_path, self.origin_path, self.client())


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hepta-auth-test-")
        self.directory = Path(self.temporary.name)
        self.service = Service(self.directory)

    def tearDown(self):
        self.temporary.cleanup()

    def test_exact_artifact_and_separate_authorization(self):
        result = self.service.authenticate()
        self.assertTrue(result["passed"])
        self.assertEqual(result["zip"], self.service.origin["zip"])
        self.assertEqual(len(self.service.requests), 5)
        for storage, request, timeout in self.service.requests:
            self.assertEqual(request.get_header("Authorization"), None if storage else "Bearer FIXTURE_TOKEN")
            self.assertEqual(timeout, 30)
        self.assertNotIn("DO_NOT_PRINT", canonical(result).decode())
        self.assertNotIn("FIXTURE_TOKEN", canonical(result).decode())

    def test_incomplete_failed_or_different_run_rejected_before_download(self):
        baseline = copy.deepcopy(self.service.routes["/actions/runs/123"])
        for change in ({"status": "in_progress"}, {"conclusion": "failure"},
                       {"path": ".github/workflows/other.yml"}, {"head_sha": "c" * 40},
                       {"head_commit": {"tree_id": "d" * 40}}):
            with self.subTest(change=change):
                self.service.routes["/actions/runs/123"] = dict(baseline, **change)
                with self.assertRaises(ValueError):
                    self.service.authenticate()
        self.assertFalse(any(storage for storage, _, _ in self.service.requests))

    def test_job_and_artifact_binding_rejected(self):
        baseline = copy.deepcopy(self.service.routes)
        for route, change in (("/actions/jobs/456", {"run_id": 999}),
                              ("/actions/jobs/456", {"conclusion": "failure"}),
                              ("/actions/artifacts/789", {"workflow_run": {"id": 999}}),
                              ("/actions/artifacts/789", {"name": "other"}),
                              ("/actions/artifacts/789", {"digest": "sha256:" + "0" * 64}),
                              ("/actions/artifacts/789", {"expired": True})):
            with self.subTest(route=route, change=change):
                self.service.routes = copy.deepcopy(baseline)
                self.service.routes[route].update(change)
                with self.assertRaises(ValueError):
                    self.service.authenticate()
        self.assertFalse(any(storage for storage, _, _ in self.service.requests))

    def test_outer_zip_and_inner_receipt_corruption_rejected(self):
        self.service.zip_bytes = b"X" + self.service.zip_bytes[1:]
        with self.assertRaises(ValueError):
            self.service.authenticate()
        name, raw, mode = self.service.members[1]
        self.service.members[1] = (name, raw.replace(b"not-real", b"bad-real"), mode)
        self.service.build_zip()
        with self.assertRaises(ValueError):
            self.service.authenticate()

    def test_extra_duplicate_escaping_and_link_zip_members_rejected(self):
        baseline = self.service.members[:]
        variants = [baseline + [("extra", b"x", stat.S_IFREG)],
                    [baseline[0], baseline[0], baseline[2]],
                    [("../INDEX.json", baseline[0][1], stat.S_IFREG)] + baseline[1:],
                    [(baseline[0][0], baseline[0][1], stat.S_IFLNK)] + baseline[1:]]
        for members in variants:
            with self.subTest(names=[item[0] for item in members]):
                self.service.members = members
                with mock.patch("warnings.warn"):
                    self.service.build_zip()
                with self.assertRaises(ValueError):
                    self.service.authenticate()

    def test_unsafe_and_additional_storage_redirect_rejected(self):
        self.service.redirect = "http://artifact.example.invalid/file.zip?sig=DO_NOT_PRINT"
        with self.assertRaises(ValueError):
            self.service.authenticate()
        self.service.redirect = "https://artifact.example.invalid/file.zip?sig=DO_NOT_PRINT"
        self.service.storage_status = 302
        with self.assertRaises(ValueError):
            self.service.authenticate()

    def test_failed_cli_receipt_contains_no_secret_or_signed_url(self):
        self.service.storage_status = 403
        output = self.directory / "failed-receipt.json"
        argv = ["authenticate_ci_artifact.py", "--transport", str(self.service.manifest_path),
                "--origin", str(self.service.origin_path), "--output", str(output)]
        console = io.StringIO()
        client = self.service.client()
        with mock.patch.object(sys, "argv", argv), mock.patch.dict(os.environ, {"GH_TOKEN": "FIXTURE_TOKEN"}), \
                mock.patch.object(auth, "GitHubClient", return_value=client), contextlib.redirect_stdout(console):
            status = auth.main()
        self.assertEqual(status, 1)
        result = json.loads(output.read_bytes())
        self.assertFalse(result["passed"])
        self.assertEqual(result["stage"], "anonymous_zip_download")
        for sensitive in ("DO_NOT_PRINT", "FIXTURE_TOKEN", "artifact.example.invalid"):
            self.assertNotIn(sensitive, console.getvalue() + output.read_text())


if __name__ == "__main__":
    unittest.main()
