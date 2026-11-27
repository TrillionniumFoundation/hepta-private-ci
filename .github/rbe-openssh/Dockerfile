# Build each architecture natively from its original RBE image.
# TARGETARCH is BuildKit's platform argument; no arbitrary base-image override.
ARG TARGETARCH
FROM docker.io/mbolin491/codex-bazel@sha256:0a8e56bfaa3b2e5279db0d3bb2d62b44ba5e5d63a37d97eb8790f49da570af70 AS original-amd64
FROM docker.io/mbolin491/codex-bazel@sha256:136487cc4b7cf6f1021816ca18ed00896daed98404ea91dc4d6dd9e9d1cf9564 AS original-arm64
FROM original-${TARGETARCH}

USER root
WORKDIR /workspace
COPY --chmod=0444 image_prepare.py tool_supply.py /usr/local/lib/hepta-rbe-openssh/
RUN ["/usr/bin/python3", "-I", "-B", "/usr/local/lib/hepta-rbe-openssh/image_prepare.py", "install"]

USER ubuntu
RUN ["/usr/bin/python3", "-I", "-B", "/usr/local/lib/hepta-rbe-openssh/image_prepare.py", "qualify"]

USER root
RUN ["/usr/bin/install", "-o", "0", "-g", "0", "-m", "0444", "/tmp/hepta-rbe-openssh-tool-test.json", "/usr/local/share/hepta-rbe-openssh/tool-test.json"]
RUN ["/usr/bin/rm", "--", "/tmp/hepta-rbe-openssh-tool-test.json"]

USER ubuntu
WORKDIR /workspace
