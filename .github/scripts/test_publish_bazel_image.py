#!/usr/bin/env python3

import base64
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import publish_bazel_image as publisher
import bazel_image_identity as identity


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
        self.image = f"{publisher.IMAGE}:sha-{self.sha}-amd64"
        self.source = {
            "repository": publisher.REPOSITORY,
            "source_sha": self.sha,
            "architecture": "amd64",
            "image_tag": self.image,
            "base_image": "ubuntu@sha256:" + "1" * 64,
            "dockerfile_sha256": "2" * 64,
        }
        config = {
            "os": "linux",
            "architecture": "amd64",
            "config": {
                "User": "ubuntu",
                "Labels": {
                    "org.opencontainers.image.source": "https://github.com/"
                    + publisher.REPOSITORY,
                    "org.opencontainers.image.revision": self.sha,
                    "org.opencontainers.image.base.name": self.source["base_image"],
                    "org.opencontainers.image.base.digest": "sha256:" + "1" * 64,
                    "io.hepta.dockerfile.sha256": "2" * 64,
                },
            },
            "rootfs": {"type": "layers", "diff_ids": []},
        }
        config_bytes = json.dumps(config).encode()
        self.config = identity.digest(config_bytes)
        self.write_source()
        (self.evidence / "verified-image-tag.txt").write_text(self.image + "\n")
        (self.evidence / "image-inspect.json").write_text(
            json.dumps(
                [
                    {
                        "Id": self.config,
                        "Os": "linux",
                        "Architecture": "amd64",
                        "Config": config["config"],
                        "RootFS": {"Layers": []},
                    }
                ]
            )
        )
        (self.evidence / "verified-image-id.txt").write_text(self.config + "\n")
        (self.evidence / "local-image-identity.json").write_text(
            json.dumps(
                {
                    "schema": "hepta-local-image-identity-v1",
                    "image_id": self.config,
                    "architecture": "amd64",
                    "identity_kind": "classic-config-id",
                    "image_manifest_digest": None,
                    "config_digest": self.config,
                    "members": {
                        "manifest.json": base64.b64encode(
                            json.dumps(
                                [{"Config": "config.json", "Layers": []}]
                            ).encode()
                        ).decode(),
                        "config.json": base64.b64encode(config_bytes).decode(),
                    },
                }
            )
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

    def test_invalid_local_identity_never_authenticates(self):
        path = self.evidence / "local-image-identity.json"
        original = json.loads(path.read_text())
        for mutation in ("bytes", "smoked-id"):
            with self.subTest(mutation=mutation):
                proof = copy.deepcopy(original)
                (self.evidence / "verified-image-id.txt").write_text(self.config + "\n")
                if mutation == "bytes":
                    data = base64.b64decode(proof["members"]["config.json"]) + b" "
                    proof["members"]["config.json"] = base64.b64encode(data).decode()
                else:
                    (self.evidence / "verified-image-id.txt").write_text(
                        "sha256:" + "f" * 64
                    )
                path.write_text(json.dumps(proof))
                with self.assertRaisesRegex(
                    publisher.PublicationError, "identity evidence"
                ):
                    publisher.publish(
                        self.evidence,
                        self.env,
                        run=self.run_docker,
                        registry_factory=lambda *_: self.fail("must not authenticate"),
                    )
                self.assertEqual(self.calls, [])

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


# Exact metadata bytes from Docker 29.1.3 image save on ai395, job
# 1a1aaff47f9-fc05-4957, source 4b4b70b3c0004196b73519ec1b28fd66eefbc748.
# Original 69,277,696-byte archive SHA256:
# 05daec73f7d59f32aff5ad4ae6b604177ec23d6cd813cf0a1f0102a433f366a6.
# Layer bodies are omitted from this metadata-only unit fixture.
REAL_IMAGE_ID = (
    "sha256:c6bd5a949d6e91fcd89eada6b59677758ec8b41e0a9490ea6266777062b9865f"
)
REAL_MANIFEST_ID = (
    "sha256:a3c476f718bf5ebe17742bf4e745343dac0b1d03f72b4e4e059e54aacf8c03e1"
)
REAL_CONFIG_ID = (
    "sha256:8f9a6153cdbb885e90b06e392f3efd05f3a403742b9be86b36271879d2922c09"
)
REAL_MEMBERS = {
    "index.json": (
        "eyJzY2hlbWFWZXJzaW9uIjoyLCJtZWRpYVR5cGUiOiJhcHBsaWNhdGlvbi92bmQub2NpLmltYWdlLmluZGV4LnYx"
        "K2pzb24iLCJtYW5pZmVzdHMiOlt7Im1lZGlhVHlwZSI6ImFwcGxpY2F0aW9uL3ZuZC5vY2kuaW1hZ2UuaW5kZXgu"
        "djEranNvbiIsImRpZ2VzdCI6InNoYTI1NjpjNmJkNWE5NDlkNmU5MWZjZDg5ZWFkYTZiNTk2Nzc3NThlYzhiNDFl"
        "MGE5NDkwZWE2MjY2Nzc3MDYyYjk4NjVmIiwic2l6ZSI6ODU2fV19"
    ),
    "blobs/sha256/c6bd5a949d6e91fcd89eada6b59677758ec8b41e0a9490ea6266777062b9865f": (
        "ewogICJzY2hlbWFWZXJzaW9uIjogMiwKICAibWVkaWFUeXBlIjogImFwcGxpY2F0aW9uL3ZuZC5vY2kuaW1hZ2Uu"
        "aW5kZXgudjEranNvbiIsCiAgIm1hbmlmZXN0cyI6IFsKICAgIHsKICAgICAgIm1lZGlhVHlwZSI6ICJhcHBsaWNh"
        "dGlvbi92bmQub2NpLmltYWdlLm1hbmlmZXN0LnYxK2pzb24iLAogICAgICAiZGlnZXN0IjogInNoYTI1NjphM2M0"
        "NzZmNzE4YmY1ZWJlMTc3NDJiZjRlNzQ1MzQzZGFjMGIxZDAzZjcyYjRlNGUwNTllNTRhYWNmOGMwM2UxIiwKICAg"
        "ICAgInNpemUiOiAxMDU0LAogICAgICAicGxhdGZvcm0iOiB7CiAgICAgICAgImFyY2hpdGVjdHVyZSI6ICJhbWQ2"
        "NCIsCiAgICAgICAgIm9zIjogImxpbnV4IgogICAgICB9CiAgICB9LAogICAgewogICAgICAibWVkaWFUeXBlIjog"
        "ImFwcGxpY2F0aW9uL3ZuZC5vY2kuaW1hZ2UubWFuaWZlc3QudjEranNvbiIsCiAgICAgICJkaWdlc3QiOiAic2hh"
        "MjU2OmYyMTc0ZTQ2YTQ3YTk5ZTdjOGU0ZDMwNzZlN2E4OThmNjQ2MDFkNDU1YzZhZDJhMjhiYjJmZTNiNjRmY2Y1"
        "ZTEiLAogICAgICAic2l6ZSI6IDU2NiwKICAgICAgImFubm90YXRpb25zIjogewogICAgICAgICJ2bmQuZG9ja2Vy"
        "LnJlZmVyZW5jZS5kaWdlc3QiOiAic2hhMjU2OmEzYzQ3NmY3MThiZjVlYmUxNzc0MmJmNGU3NDUzNDNkYWMwYjFk"
        "MDNmNzJiNGU0ZTA1OWU1NGFhY2Y4YzAzZTEiLAogICAgICAgICJ2bmQuZG9ja2VyLnJlZmVyZW5jZS50eXBlIjog"
        "ImF0dGVzdGF0aW9uLW1hbmlmZXN0IgogICAgICB9LAogICAgICAicGxhdGZvcm0iOiB7CiAgICAgICAgImFyY2hp"
        "dGVjdHVyZSI6ICJ1bmtub3duIiwKICAgICAgICAib3MiOiAidW5rbm93biIKICAgICAgfQogICAgfQogIF0KfQ=="
    ),
    "blobs/sha256/a3c476f718bf5ebe17742bf4e745343dac0b1d03f72b4e4e059e54aacf8c03e1": (
        "ewogICJzY2hlbWFWZXJzaW9uIjogMiwKICAibWVkaWFUeXBlIjogImFwcGxpY2F0aW9uL3ZuZC5vY2kuaW1hZ2Uu"
        "bWFuaWZlc3QudjEranNvbiIsCiAgImNvbmZpZyI6IHsKICAgICJtZWRpYVR5cGUiOiAiYXBwbGljYXRpb24vdm5k"
        "Lm9jaS5pbWFnZS5jb25maWcudjEranNvbiIsCiAgICAiZGlnZXN0IjogInNoYTI1Njo4ZjlhNjE1M2NkYmI4ODVl"
        "OTBiMDZlMzkyZjNlZmQwNWYzYTQwMzc0MmI5YmU4NmIzNjI3MTg3OWQyOTIyYzA5IiwKICAgICJzaXplIjogMjYx"
        "MAogIH0sCiAgImxheWVycyI6IFsKICAgIHsKICAgICAgIm1lZGlhVHlwZSI6ICJhcHBsaWNhdGlvbi92bmQub2Np"
        "LmltYWdlLmxheWVyLnYxLnRhcitnemlwIiwKICAgICAgImRpZ2VzdCI6ICJzaGEyNTY6N2E0OGI4ZjBlNWM3M2Qw"
        "Y2MyYTg1YjAwODk3ODM5NmFhMTlkMjUzZGMxYjk2ZmRiMGI3NjllZTZkY2JlY2E0YSIsCiAgICAgICJzaXplIjog"
        "Mjk3Njc2MTIKICAgIH0sCiAgICB7CiAgICAgICJtZWRpYVR5cGUiOiAiYXBwbGljYXRpb24vdm5kLm9jaS5pbWFn"
        "ZS5sYXllci52MS50YXIrZ3ppcCIsCiAgICAgICJkaWdlc3QiOiAic2hhMjU2OjI0OTRlNjBjMGUxZTAzODhmMjAz"
        "OWQ5ZTFmYjM1ODM2ODRiNGRkZWIyMjc1ZWRlN2VmMjE3MDk3M2MwYjAzNzAiLAogICAgICAic2l6ZSI6IDM4Njg5"
        "OTE5CiAgICB9LAogICAgewogICAgICAibWVkaWFUeXBlIjogImFwcGxpY2F0aW9uL3ZuZC5vY2kuaW1hZ2UubGF5"
        "ZXIudjEudGFyK2d6aXAiLAogICAgICAiZGlnZXN0IjogInNoYTI1NjphMzgzMGM0YjA5NDg2NzZmNDkzODY4OTEy"
        "ZDAyOTNhNDdjZjk4NmI1OTVmYWU0MzZlNzRiOWQ5NTAzODc2MWQ2IiwKICAgICAgInNpemUiOiA4MDAxOTIKICAg"
        "IH0sCiAgICB7CiAgICAgICJtZWRpYVR5cGUiOiAiYXBwbGljYXRpb24vdm5kLm9jaS5pbWFnZS5sYXllci52MS50"
        "YXIrZ3ppcCIsCiAgICAgICJkaWdlc3QiOiAic2hhMjU2OmQwZmVjMWM0ZWFkNDM3ZDBjMjkwMzExZWUwOTQ1MWMx"
        "NjYzMWVjNzYzZWQyYTQ3Yjc3ZDhjODM3OGVkZWQwZWIiLAogICAgICAic2l6ZSI6IDEwMgogICAgfQogIF0KfQ=="
    ),
    "blobs/sha256/8f9a6153cdbb885e90b06e392f3efd05f3a403742b9be86b36271879d2922c09": (
        "eyJhcmNoaXRlY3R1cmUiOiJhbWQ2NCIsImNvbmZpZyI6eyJVc2VyIjoidWJ1bnR1IiwiRW52IjpbIlBBVEg9L3Vz"
        "ci9sb2NhbC9zYmluOi91c3IvbG9jYWwvYmluOi91c3Ivc2JpbjovdXNyL2Jpbjovc2JpbjovYmluIl0sIkNtZCI6"
        "WyIvYmluL2Jhc2giXSwiV29ya2luZ0RpciI6Ii93b3Jrc3BhY2UiLCJMYWJlbHMiOnsiaW8uaGVwdGEuZG9ja2Vy"
        "ZmlsZS5zaGEyNTYiOiI5MmNhOTI3ZTRhNzNmOTlkY2E5MTcyMmZmYzUyMjU0MjY4MWE4OWIwMjkyYzY1NWZmMGNl"
        "MmNmOWU3NDFhYTQ4Iiwib3JnLm9wZW5jb250YWluZXJzLmltYWdlLmJhc2UuZGlnZXN0Ijoic2hhMjU2Ojc4ZDQ3"
        "NDRlYWQxZjViMTliMDRkMGRmNTU4YWIxODJhNTMwMDkwMzkwMDc1NWU1MTViMmNhNGQxMGViMjA0NGQiLCJvcmcu"
        "b3BlbmNvbnRhaW5lcnMuaW1hZ2UuYmFzZS5uYW1lIjoidWJ1bnR1QHNoYTI1Njo3OGQ0NzQ0ZWFkMWY1YjE5YjA0"
        "ZDBkZjU1OGFiMTgyYTUzMDA5MDM5MDA3NTVlNTE1YjJjYTRkMTBlYjIwNDRkIiwib3JnLm9wZW5jb250YWluZXJz"
        "LmltYWdlLnJldmlzaW9uIjoiNGI0YjcwYjNjMDAwNDE5NmI3MzUxOWVjMWIyOGZkNjZlZWZiYzc0OCIsIm9yZy5v"
        "cGVuY29udGFpbmVycy5pbWFnZS5zb3VyY2UiOiJodHRwczovL2dpdGh1Yi5jb20vVHJpbGxpb25uaXVtRm91bmRh"
        "dGlvbi9oZXB0YS1wcml2YXRlLWNpIiwib3JnLm9wZW5jb250YWluZXJzLmltYWdlLnZlcnNpb24iOiIyNC4wNCJ9"
        "fSwiY3JlYXRlZCI6IjIwMjYtMTEtMDVUMTc6MDY6MTQuMzg4OTIxNDkxKzA4OjAwIiwiaGlzdG9yeSI6W3siY3Jl"
        "YXRlZCI6IjIwMjYtMTAtMjVUMTQ6MTc6NDUuMTM0OTk0MDYxWiIsImNyZWF0ZWRfYnkiOiIvYmluL3NoIC1jICMo"
        "bm9wKSAgQVJHIFJFTEVBU0UiLCJlbXB0eV9sYXllciI6dHJ1ZX0seyJjcmVhdGVkIjoiMjAyNi0xMC0yNVQxNDox"
        "Nzo0NS4xNzQyMzUxMDlaIiwiY3JlYXRlZF9ieSI6Ii9iaW4vc2ggLWMgIyhub3ApICBBUkcgTEFVTkNIUEFEX0JV"
        "SUxEX0FSQ0giLCJlbXB0eV9sYXllciI6dHJ1ZX0seyJjcmVhdGVkIjoiMjAyNi0xMC0yNVQxNDoxNzo0NS4yMTMx"
        "MDAxMThaIiwiY3JlYXRlZF9ieSI6Ii9iaW4vc2ggLWMgIyhub3ApICBMQUJFTCBvcmcub3BlbmNvbnRhaW5lcnMu"
        "aW1hZ2UudmVyc2lvbj0yNC4wNCIsImVtcHR5X2xheWVyIjp0cnVlfSx7ImNyZWF0ZWQiOiIyMDI2LTEwLTI1VDE0"
        "OjE3OjQ3LjQzMjA1ODQ1OVoiLCJjcmVhdGVkX2J5IjoiL2Jpbi9zaCAtYyAjKG5vcCkgQUREIGZpbGU6ZWVkODhl"
        "OTRkNmFhN2M5ZGE2MjgzNmUxMzdmODg5ZTAzOTg4YzFhNmIyMzdiMGNlZGI2Y2E2NjZkZmFhOThlYSBpbiAvICJ9"
        "LHsiY3JlYXRlZCI6IjIwMjYtMTAtMjVUMTQ6MTc6NDcuODQxMzU2MTU1WiIsImNyZWF0ZWRfYnkiOiIvYmluL3No"
        "IC1jICMobm9wKSAgQ01EIFtcIi9iaW4vYmFzaFwiXSIsImVtcHR5X2xheWVyIjp0cnVlfSx7ImNyZWF0ZWQiOiIy"
        "MDI2LTExLTA1VDE3OjA1OjUwLjM0NjYxMzIyNSswODowMCIsImNyZWF0ZWRfYnkiOiJSVU4gL2Jpbi9zaCAtYyBh"
        "cHQtZ2V0IHVwZGF0ZSBcdTAwMjZcdTAwMjYgICAgIGFwdC1nZXQgaW5zdGFsbCAteSAtLW5vLWluc3RhbGwtcmVj"
        "b21tZW5kcyAgICAgY3VybCBnaXQgcHl0aG9uMyBjYS1jZXJ0aWZpY2F0ZXMgb3BlbnNzaC1jbGllbnQgXHUwMDI2"
        "XHUwMDI2ICAgICBybSAtcmYgL3Zhci9saWIvYXB0L2xpc3RzLyogIyBidWlsZGtpdCIsImNvbW1lbnQiOiJidWls"
        "ZGtpdC5kb2NrZXJmaWxlLnYwIn0seyJjcmVhdGVkIjoiMjAyNi0xMS0wNVQxNzowNjoxNC4zNzAzMDkyMiswODow"
        "MCIsImNyZWF0ZWRfYnkiOiJSVU4gL2Jpbi9zaCAtYyBjdXJsIC1MU2ZzIFwiaHR0cHM6Ly9naXRodWIuY29tL2Zh"
        "Y2Vib29rL2RvdHNsYXNoL3JlbGVhc2VzL2Rvd25sb2FkL3YwLjUuOC9kb3RzbGFzaC11YnVudHUtMjIuMDQuJCh1"
        "bmFtZSAtbSkudGFyLmd6XCIgfCB0YXIgZnh6IC0gLUMgL3Vzci9sb2NhbC9iaW4gIyBidWlsZGtpdCIsImNvbW1l"
        "bnQiOiJidWlsZGtpdC5kb2NrZXJmaWxlLnYwIn0seyJjcmVhdGVkIjoiMjAyNi0xMS0wNVQxNzowNjoxNC4zODg5"
        "MjE0OTErMDg6MDAiLCJjcmVhdGVkX2J5IjoiVVNFUiB1YnVudHUiLCJjb21tZW50IjoiYnVpbGRraXQuZG9ja2Vy"
        "ZmlsZS52MCIsImVtcHR5X2xheWVyIjp0cnVlfSx7ImNyZWF0ZWQiOiIyMDI2LTExLTA1VDE3OjA2OjE0LjM4ODky"
        "MTQ5MSswODowMCIsImNyZWF0ZWRfYnkiOiJXT1JLRElSIC93b3Jrc3BhY2UiLCJjb21tZW50IjoiYnVpbGRraXQu"
        "ZG9ja2VyZmlsZS52MCJ9XSwib3MiOiJsaW51eCIsInJvb3RmcyI6eyJ0eXBlIjoibGF5ZXJzIiwiZGlmZl9pZHMi"
        "Olsic2hhMjU2OmJlYzg3Nzc3YmMyZmIyZWRjZGY5YWYxMWRmMTUzMTQ2OWU3ZGY5MTEzMDljMTQxMzA4MmIxOGZj"
        "Yjg2MTAyNzgiLCJzaGEyNTY6N2FlMDYzNDdkMTI4ODVmZDRiYmQ4NzIyZmM4MjJkZjhmNzQ0ZjNmYzdmM2U5MzAy"
        "MjlkYzY4ZDgzOWVlMDI0MyIsInNoYTI1NjowMzdlNDJhNDQzNmY2YTE3NjA0OTA3ODIyYjVmYTJmZGQ3OWM5MTli"
        "ZTM0ZGY2NDU1MTRmMjk4MTlmNWYxNWI5Iiwic2hhMjU2OjU1ZDQ1ZjcxOTJkOWJjZmJiM2MxMmVjZDk1NzFjMzVm"
        "OTcyOGY3OTUyOTM0OTk2NWFmYTQ4YzkyYmU0OTcyY2YiXX19"
    ),
}


class LocalImageIdentityTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.evidence = self.directory / "evidence"
        self.evidence.mkdir()
        self.members = {
            name: base64.b64decode(data) for name, data in REAL_MEMBERS.items()
        }
        self.source = {
            "repository": publisher.REPOSITORY,
            "source_sha": "4b4b70b3c0004196b73519ec1b28fd66eefbc748",
            "architecture": "amd64",
            "base_image": "ubuntu@sha256:78d4744ead1f5b19b04d0df558ab182a5300903900755e515b2ca4d10eb2044d",
            "dockerfile_sha256": "92ca927e4a73f99dca91722ffc522542681a89b0292c655ff0ce2cf9e741aa48",
            "image_tag": "mutable-tag-must-never-be-saved:latest",
        }
        config = json.loads(
            self.members["blobs/sha256/" + REAL_CONFIG_ID.split(":")[1]]
        )
        self.inspected = {
            "Id": REAL_IMAGE_ID,
            "Os": "linux",
            "Architecture": "amd64",
            "Config": config["config"],
            "RootFS": {"Layers": config["rootfs"]["diff_ids"]},
        }
        self.write_evidence_inputs()

    def write_evidence_inputs(self):
        (self.evidence / "source.json").write_text(json.dumps(self.source))
        (self.evidence / "image-inspect.json").write_text(json.dumps([self.inspected]))
        (self.evidence / "verified-image-id.txt").write_text(
            self.inspected["Id"] + "\n"
        )

    def archive(self, members=None, extra=None, path=None):
        path = path or self.directory / "fixture.tar"
        with tarfile.open(path, mode="w") as archive:
            for name, data in (self.members if members is None else members).items():
                item = tarfile.TarInfo(name)
                item.size = len(data)
                archive.addfile(item, io.BytesIO(data))
            if extra is not None:
                item, data = extra
                archive.addfile(item, io.BytesIO(data) if data is not None else None)
        return path

    def save_proof(self, members=None):
        proof = identity.identity_from_archive(
            self.archive(members), self.source, self.inspected
        )
        (self.evidence / "local-image-identity.json").write_text(json.dumps(proof))
        return proof

    def replace_root(self, root, members):
        old_path = "blobs/sha256/" + self.inspected["Id"].split(":")[1]
        members.pop(old_path)
        data = json.dumps(root).encode()
        image_id = identity.digest(data)
        members["blobs/sha256/" + image_id.split(":")[1]] = data
        outer = json.loads(members["index.json"])
        outer["manifests"][0].update(digest=image_id, size=len(data))
        members["index.json"] = json.dumps(outer).encode()
        self.inspected["Id"] = image_id
        self.write_evidence_inputs()

    def test_real_docker29_index_resolves_original_config_and_strict_readback(self):
        self.assertNotEqual(REAL_IMAGE_ID, REAL_CONFIG_ID)
        self.save_proof()
        resolved = identity.verified_local_identity(self.evidence)
        self.assertEqual(resolved["identity_kind"], "oci-index-id")
        self.assertEqual(resolved["image_id"], REAL_IMAGE_ID)
        self.assertEqual(resolved["config_digest"], REAL_CONFIG_ID)
        self.assertEqual(resolved["image_manifest_digest"], REAL_MANIFEST_ID)
        members = self.members

        class RealRegistry:
            def manifest(self, reference, **_kwargs):
                digest = REAL_IMAGE_ID if reference == "source-tag" else reference
                return digest, json.loads(
                    members["blobs/sha256/" + digest.split(":")[1]]
                )

        # The prior Id-as-config comparison rejects these real unchanged bytes.
        with self.assertRaisesRegex(publisher.PublicationError, "configuration"):
            publisher.published_manifest(
                RealRegistry(), "source-tag", "amd64", REAL_IMAGE_ID
            )
        result = publisher.published_manifest(
            RealRegistry(),
            "source-tag",
            "amd64",
            resolved["config_digest"],
            resolved["image_manifest_digest"],
        )
        self.assertEqual(result["config_digest"], REAL_CONFIG_ID)
        self.assertEqual(result["image_digest"], REAL_MANIFEST_ID)

    def test_real_oci_root_manifest_and_config_byte_changes_are_rejected(self):
        for reference in (REAL_IMAGE_ID, REAL_MANIFEST_ID, REAL_CONFIG_ID):
            with self.subTest(reference=reference):
                changed = dict(self.members)
                path = "blobs/sha256/" + reference.split(":")[1]
                changed[path] += b" "
                with self.assertRaises(identity.IdentityError):
                    self.save_proof(changed)

    def test_native_manifest_id_also_resolves_original_config(self):
        changed = dict(self.members)
        changed.pop("blobs/sha256/" + REAL_IMAGE_ID.split(":")[1])
        outer = json.loads(changed["index.json"])
        outer["manifests"][0].update(
            mediaType="application/vnd.oci.image.manifest.v1+json",
            digest=REAL_MANIFEST_ID,
            size=len(changed["blobs/sha256/" + REAL_MANIFEST_ID.split(":")[1]]),
        )
        changed["index.json"] = json.dumps(outer).encode()
        self.inspected["Id"] = REAL_MANIFEST_ID
        self.write_evidence_inputs()
        self.save_proof(changed)
        resolved = identity.verified_local_identity(self.evidence)
        self.assertEqual(resolved["identity_kind"], "oci-manifest-id")
        self.assertEqual(resolved["config_digest"], REAL_CONFIG_ID)

    def test_wrong_or_duplicate_native_platform_is_rejected(self):
        original = copy.deepcopy(self.members)
        for invalid in ("wrong-architecture", "duplicate"):
            with self.subTest(invalid=invalid):
                self.inspected["Id"] = REAL_IMAGE_ID
                changed = copy.deepcopy(original)
                root = json.loads(
                    changed["blobs/sha256/" + REAL_IMAGE_ID.split(":")[1]]
                )
                if invalid == "wrong-architecture":
                    root["manifests"][0]["platform"]["architecture"] = "arm64"
                else:
                    root["manifests"].append(copy.deepcopy(root["manifests"][0]))
                self.replace_root(root, changed)
                with self.assertRaises(identity.IdentityError):
                    self.save_proof(changed)

    def test_source_labels_platform_and_smoked_id_remain_bound(self):
        self.save_proof()
        original_source = copy.deepcopy(self.source)
        for field, value in (
            ("source_sha", "f" * 40),
            ("architecture", "arm64"),
            ("base_image", "ubuntu@sha256:" + "f" * 64),
            ("dockerfile_sha256", "f" * 64),
            ("repository", "someone/other-repository"),
        ):
            with self.subTest(field=field):
                self.source = dict(original_source, **{field: value})
                self.write_evidence_inputs()
                with self.assertRaises(identity.IdentityError):
                    identity.verified_local_identity(self.evidence)
        self.source = original_source
        self.write_evidence_inputs()
        (self.evidence / "verified-image-id.txt").write_text("sha256:" + "f" * 64)
        with self.assertRaises(identity.IdentityError):
            identity.verified_local_identity(self.evidence)

    def test_archive_traversal_links_duplicates_and_oversized_metadata_are_rejected(
        self,
    ):
        cases = []
        for name in ("../outside.json", "/absolute.json", "blobs/../outside"):
            item = tarfile.TarInfo(name)
            item.size = 2
            cases.append((item, b"{}"))
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
            item = tarfile.TarInfo("linked-metadata")
            item.type = kind
            item.linkname = "../outside.json"
            cases.append((item, None))
        duplicate = tarfile.TarInfo("index.json")
        duplicate.size = 2
        cases.append((duplicate, b"{}"))
        for item, data in cases:
            with self.subTest(name=item.name, kind=item.type):
                with (
                    patch.object(
                        tarfile.TarFile,
                        "extract",
                        side_effect=AssertionError("must not extract"),
                    ),
                    patch.object(
                        tarfile.TarFile,
                        "extractall",
                        side_effect=AssertionError("must not extract"),
                    ),
                ):
                    with self.assertRaises(identity.IdentityError):
                        identity.identity_from_archive(
                            self.archive(extra=(item, data)),
                            self.source,
                            self.inspected,
                        )
        oversized = dict(self.members)
        oversized["blobs/sha256/" + REAL_CONFIG_ID.split(":")[1]] = b" " * (
            identity.MAX_JSON + 1
        )
        with self.assertRaises(identity.IdentityError):
            self.save_proof(oversized)
        self.assertFalse((self.directory / "outside.json").exists())

    def test_capture_saves_only_smoked_immutable_id_and_cleans_temporary_archive(self):
        calls = []

        def save(args, **kwargs):
            calls.append((args, kwargs))
            self.assertEqual(args[:4], ["docker", "image", "save", "--output"])
            self.assertEqual(args[-1], REAL_IMAGE_ID)
            self.assertNotIn(self.source["image_tag"], args)
            self.assertNotIn("GHCR_PUBLISH_TOKEN", kwargs["env"])
            self.archive(path=Path(args[4]))
            return subprocess.CompletedProcess(args, 0, b"", b"")

        with patch.dict("os.environ", {"GHCR_PUBLISH_TOKEN": "must-not-reach-save"}):
            identity.capture_local_identity(self.evidence, run=save)
        self.assertEqual(len(calls), 1)
        self.assertFalse(Path(calls[0][0][4]).exists())
        self.assertEqual(
            identity.verified_local_identity(self.evidence)["config_digest"],
            REAL_CONFIG_ID,
        )

    def test_retained_config_or_claimed_digest_changes_never_verify(self):
        original = self.save_proof()
        for mutation in ("config-bytes", "claimed-digest", "extra-member"):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(original)
                if mutation == "config-bytes":
                    key = "blobs/sha256/" + REAL_CONFIG_ID.split(":")[1]
                    changed["members"][key] = base64.b64encode(
                        self.members[key] + b" "
                    ).decode()
                elif mutation == "claimed-digest":
                    changed["config_digest"] = "sha256:" + "f" * 64
                else:
                    changed["members"]["unrelated.json"] = base64.b64encode(
                        b"{}"
                    ).decode()
                (self.evidence / "local-image-identity.json").write_text(
                    json.dumps(changed)
                )
                with self.assertRaises(identity.IdentityError):
                    identity.verified_local_identity(self.evidence)

    def test_same_remote_config_under_changed_manifest_is_rejected(self):
        with self.assertRaisesRegex(
            publisher.PublicationError, "native manifest differs"
        ):
            publisher.published_manifest(
                Registry(REAL_CONFIG_ID, index=True),
                "sha-source",
                "amd64",
                REAL_CONFIG_ID,
                REAL_MANIFEST_ID,
            )


if __name__ == "__main__":
    unittest.main()
