#!/usr/bin/env python3

import contextlib
import io
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import publish_bazel_image as publisher


class Registry:
    def __init__(self, config, *, exists=False, index=False):
        self.config = config
        self.exists = exists
        self.index = index

    def manifest(self, reference, *, missing_ok=False):
        if missing_ok:
            return ("sha256:" + "c" * 64, {}) if self.exists else None
        if self.index and reference.startswith("sha-"):
            return "sha256:" + "c" * 64, {
                "manifests": [
                    {
                        "digest": "sha256:" + "d" * 64,
                        "platform": {"os": "linux", "architecture": "amd64"},
                    },
                    {
                        "digest": "sha256:" + "e" * 64,
                        "platform": {"os": "unknown", "architecture": "unknown"},
                    },
                ]
            }
        return "sha256:" + "d" * 64, {"config": {"digest": self.config}}


class PublishBazelImageTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.evidence = self.directory / "evidence"
        self.evidence.mkdir()
        self.sha = "a" * 40
        self.config = "sha256:" + "b" * 64
        self.image = f"{publisher.IMAGE}:sha-{self.sha}-amd64"
        self.source = {
            "repository": publisher.REPOSITORY,
            "source_sha": self.sha,
            "architecture": "amd64",
            "image_tag": self.image,
        }
        self.write_source()
        (self.evidence / "verified-image-tag.txt").write_text(self.image + "\n")
        (self.evidence / "image-inspect.json").write_text(
            json.dumps([{"Id": self.config}])
        )
        self.env = {
            "GHCR_PUBLISH_TOKEN": "test-only-credential",
            "GITHUB_ACTOR": "test-user",
            "GITHUB_REPOSITORY": publisher.REPOSITORY,
            "SOURCE_SHA": self.sha,
            "IMAGE_ARCH": "amd64",
            "RUNNER_TEMP": str(self.directory),
        }
        self.calls = []

    def write_source(self):
        (self.evidence / "source.json").write_text(json.dumps(self.source))

    def run_docker(self, args, **kwargs):
        self.calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, "", "")

    def publish(self, registry):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            publisher.publish(
                self.evidence,
                self.env,
                run=self.run_docker,
                registry_factory=lambda username, token: registry,
            )
        return output.getvalue()

    def test_push_keeps_credential_out_of_argv_environment_and_evidence(self):
        output = self.publish(Registry(self.config, index=True))
        self.assertEqual(
            [call[0][1] for call in self.calls], ["login", "push", "logout"]
        )
        for argv, kwargs in self.calls:
            self.assertNotIn(self.env["GHCR_PUBLISH_TOKEN"], repr(argv))
            self.assertNotIn("GHCR_PUBLISH_TOKEN", kwargs["env"])
            self.assertFalse(Path(kwargs["env"]["DOCKER_CONFIG"]).exists())
            if argv[1] != "login":
                self.assertNotIn("input", kwargs)
        self.assertEqual(self.calls[0][1]["input"], self.env["GHCR_PUBLISH_TOKEN"])
        self.assertNotIn(self.env["GHCR_PUBLISH_TOKEN"], output)
        evidence = (self.evidence / "published-image.json").read_text()
        self.assertNotIn(self.env["GHCR_PUBLISH_TOKEN"], evidence)
        result = json.loads(evidence)
        self.assertFalse(result["anonymous_pull_verified"])
        self.assertEqual(result["config_digest"], self.config)
        self.assertEqual(result["image_digest"], "sha256:" + "d" * 64)

    def test_existing_source_tag_never_reaches_docker_push(self):
        with self.assertRaisesRegex(
            publisher.PublicationError, "refusing to overwrite"
        ):
            self.publish(Registry(self.config, exists=True))
        self.assertEqual(self.calls, [])

    def test_other_repository_or_source_never_authenticates(self):
        for field, value in [
            ("GITHUB_REPOSITORY", "someone/other-repository"),
            ("SOURCE_SHA", "f" * 40),
            ("IMAGE_ARCH", "arm64"),
        ]:
            with self.subTest(field=field):
                environment = dict(self.env, **{field: value})
                with self.assertRaises(publisher.PublicationError):
                    publisher.publish(
                        self.evidence,
                        environment,
                        run=self.run_docker,
                        registry_factory=lambda *_: self.fail("must not authenticate"),
                    )
        self.assertEqual(self.calls, [])

    def test_other_registry_and_incomplete_verification_never_authenticate(self):
        for image in ["other.example/package:tag", self.image + "-different"]:
            with self.subTest(image=image):
                self.source["image_tag"] = image
                self.write_source()
                with self.assertRaises(publisher.PublicationError):
                    publisher.publish(
                        self.evidence,
                        self.env,
                        run=self.run_docker,
                        registry_factory=lambda *_: self.fail("must not authenticate"),
                    )

    def test_changed_registry_config_is_not_recorded_as_verified(self):
        with self.assertRaisesRegex(
            publisher.PublicationError, "differs from the locally verified"
        ):
            self.publish(Registry("sha256:" + "f" * 64))
        self.assertFalse((self.evidence / "published-image.json").exists())
        self.assertEqual(self.calls[-1][0], ["docker", "logout", "ghcr.io"])
        self.assertFalse(Path(self.calls[-1][1]["env"]["DOCKER_CONFIG"]).exists())

    def test_failed_push_cleans_credentials_without_success_evidence(self):
        def failed_push(args, **kwargs):
            self.calls.append((args, kwargs))
            return subprocess.CompletedProcess(
                args,
                1 if args[1] == "push" else 0,
                "",
                "potentially sensitive tool output",
            )

        with self.assertRaisesRegex(publisher.PublicationError, "no verified digest"):
            publisher.publish(
                self.evidence,
                self.env,
                run=failed_push,
                registry_factory=lambda *_: Registry(self.config),
            )
        self.assertFalse((self.evidence / "published-image.json").exists())
        self.assertEqual(self.calls[-1][0][1], "logout")
        self.assertFalse(Path(self.calls[-1][1]["env"]["DOCKER_CONFIG"]).exists())

    def test_authenticated_redirect_is_rejected(self):
        with self.assertRaisesRegex(publisher.PublicationError, "redirected"):
            publisher.NoRedirects().redirect_request(
                None, None, 302, "", {}, "https://other.example/token"
            )

    def test_only_manifest_404_means_tag_is_absent(self):
        registry = publisher.Ghcr.__new__(publisher.Ghcr)
        registry.bearer = "test-only-bearer"
        for status in (401, 403, 404, 429, 500):
            with self.subTest(status=status):
                with patch.object(publisher, "build_opener") as opener:
                    registry.opener = opener.return_value
                    registry.opener.open.side_effect = HTTPError(
                        "https://ghcr.io", status, "", {}, None
                    )
                    if status == 404:
                        self.assertIsNone(registry.manifest("sha-tag", missing_ok=True))
                    else:
                        with self.assertRaises(publisher.PublicationError):
                            registry.manifest("sha-tag", missing_ok=True)


if __name__ == "__main__":
    unittest.main()
