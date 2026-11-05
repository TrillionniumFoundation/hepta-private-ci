#!/usr/bin/env python3
"""Publish a verified image without overwriting a source tag or logging credentials."""

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
PACKAGE = "trillionniumfoundation/hepta-bazel"
IMAGE = f"ghcr.io/{PACKAGE}"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


class PublicationError(Exception):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Credentials are only ever sent to the literal ghcr.io host below.
        raise PublicationError("GHCR unexpectedly redirected an authenticated request")


class Ghcr:
    def __init__(self, username: str, token: str):
        self.opener = build_opener(NoRedirects())
        query = urlencode(
            {"service": "ghcr.io", "scope": f"repository:{PACKAGE}:pull,push"}
        )
        basic = base64.b64encode(f"{username}:{token}".encode()).decode()
        request = Request(
            f"https://ghcr.io/token?{query}",
            headers={"Authorization": f"Basic {basic}"},
        )
        try:
            with self.opener.open(request, timeout=60) as response:
                self.bearer = json.load(response)["token"]
        except (HTTPError, URLError, KeyError, ValueError):
            raise PublicationError(
                "Unable to authorize the repository-associated GHCR package"
            ) from None

    def manifest(self, reference: str, *, missing_ok: bool = False):
        request = Request(
            f"https://ghcr.io/v2/{PACKAGE}/manifests/{reference}",
            headers={
                "Authorization": f"Bearer {self.bearer}",
                "Accept": ACCEPT,
            },
        )
        try:
            with self.opener.open(request, timeout=60) as response:
                body = response.read()
                digest = response.headers.get("Docker-Content-Digest", "")
        except HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            raise PublicationError(
                f"GHCR manifest request failed with HTTP {error.code}"
            ) from None
        except URLError:
            raise PublicationError("GHCR manifest request failed") from None
        if (
            not DIGEST.fullmatch(digest)
            or digest != f"sha256:{hashlib.sha256(body).hexdigest()}"
        ):
            raise PublicationError(
                "GHCR manifest content does not match its declared digest"
            )
        try:
            return digest, json.loads(body)
        except ValueError:
            raise PublicationError("GHCR returned an invalid image manifest") from None


def published_manifest(registry, tag, architecture, expected_config):
    tag_digest, manifest = registry.manifest(tag)
    image_digest = tag_digest
    if "manifests" in manifest:
        matches = [
            entry
            for entry in manifest["manifests"]
            if entry.get("platform", {}).get("os") == "linux"
            and entry.get("platform", {}).get("architecture") == architecture
        ]
        if len(matches) != 1 or not DIGEST.fullmatch(matches[0].get("digest", "")):
            raise PublicationError(
                "Published index must contain exactly one expected platform"
            )
        image_digest, manifest = registry.manifest(matches[0]["digest"])
        if image_digest != matches[0]["digest"]:
            raise PublicationError("Published architecture manifest digest changed")
    if manifest.get("config", {}).get("digest") != expected_config:
        raise PublicationError(
            "Published image differs from the locally verified image configuration"
        )
    return {
        "tag_digest": tag_digest,
        "image_digest": image_digest,
        "config_digest": expected_config,
    }


def publish(evidence: Path, environment, *, run=subprocess.run, registry_factory=Ghcr):
    child_env = dict(environment)
    token = child_env.pop("GHCR_PUBLISH_TOKEN", "")
    username = child_env.get("GITHUB_ACTOR", "")
    if (
        child_env.get("GITHUB_REPOSITORY") != REPOSITORY
        or not token
        or not re.fullmatch(r"[A-Za-z0-9_\[\]-]+", username)
    ):
        raise PublicationError("Publishing requires this repository's Actions identity")

    source = json.loads((evidence / "source.json").read_text(encoding="utf-8"))
    sha = source["source_sha"]
    arch = source["architecture"]
    if (
        not re.fullmatch(r"[0-9a-f]{40}", sha)
        or arch not in ("amd64", "arm64")
        or source["repository"] != REPOSITORY
    ):
        raise PublicationError("Invalid image source identity")
    if sha != child_env.get("SOURCE_SHA") or arch != child_env.get("IMAGE_ARCH"):
        raise PublicationError(
            "Image source differs from the workflow's exact source and architecture"
        )
    tag = f"sha-{sha}-{arch}"
    image = f"{IMAGE}:{tag}"
    if (
        source["image_tag"] != image
        or (evidence / "verified-image-tag.txt").read_text().strip() != image
    ):
        raise PublicationError(
            "Image has not completed the expected local verification"
        )
    inspected = json.loads(
        (evidence / "image-inspect.json").read_text(encoding="utf-8")
    )[0]
    expected_config = inspected["Id"]
    if not DIGEST.fullmatch(expected_config):
        raise PublicationError("Invalid locally verified image configuration digest")

    registry = registry_factory(username, token)
    if registry.manifest(tag, missing_ok=True) is not None:
        raise PublicationError("Source tag already exists; refusing to overwrite it")

    # Keep the login credential out of argv, child environments, the repository,
    # image build inputs, build caches and uploaded evidence. Clean up on failure.
    with TemporaryDirectory(
        prefix="hepta-ghcr-", dir=child_env.get("RUNNER_TEMP")
    ) as auth_dir:
        os.chmod(auth_dir, 0o700)
        child_env["DOCKER_CONFIG"] = auth_dir
        try:
            login = run(
                [
                    "docker",
                    "login",
                    "ghcr.io",
                    "--username",
                    username,
                    "--password-stdin",
                ],
                input=token,
                text=True,
                capture_output=True,
                env=child_env,
                check=False,
            )
            if login.returncode:
                raise PublicationError("Docker GHCR login failed")
            pushed = run(
                ["docker", "push", image],
                text=True,
                capture_output=True,
                env=child_env,
                check=False,
            )
            if pushed.returncode:
                raise PublicationError(
                    "Docker image push failed; no verified digest was recorded"
                )
            # Refresh after the push so a slow transfer cannot expire the readback token.
            registry = registry_factory(username, token)
            result = published_manifest(registry, tag, arch, expected_config)
        finally:
            run(
                ["docker", "logout", "ghcr.io"],
                text=True,
                capture_output=True,
                env=child_env,
                check=False,
            )

    result.update(
        {
            "image_tag": image,
            "source_sha": sha,
            "architecture": arch,
            "image_by_digest": f"{IMAGE}@{result['image_digest']}",
            "anonymous_pull_verified": False,
        }
    )
    (evidence / "published-image.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Published and authenticated-readback verified: {result['image_by_digest']}")
    print(
        "Visibility, anonymous pull and the original RBE test suites remain separate checks."
    )


def main():
    # Remove the credential from the process environment as early as possible.
    environment = dict(os.environ)
    os.environ.pop("GHCR_PUBLISH_TOKEN", None)
    try:
        if len(sys.argv) != 2:
            raise PublicationError("Expected the image evidence directory")
        publish(Path(sys.argv[1]), environment)
    except PublicationError as error:
        print(f"Image publication failed: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError):
        # Do not dump subprocess state, environment or HTTP objects on errors.
        print(
            "Image publication failed while reading or recording evidence",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
