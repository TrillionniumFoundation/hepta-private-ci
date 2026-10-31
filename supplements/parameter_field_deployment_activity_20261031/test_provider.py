"""Offline tests for provider trust boundaries; these are not delivery receipts."""

import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
import urllib.error

from . import provider


HEAD = "a" * 40
RUN_ID = 1234567
RUN_ATTEMPT = 2


def request_fixture():
    entries = []
    for index, role in enumerate(provider.ROLES, start=1):
        label = role.removeprefix("barrier:")
        name = (
            f"hepta-r07-{RUN_ID}-{RUN_ATTEMPT}-{label}"
            if index <= 18
            else "final-" + label
        )
        entries.append(
            {
                "id": 1000 + index,
                "name": name,
                "bytes": 4,
                "sha256": hashlib.sha256(b"test").hexdigest(),
                "role": role,
            }
        )
    return {
        "schema": provider.REQUEST_SCHEMA,
        "repository": provider.REPOSITORY,
        "run_id": RUN_ID,
        "run_attempt": RUN_ATTEMPT,
        "head_sha": HEAD,
        "artifacts": entries,
    }


def run_fixture():
    return {
        "id": RUN_ID,
        "run_attempt": RUN_ATTEMPT,
        "head_sha": HEAD,
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": provider.REPOSITORY, "id": 345},
        "head_repository": {"full_name": provider.REPOSITORY, "id": 345},
        "run_started_at": "2026-10-31T10:00:00Z",
        "updated_at": "2026-10-31T11:00:00Z",
    }


def metadata_fixture(entry):
    return {
        "id": entry["id"],
        "name": entry["name"],
        "size_in_bytes": entry["bytes"],
        "digest": "sha256:" + entry["sha256"],
        "expired": False,
        "created_at": "2026-10-31T10:30:00Z",
        "updated_at": "2026-10-31T10:31:00Z",
        "expires_at": "2099-01-01T00:00:00Z",
        "workflow_run": {
            "id": RUN_ID,
            "head_sha": HEAD,
            "repository_id": 345,
            "head_repository_id": 345,
        },
    }


class Response(io.BytesIO):
    status = 200

    def __init__(self, payload, content_length=None):
        super().__init__(payload)
        self.headers = (
            {} if content_length is None else {"Content-Length": str(content_length)}
        )


class Opener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        result = next(self.responses)
        if isinstance(result, BaseException):
            raise result
        return result


def redirect(destination):
    return urllib.error.HTTPError(
        "https://api.github.com/fixture",
        302,
        "Found",
        {"Location": destination},
        io.BytesIO(),
    )


class ProviderTests(unittest.TestCase):
    def test_exact_twenty_roles_and_unique_ids(self):
        original = request_fixture()
        self.assertEqual(provider.validate_request(original), original)
        for mutate in (
            lambda d: d["artifacts"].pop(),
            lambda d: d["artifacts"][1].update(id=d["artifacts"][0]["id"]),
            lambda d: d["artifacts"][0].update(role="unregistered"),
            lambda d: d.update(repository="another/repository"),
            lambda d: d.update(run_attempt=True),
            lambda d: d["artifacts"][0].update(name="hepta-r07-1234567-1-A-17"),
        ):
            changed = copy.deepcopy(original)
            mutate(changed)
            with self.assertRaises(provider.ProviderFailure):
                provider.validate_request(changed)

    def test_completed_successful_exact_attempt_required(self):
        request = request_fixture()
        actual = run_fixture()
        self.assertEqual(
            provider.validate_run(actual, request)["run_attempt"], RUN_ATTEMPT
        )
        for field, value in (
            ("id", 1),
            ("run_attempt", 1),
            ("head_sha", "b" * 40),
            ("status", "in_progress"),
            ("conclusion", "failure"),
        ):
            changed = copy.deepcopy(actual)
            changed[field] = value
            with self.assertRaises(provider.ProviderFailure):
                provider.validate_run(changed, request)

    def test_provider_metadata_must_match_all_pins_and_current_attempt(self):
        entry = request_fixture()["artifacts"][0]
        run = provider.validate_run(run_fixture(), request_fixture())
        actual = metadata_fixture(entry)
        self.assertEqual(
            provider.validate_metadata(actual, entry, run)["id"], entry["id"]
        )
        for field, value in (
            ("size_in_bytes", 5),
            ("digest", "sha256:" + "f" * 64),
            ("expired", True),
            ("created_at", "2026-10-30T10:00:00Z"),
            ("expires_at", "2000-01-01T00:00:00Z"),
        ):
            changed = copy.deepcopy(actual)
            changed[field] = value
            with self.assertRaises(provider.ProviderFailure):
                provider.validate_metadata(changed, entry, run)
        actual["workflow_run"]["head_sha"] = "b" * 40
        with self.assertRaises(provider.ProviderFailure):
            provider.validate_metadata(actual, entry, run)

    def test_redirect_never_carries_api_token(self):
        entry = request_fixture()["artifacts"][0]
        opener = Opener(
            [
                redirect(
                    "https://productionresultssa13.blob.core.windows.net/artifact?sig=synthetic"
                ),
                Response(b"test", 4),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "artifact.zip"
            receipt = provider.download(
                opener, entry, destination, "fixture-token", time.monotonic() + 60
            )
            self.assertEqual(destination.read_bytes(), b"test")
            self.assertEqual(receipt["sha256"], entry["sha256"])
            self.assertFalse(destination.with_suffix(".zip.partial").exists())
        self.assertEqual(
            opener.requests[0].get_header("Authorization"), "Bearer fixture-token"
        )
        self.assertIsNone(opener.requests[1].get_header("Authorization"))

    def test_redirect_to_unapproved_host_is_rejected_before_contact(self):
        opener = Opener([redirect("https://attacker.example/collect")])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(provider.ProviderFailure):
                provider.download(
                    opener,
                    request_fixture()["artifacts"][0],
                    Path(directory) / "artifact.zip",
                    "fixture-token",
                    time.monotonic() + 60,
                )
        self.assertEqual(len(opener.requests), 1)

    def test_corrupt_or_oversized_download_is_retained_as_partial(self):
        for payload in (b"evil", b"toolong", b"short"[:2]):
            opener = Opener([Response(payload)])
            with tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "artifact.zip"
                with self.assertRaises(provider.ProviderFailure):
                    provider.download(
                        opener,
                        request_fixture()["artifacts"][0],
                        destination,
                        "fixture-token",
                        time.monotonic() + 60,
                    )
                self.assertFalse(destination.exists())
                self.assertTrue(destination.with_suffix(".zip.partial").exists())
                self.assertEqual(len(opener.requests), 1, "failed transfer was retried")

    def test_download_endpoint_validation(self):
        for url in (
            "http://api.github.com/file",
            "https://api.github.com.attacker.example/file",
            "https://token@api.github.com/file",
            "https://api.github.com:444/file",
            "https://unrelated.blob.core.windows.net/file",
        ):
            with self.assertRaises(provider.ProviderFailure):
                provider.allowed_download_url(url)

    def test_duplicate_json_keys_and_error_url_redaction(self):
        with self.assertRaises(provider.ProviderFailure):
            provider.parse_json(b'{"run_id":1,"run_id":2}')
        error = urllib.error.HTTPError(
            "https://example.test/?sig=do-not-print", 403, "secret detail", {}, None
        )
        rendered = json.dumps(provider.safe_error(error))
        self.assertNotIn("do-not-print", rendered)
        self.assertNotIn("secret detail", rendered)


if __name__ == "__main__":
    unittest.main()
