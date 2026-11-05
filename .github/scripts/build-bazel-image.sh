#!/usr/bin/env bash
set -euo pipefail

: "${SOURCE_SHA:?SOURCE_SHA is required}"
: "${IMAGE_ARCH:?IMAGE_ARCH is required}"
: "${IMAGE_EVIDENCE_DIR:?IMAGE_EVIDENCE_DIR is required}"
[[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]]
[[ "$(git rev-parse HEAD)" == "$SOURCE_SHA" ]]
[[ -z "$(git status --porcelain --untracked-files=no)" ]]
case "$IMAGE_ARCH:$(uname -m)" in
  amd64:x86_64|arm64:aarch64) ;;
  *) echo 'Image must be built on its native architecture' >&2; exit 1 ;;
esac

mkdir -p "$IMAGE_EVIDENCE_DIR/context"
docker version --format '{{json .}}' > "$IMAGE_EVIDENCE_DIR/docker-version.json"
docker buildx version > "$IMAGE_EVIDENCE_DIR/buildx-version.txt"
docker buildx imagetools inspect ubuntu:24.04 --format '{{json .Manifest}}' > "$IMAGE_EVIDENCE_DIR/base-index.json"

# Resolve the mutable base tag before the build, then pass only its immutable
# architecture manifest to FROM. Preserve the original index as evidence.
base_digest="$(python3 - "$IMAGE_EVIDENCE_DIR/base-index.json" "$IMAGE_ARCH" <<'PY'
import json
import re
import sys

index = json.load(open(sys.argv[1], encoding="utf-8"))
matches = [
    item["digest"] for item in index["manifests"]
    if item.get("platform", {}).get("os") == "linux"
    and item.get("platform", {}).get("architecture") == sys.argv[2]
    and item.get("platform", {}).get("variant", "") in ("", "v8")
]
if len(matches) != 1 or not re.fullmatch(r"sha256:[0-9a-f]{64}", matches[0]):
    raise SystemExit("Expected exactly one immutable base manifest for the native architecture")
print(matches[0])
PY
)"
base_image="ubuntu@$base_digest"
image="ghcr.io/trillionniumfoundation/hepta-bazel:sha-${SOURCE_SHA}-${IMAGE_ARCH}"
dockerfile_sha256="$(sha256sum .github/workflows/Dockerfile.bazel | cut -d ' ' -f 1)"
cp .github/workflows/Dockerfile.bazel "$IMAGE_EVIDENCE_DIR/Dockerfile.bazel"
python3 - "$IMAGE_EVIDENCE_DIR/source.json" "$base_image" "$image" "$dockerfile_sha256" <<'PY'
import json
import os
from pathlib import Path
import subprocess
import sys

Path(sys.argv[1]).write_text(json.dumps({
    "repository": os.environ["GITHUB_REPOSITORY"],
    "source_sha": os.environ["SOURCE_SHA"],
    "source_tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip(),
    "architecture": os.environ["IMAGE_ARCH"],
    "base_image": sys.argv[2],
    "image_tag": sys.argv[3],
    "dockerfile_sha256": sys.argv[4],
    "workflow_sha": os.environ.get("GITHUB_WORKFLOW_SHA"),
    "run_id": os.environ["GITHUB_RUN_ID"],
    "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
}, indent=2) + "\n", encoding="utf-8")
PY

# The empty build context prevents private repository contents from entering
# the image. Dockerfile.bazel currently needs no COPY or ADD inputs.
docker buildx build \
  --platform "linux/$IMAGE_ARCH" \
  --build-arg "BASE_IMAGE=$base_image" \
  --no-cache --load \
  --file .github/workflows/Dockerfile.bazel \
  --tag "$image" \
  --label "org.opencontainers.image.source=https://github.com/$GITHUB_REPOSITORY" \
  --label "org.opencontainers.image.revision=$SOURCE_SHA" \
  --label "org.opencontainers.image.base.name=$base_image" \
  --label "org.opencontainers.image.base.digest=$base_digest" \
  --label "io.hepta.dockerfile.sha256=$dockerfile_sha256" \
  --metadata-file "$IMAGE_EVIDENCE_DIR/build-metadata.json" \
  --progress plain "$IMAGE_EVIDENCE_DIR/context"

docker image inspect "$image" > "$IMAGE_EVIDENCE_DIR/image-inspect.json"
python3 - "$IMAGE_EVIDENCE_DIR/image-inspect.json" "$IMAGE_ARCH" <<'PY'
import json
import sys

image = json.load(open(sys.argv[1], encoding="utf-8"))[0]
if (image["Os"], image["Architecture"], image["Config"]["User"]) != ("linux", sys.argv[2], "ubuntu"):
    raise SystemExit("Image OS, architecture or default user differs from the RBE contract")
if image["Config"].get("Entrypoint"):
    raise SystemExit("RBE image must not introduce an entrypoint")
PY
docker run --rm -i --network none --entrypoint /bin/sh "$image" -s \
  < .github/scripts/smoke-bazel-openssh.sh 2>&1 | tee "$IMAGE_EVIDENCE_DIR/openssh-smoke.log"
grep -Fxq \
  'PASS: default UID 1000; signature accepted; altered payload and wrong namespace rejected' \
  "$IMAGE_EVIDENCE_DIR/openssh-smoke.log"
docker run --rm --network none --entrypoint dpkg-query "$image" \
  -W -f '${Package}\t${Version}\t${Architecture}\n' > "$IMAGE_EVIDENCE_DIR/packages.tsv"
docker run --rm --network none --entrypoint sha256sum "$image" \
  /usr/bin/ssh-keygen /usr/local/bin/dotslash > "$IMAGE_EVIDENCE_DIR/executable-sha256.txt"
printf '%s\n' "$image" > "$IMAGE_EVIDENCE_DIR/verified-image-tag.txt"
