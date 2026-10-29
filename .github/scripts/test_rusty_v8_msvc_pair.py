#!/usr/bin/env python3

import re
import unittest

import rusty_v8_bazel
import rusty_v8_module_bazel


class RustyV8MsvcPairTest(unittest.TestCase):
    def test_msvc_consumer_uses_matching_published_sandbox_bindings(self) -> None:
        version = rusty_v8_bazel.resolved_v8_crate_version()
        version_suffix = version.replace(".", "_")
        module = rusty_v8_bazel.MODULE_BAZEL.read_text()
        entries = {
            entry.name: entry
            for entry in rusty_v8_module_bazel.rusty_v8_http_files(module, version)
        }
        build = (rusty_v8_bazel.ROOT / "third_party/v8/BUILD.bazel").read_text()
        filegroups = {
            rusty_v8_module_bazel.string_field(block, "name"): block
            for block in re.findall(r"(?ms)^filegroup\(\n.*?^\)\n?", build)
        }
        for architecture in ("aarch64", "x86_64"):
            with self.subTest(architecture=architecture):
                target = f"{architecture}-pc-windows-msvc"
                binding_selector = (
                    f"src_binding_release_{architecture}_pc_windows_msvc_"
                    f"{version_suffix}_release"
                )
                binding_repositories = re.findall(
                    r'"@([^"/]+)//file"', filegroups[binding_selector]
                )
                self.assertEqual(len(binding_repositories), 1)
                binding = entries[binding_repositories[0]]
                archive = entries[
                    f"rusty_v8_{version_suffix}_{architecture}_pc_windows_msvc_archive"
                ]
                for entry, filename in (
                    (archive, f"rusty_v8_ptrcomp_sandbox_release_{target}.lib.gz"),
                    (binding, f"src_binding_ptrcomp_sandbox_release_{target}.rs"),
                ):
                    urls = re.findall(r'"(https://[^" ]+)"', entry.block)
                    self.assertEqual(
                        urls,
                        [
                            "https://github.com/openai/codex/releases/download/"
                            f"rusty-v8-v{version}/{filename}"
                        ],
                    )


if __name__ == "__main__":
    unittest.main()
