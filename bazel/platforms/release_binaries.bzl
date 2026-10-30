"""Rules for building release binaries across supported target platforms."""

load("@rules_platform//platform_data:defs.bzl", "platform_data")

PLATFORMS = [
    "linux_arm64_musl",
    "linux_amd64_musl",
    "macos_amd64",
    "macos_arm64",
    "windows_amd64",
    "windows_arm64",
]

# LLVM's convenience platforms do not carry Rust's Windows ABI or Linux libc
# marker. Keep the published roles on complete target platforms, including the
# existing static CRT feature for Windows; macOS and custom roles stay unchanged.
_RUST_RELEASE_PLATFORMS = {
    "linux_arm64_musl": "@rules_rs//rs/platforms:aarch64-unknown-linux-musl",
    "linux_amd64_musl": "@rules_rs//rs/platforms:x86_64-unknown-linux-musl",
    "windows_amd64": "//:windows_x86_64_msvc",
    "windows_arm64": "//:windows_aarch64_msvc",
}

def multiplatform_binaries(name, platforms = PLATFORMS, release_group_name = "release_binaries"):
    for platform in platforms:
        platform_data(
            name = name + "_" + platform,
            platform = _RUST_RELEASE_PLATFORMS.get(platform, "@llvm//platforms:" + platform),
            target = name,
            tags = ["manual"],
        )

    native.filegroup(
        name = release_group_name,
        srcs = [name + "_" + platform for platform in platforms],
        tags = ["manual"],
    )
