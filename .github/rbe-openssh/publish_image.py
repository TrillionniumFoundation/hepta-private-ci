#!/usr/bin/python3
"""Publish the verified OCI bytes, then separately test anonymous digest consumption."""

import base64
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from common import (
    BASES,
    DIGEST,
    Evidence,
    REGISTRY_REPOSITORY,
    descriptor_path,
    image_checks,
    json_write,
    require,
    sha_file,
    unpack_oci,
    verify_diff_ids,
)

MANIFEST_TYPE = "application/vnd.oci.image.manifest.v1+json"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Registry:
    def __init__(self, evidence):
        self.evidence, self.log = evidence, []
        evidence.state["registry_requests"] = self.log
        self.prefix = "/v2/" + REGISTRY_REPOSITORY + "/"
        actor, token = os.environ["GITHUB_ACTOR"], os.environ["GITHUB_TOKEN"]
        require(re.fullmatch(r"[A-Za-z0-9-]+", actor), "unexpected publishing actor")
        require(
            token and "\n" not in token and "\r" not in token, "missing ephemeral token"
        )
        encoded = base64.b64encode((actor + ":" + token).encode()).decode("ascii")
        query = urllib.parse.urlencode(
            {
                "service": "ghcr.io",
                "scope": "repository:" + REGISTRY_REPOSITORY + ":pull,push",
            }
        )
        status, headers, raw = self.exchange(
            "GET",
            "https://ghcr.io/token?" + query,
            {"Authorization": "Basic " + encoded},
            secret_response=True,
        )
        require(status == 200, "GHCR token authority was not established")
        response = json.loads(raw)
        self.token = response.get("token") or response.get("access_token")
        require(
            isinstance(self.token, str) and self.token,
            "GHCR token response missing token",
        )
        # No token, authorization header, or private Docker config is written to evidence.

    def exchange(self, method, url, headers=None, *, body=None, secret_response=False):
        parsed = urllib.parse.urlsplit(url)
        require(
            parsed.scheme == "https"
            and parsed.netloc == "ghcr.io"
            and not parsed.fragment
            and not parsed.username,
            "registry request destination changed",
        )
        require(
            urllib.parse.unquote(parsed.path, errors="strict") == parsed.path
            and "//" not in parsed.path
            and not any(part in (".", "..") for part in parsed.path.split("/")),
            "registry path is not a canonical literal path",
        )
        require(
            parsed.path == "/token" or parsed.path.startswith(self.prefix),
            "registry path escaped the fixed repository",
        )
        request_headers = dict(headers or {})
        request_headers["Accept-Encoding"] = "identity"
        entry = {
            "method": method,
            "path": parsed.path,
            "status": "requested",
            "secret_response": secret_response,
        }
        self.log.append(entry)
        channel = queue.Queue(maxsize=1)

        def run():
            opened = None
            try:
                data = body
                if isinstance(body, Path):
                    opened = body.open("rb")
                    data = opened
                    request_headers["Content-Length"] = str(body.stat().st_size)
                request = urllib.request.Request(
                    url, data=data, method=method, headers=request_headers
                )
                opener = urllib.request.build_opener(NoRedirect())
                try:
                    response = opener.open(request, timeout=self.evidence.remaining())
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    raw = response.read(8 * 1024 * 1024 + 1)
                    require(
                        len(raw) <= 8 * 1024 * 1024, "registry response exceeds bound"
                    )
                    require(
                        response.headers.get("Content-Encoding", "identity")
                        == "identity",
                        "registry response encoding changed",
                    )
                    channel.put(
                        (
                            response.status,
                            {
                                key.lower(): value
                                for key, value in response.headers.items()
                            },
                            raw,
                            None,
                        )
                    )
            except BaseException as error:
                channel.put((None, None, None, error))
            finally:
                if opened is not None:
                    opened.close()

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        try:
            worker.join(timeout=self.evidence.remaining())
        except BaseException:
            entry.update(status="deadline-unknown", response_complete=False)
            raise
        if worker.is_alive():
            entry.update(status="deadline-unknown", response_complete=False)
            raise TimeoutError(
                "registry request terminal response unknown; no retry or follow-up write"
            )
        status, response_headers, raw, error = channel.get_nowait()
        if error is not None:
            entry.update(
                status="transport-unknown",
                response_complete=False,
                exception_type=type(error).__name__,
            )
            raise error
        entry.update(status="completed", http_status=status, response_complete=True)
        if not secret_response:
            entry.update(
                response_bytes=len(raw), response_sha256=hashlib.sha256(raw).hexdigest()
            )
        # Do not retain token responses, Authorization, or signed redirect locations.
        return status, response_headers, raw

    def request(self, method, path, *, body=None, headers=None):
        require(path.startswith(self.prefix), "request path escaped repository")
        fields = {"Authorization": "Bearer " + self.token, **(headers or {})}
        return self.exchange(method, "https://ghcr.io" + path, fields, body=body)

    def manifest(self, reference):
        require(
            DIGEST.fullmatch(reference)
            or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", reference),
            "invalid manifest reference",
        )
        status, headers, raw = self.request(
            "GET",
            self.prefix + "manifests/" + reference,
            headers={"Accept": MANIFEST_TYPE},
        )
        if status == 404:
            errors = json.loads(raw).get("errors")
            require(
                isinstance(errors, list)
                and errors
                and all(
                    x.get("code") in ("MANIFEST_UNKNOWN", "NAME_UNKNOWN")
                    for x in errors
                ),
                "manifest absence is not established",
            )
            return None
        require(
            status == 200
            and headers.get("content-type", "").split(";", 1)[0] == MANIFEST_TYPE,
            "manifest read did not return the expected OCI object",
        )
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        require(
            headers.get("docker-content-digest") == digest,
            "registry manifest digest mismatch",
        )
        return raw

    def blob(self, descriptor, directory):
        digest = descriptor["digest"]
        path = descriptor_path(directory, descriptor)
        status, headers, _ = self.request("HEAD", self.prefix + "blobs/" + digest)
        if status == 200:
            require(
                headers.get("docker-content-digest") == digest
                and headers.get("content-length") == str(descriptor["size"]),
                "existing content-addressed blob identity differs",
            )
            return
        require(status == 404, "blob absence is not established")
        status, headers, _ = self.request(
            "POST", self.prefix + "blobs/uploads/", body=b""
        )
        require(status == 202, "registry did not accept a new blob upload")
        location = headers.get("location")
        require(isinstance(location, str), "upload location is missing")
        original_location = urllib.parse.urlsplit(location)
        require(
            urllib.parse.unquote(original_location.path, errors="strict")
            == original_location.path
            and "//" not in original_location.path
            and not any(
                part in (".", "..") for part in original_location.path.split("/")
            ),
            "original upload Location has a noncanonical path",
        )
        absolute = urllib.parse.urljoin("https://ghcr.io", location)
        parsed = urllib.parse.urlsplit(absolute)
        require(
            parsed.scheme == "https"
            and parsed.netloc == "ghcr.io"
            and parsed.path.startswith(self.prefix + "blobs/uploads/")
            and not parsed.fragment,
            "upload destination escaped the exact registry repository",
        )
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        require(
            all(key != "digest" for key, value in query),
            "unexpected pre-bound upload digest",
        )
        query.append(("digest", digest))
        destination = parsed.path + "?" + urllib.parse.urlencode(query)
        status, headers, _ = self.request(
            "PUT",
            destination,
            body=path,
            headers={"Content-Type": "application/octet-stream"},
        )
        require(
            status == 201 and headers.get("docker-content-digest") == digest,
            "blob publication did not confirm its expected digest",
        )


def publish(evidence, input_directory, qualification):
    arch, identity = evidence.arch, evidence.identity
    require(
        qualification["schema"] == "hepta.rbe-openssh.build.v1"
        and qualification["status"] == "image-only-qualified"
        and qualification["identity"] == identity
        and qualification["architecture"] == arch
        and qualification["base"] == BASES[arch],
        "build source/platform qualification mismatch",
    )
    receipt = json.loads((input_directory / "receipt.json").read_text())
    require(
        receipt["status"] == "image-only-qualified"
        and receipt["mode"] == "build"
        and receipt["qualification"] == qualification
        and receipt["identity"] == identity,
        "build did not reach its original terminal receipt",
    )
    require(
        qualification["deadline_unix_ns"] == receipt["deadline_unix_ns"]
        and time.time_ns() < qualification["deadline_unix_ns"],
        "original 1200-second deadline exhausted",
    )
    archive = input_directory / "image.oci.tar"
    require(
        archive.is_file()
        and not archive.is_symlink()
        and archive.stat().st_size == qualification["oci_archive"]["bytes"]
        and sha_file(archive) == qualification["oci_archive"]["sha256"],
        "OCI artifact identity mismatch",
    )
    descriptor, manifest, raw_manifest, config = unpack_oci(
        archive, evidence.root / "oci"
    )
    require(
        descriptor == qualification["platform_manifest"]
        and manifest["config"]["digest"] == qualification["image_config_digest"],
        "build manifest changed during handoff",
    )
    baseline_path = input_directory / "baseline-image.json"
    require(
        sha_file(baseline_path) == qualification["baseline_file_sha256"],
        "baseline evidence changed",
    )
    image_checks(identity, arch, config, json.loads(baseline_path.read_text()))
    verify_diff_ids(evidence.root / "oci", manifest, config)
    expected_digest = "sha256:" + hashlib.sha256(raw_manifest).hexdigest()
    require(
        descriptor["digest"] == expected_digest,
        "platform manifest bytes differ from descriptor",
    )
    tag = (
        "source-"
        + identity["commit"]
        + "-run-"
        + identity["run_id"]
        + "-attempt-"
        + identity["attempt"]
        + "-"
        + arch
    )
    reference = "ghcr.io/" + REGISTRY_REPOSITORY
    evidence.state.update(
        tag=reference + ":" + tag,
        expected_platform_digest=expected_digest,
        image_config_digest=manifest["config"]["digest"],
        registry_write_attempted=False,
        registry_publication_confirmed=False,
        anonymous_pull_confirmed=False,
        original_tests_qualified=False,
    )
    registry = Registry(evidence)
    evidence.state["registry_requests"] = registry.log
    previous = registry.manifest(tag)
    if previous is not None:
        require(
            previous == raw_manifest,
            "existing source/run/attempt tag has different bytes; refuse overwrite",
        )
        evidence.state["publication_mode"] = "reconciled-exact-existing-manifest"
    else:
        evidence.state["publication_mode"] = "new-source-run-attempt-tag"
        evidence.state["registry_write_attempted"] = True
        for blob in [manifest["config"], *manifest["layers"]]:
            registry.blob(blob, evidence.root / "oci")
        # GHCR offers no claimed compare-and-create guarantee. The guarded workflow
        # is serialized, checks again, and refuses any conflicting existing bytes.
        previous = registry.manifest(tag)
        require(
            previous is None or previous == raw_manifest,
            "tag changed before publication",
        )
        if previous is None:
            intent = {
                "reference": reference + ":" + tag,
                "platform_digest": expected_digest,
                "manifest_bytes": len(raw_manifest),
                "identity": identity,
            }
            json_write(evidence.root / "publication-intent.json", intent)
            status, headers, _ = registry.request(
                "PUT",
                registry.prefix + "manifests/" + tag,
                body=raw_manifest,
                headers={"Content-Type": MANIFEST_TYPE, "If-None-Match": "*"},
            )
            require(
                status == 201
                and headers.get("docker-content-digest") == expected_digest,
                "manifest publication terminal identity was not confirmed",
            )
    require(
        registry.manifest(tag) == raw_manifest
        and registry.manifest(expected_digest) == raw_manifest,
        "published manifest readback differs",
    )
    evidence.state.update(
        registry_publication_confirmed=True, actual_platform_digest=expected_digest
    )
    json_write(
        evidence.root / "published-manifest.json",
        {
            "reference": reference,
            "tag": tag,
            "platform_digest": expected_digest,
            "image_config_digest": manifest["config"]["digest"],
            "identity": identity,
            "anonymous_pull_confirmed": False,
            "original_tests_qualified": False,
        },
    )
    # This uses an empty Docker credential directory and no injected token. It is
    # separate from authenticated push and really retrieves all platform layers.
    with tempfile.TemporaryDirectory(
        prefix="hepta-rbe-anonymous-", dir=os.environ["RUNNER_TEMP"]
    ) as directory:
        evidence.command(
            [
                "docker",
                "pull",
                "--platform",
                "linux/" + arch,
                reference + "@" + expected_digest,
            ],
            environment={"DOCKER_CONFIG": directory},
            capture=False,
        )
        inspected = json.loads(
            evidence.command(
                ["docker", "image", "inspect", reference + "@" + expected_digest],
                environment={"DOCKER_CONFIG": directory},
            )
        )
    require(
        len(inspected) == 1
        and inspected[0]["Id"] == manifest["config"]["digest"]
        and inspected[0]["Architecture"] == arch
        and inspected[0]["Os"] == "linux",
        "anonymous pull did not yield the exact approved platform image",
    )
    evidence.remaining()
    evidence.state.update(
        status="published-and-anonymously-pulled-not-original-tests-qualified",
        anonymous_pull_confirmed=True,
    )
    json_write(
        evidence.root / "rbe-candidate.json",
        {
            "schema": "hepta.rbe-openssh.registry-candidate.v1",
            "identity": identity,
            "architecture": arch,
            "image": reference + "@" + expected_digest,
            "manifest_digest": expected_digest,
            "config_digest": manifest["config"]["digest"],
            "source_tag": tag,
            "anonymous_pull_confirmed": True,
            "rbe_bzl_modified": False,
            "original_gnu_musl_tests_run": False,
        },
    )


def main():
    directory = Path(os.environ["RBE_BUILD_INPUT"])
    require(
        directory.is_dir() and not directory.is_symlink(),
        "missing build artifact directory",
    )
    qualification_path = directory / "qualification.json"
    require(
        qualification_path.stat().st_size <= 1024 * 1024, "build receipt exceeds bound"
    )
    qualification = json.loads(qualification_path.read_text())
    receipt_path = directory / "receipt.json"
    require(
        receipt_path.stat().st_size <= 8 * 1024 * 1024,
        "build terminal receipt exceeds bound",
    )
    build_receipt = json.loads(receipt_path.read_text())
    spent = build_receipt["elapsed_seconds"]
    require(
        isinstance(spent, (int, float)) and math.isfinite(spent) and 0 <= spent <= 1200,
        "invalid original build time consumption",
    )
    deadline = qualification["deadline_unix_ns"]
    require(
        type(deadline) is int and (deadline - time.time_ns()) / 1_000_000_000 <= 1200,
        "build deadline exceeds original preparation cap",
    )
    # Recompute the absolute remainder inside the owner constructor. The actual
    # build consumption is an additional cap, never a fresh publication budget.
    evidence = Evidence("publish", sys.argv[1], 1200 - spent, deadline_unix_ns=deadline)
    try:
        publish(evidence, directory, qualification)
    except BaseException as error:
        evidence.finish(error)
        raise
    else:
        evidence.finish()


if __name__ == "__main__":
    main()
