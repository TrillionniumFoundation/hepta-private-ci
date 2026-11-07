FROM python:3.12-slim

# The packaging tests exercise the same zstd CLI used by runtime distributions.
# Build this prerequisite into the image; the tests themselves still run as the
# invoking non-root runner user.
RUN apt-get update \
    && apt-get install -y --no-install-recommends zstd \
    && rm -rf /var/lib/apt/lists/*
