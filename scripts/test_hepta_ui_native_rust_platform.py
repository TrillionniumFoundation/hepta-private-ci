"""Exercise the lexical Rust adapter guard without changing the source tree."""

from pathlib import Path
import unittest
from unittest.mock import patch

import check_hepta_ui_native_convergence as native


class NativeRustPlatformGuardTests(unittest.TestCase):
    def check_changed(self, relative, before, after, message):
        original_read = native._read
        source = original_read(relative)
        self.assertIn(before, source)

        def read(path):
            return (
                source.replace(before, after)
                if path == relative
                else original_read(path)
            )

        with patch.object(native, "_read", side_effect=read):
            with self.assertRaisesRegex(RuntimeError, message):
                native.check_native_platform_contracts()

    def test_current_rust_adapter_wiring_retains_positive_contracts(self):
        native.check_native_platform_contracts()

    def test_retired_interpreter_or_path_launcher_cannot_return(self):
        relative = "apps/hepta-native/src/platform.rs"
        for executable in (
            "/usr/bin/python3",
            "python",
            "powershell.exe",
            "/usr/bin/osascript",
            "notify-send",
        ):
            with self.subTest(executable=executable):
                self.check_changed(
                    relative,
                    "fn launch_portal_resource(",
                    f'fn unreviewed() {{ Command::new("{executable}"); }}\nfn launch_portal_resource(',
                    "retired interpreter/launcher reference",
                )

    def test_embedded_script_cannot_hide_inside_a_rust_source_file(self):
        for extension in ("py", "ps1", "js", "ts", "sh"):
            with self.subTest(extension=extension):
                self.check_changed(
                    "apps/hepta-native/src/platform_linux.rs",
                    "fn notification_error(",
                    f'const HIDDEN: &str = include_str!("adapter.{extension}");\nfn notification_error(',
                    "embedded executable script",
                )

    def test_resource_handoff_requires_the_retained_file_descriptor(self):
        self.check_changed(
            "apps/hepta-native/src/platform.rs",
            "Fd::from(file.as_fd())",
            '"/a/mutable/path"',
            "retained descriptor transport",
        )

    def test_portal_owner_path_queue_and_response_bounds_are_independent(self):
        for before, label in (
            (".sender(owner.as_str())", "pinned portal owner"),
            (".path(path.as_str())", "exact request path"),
            (
                "MessageStream::for_match_rule(rule, &connection, Some(4))",
                "bounded response queue",
            ),
            ("returned.as_str() != path", "request handle verification"),
            ("body.len() > MAX_RESPONSE_BYTES", "bounded response bytes"),
            ("CLOSE_TIMEOUT", "bounded request cleanup"),
        ):
            with self.subTest(label=label):
                self.check_changed(
                    "apps/hepta-native/src/native_portal.rs",
                    before,
                    "removed_contract",
                    label,
                )

    def test_helper_keeps_identity_request_bound_and_owned_lifetime(self):
        for before, label in (
            ("std::env::current_exe()?", "same executable"),
            ("digest_file(&executable)? != expected_digest", "launcher image identity"),
            ("ready.binary_digest != expected_digest", "child readiness identity"),
            ("self.nonce != nonce", "request identity"),
            ("MAX_REQUEST_BYTES + 1", "bounded request bytes"),
            ("#[serde(deny_unknown_fields)]", "closed request schema"),
            ("child.kill()", "child termination"),
            ("child.wait()", "child retirement"),
            (
                "crate::native_pipe::prepare_reader(&stdout)?",
                "nonblocking readiness reader",
            ),
            (
                "crate::native_pipe::prepare_writer(&stdin)?",
                "nonblocking request writer",
            ),
            ("writer.write(&request[written..])", "partial request writes"),
        ):
            with self.subTest(label=label):
                self.check_changed(
                    "apps/hepta-native/src/platform_notification_helper.rs",
                    before,
                    "removed_contract",
                    label,
                )

    def test_pipe_polling_contracts_cannot_be_removed(self):
        for relative, before, label in (
            (
                "apps/hepta-native/src/native_pipe.rs",
                "OFlags::NONBLOCK",
                "Unix nonblocking pipe mode",
            ),
            (
                "apps/hepta-native/platform-adapters/src/pipe.rs",
                "PIPE_NOWAIT",
                "Windows nonblocking pipe mode",
            ),
            (
                "apps/hepta-native/platform-adapters/src/pipe.rs",
                "if available == 0",
                "empty open pipe is not EOF",
            ),
            (
                "apps/hepta-native/platform-adapters/src/pipe.rs",
                "bytes.len().min(available as usize)",
                "bounded available-byte read",
            ),
        ):
            with self.subTest(label=label):
                self.check_changed(relative, before, "removed_contract", label)

    def test_native_notification_identity_and_literal_text_stay_explicit(self):
        for relative, before, label in (
            (
                "platform_notify_macos.rs",
                '"org.trillionnium.hepta.native"',
                "installed bundle identity",
            ),
            (
                "platform_notify_windows.rs",
                "notification_supported()",
                "registered identity gate",
            ),
            (
                "platform_notify_windows.rs",
                "CreateTextNode",
                "literal notification text",
            ),
        ):
            with self.subTest(source=relative, label=label):
                self.check_changed(
                    f"apps/hepta-native/src/{relative}",
                    before,
                    "removed_contract",
                    label,
                )

    def test_helper_cannot_accept_an_arbitrary_argument_prefix(self):
        self.check_changed(
            "apps/hepta-native/src/main.rs",
            'raw_args == ["--native-notification-helper"]',
            'raw_args.starts_with(&["--native-notification-helper".into()])',
            "exact no-argument entrypoint",
        )

    def test_required_module_must_be_present_in_its_own_source_path(self):
        path = native.ROOT / "apps/hepta-native/src/platform_notify_windows.rs"
        original = Path.is_file
        with patch.object(
            Path,
            "is_file",
            lambda candidate: False if candidate == path else original(candidate),
        ):
            with self.assertRaisesRegex(
                RuntimeError, "missing or unsafe Rust platform source"
            ):
                native.check_native_platform_contracts()


if __name__ == "__main__":
    unittest.main()
