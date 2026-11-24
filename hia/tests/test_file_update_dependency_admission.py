#!/usr/bin/env python3
"""Admission regressions with local fixtures; no Git, Cargo, Wine, sockets or processes."""
from pathlib import Path
import tempfile
import unittest

from file_update_oracle import cargo, identity

# Complete immutable 094/e5 exec-server leaf vector, not a filesystem scan.
# Canonical tree: 040d2b09f7f1ed6dcf930c0c6032868e32b52764 (143 leaves).
PINNED_LISTING = (
    b"100644 blob edd3380811608c669440f20c0083b01fe60874a7\tBUILD.bazel\0"
    b"100644 blob 746bfb231d61c1a67163ff55c46cd7e92964457a\tCargo.toml\0"
    b"100644 blob c5fd2c2d598951919268cb0c604e8f9355d15394\tREADME.md\0"
    b"100644 blob 3fc9e81e4c9fca280e83a99fe1e72386579d8e39\tsrc/arg0_exec_helper.rs\0"
    b"100644 blob 33bbcb8c1f76f029c3d0619aa0517a5724a448ad\tsrc/capability_discovery_cache.rs\0"
    b"100644 blob 43721630e2e8e7776ed1456db9f7b752164690ca\tsrc/capability_discovery.rs\0"
    b"100644 blob d07364c9ad06010bef00666ea4efdf12962ccd0b\tsrc/client_api.rs\0"
    b"100644 blob 4abc939d323955ae708971fb9bb21bc8a2248c05\tsrc/client_recovery_tests.rs\0"
    b"100644 blob 0c0999cb18349afed7a86fab689404030f4118ae\tsrc/client_recovery.rs\0"
    b"100644 blob 411dfc0e8db9193f2d2e7cf5402bdf247b24e0ab\tsrc/client_transport_tests.rs\0"
    b"100644 blob add01f69d4179234a39d72662f4ebe68d6bdad87\tsrc/client_transport.rs\0"
    b"100644 blob 329cd5a34cb35652fc6314507e80bcfe42c9649c\tsrc/client.rs\0"
    b"100644 blob f284f1cf39a7ea8d14f10fd59c3e40cc27daed4e\tsrc/client/accepted_tests.rs\0"
    b"100644 blob 535eecb694ad4fa2977edd672923445e2eb769d6\tsrc/client/accepted.rs\0"
    b"100644 blob cbafd448a0a50f984978f1b37f9694f54c682ad9\tsrc/client/http_client.rs\0"
    b"100644 blob 625c640812797e3e6a76e2eb978ab037a127aabc\tsrc/client/http_response_body_stream.rs\0"
    b"100644 blob b16249a9b9b3622408cca1373ae2961c11c27a24\tsrc/client/network_policy_audit.rs\0"
    b"100644 blob 81dd4607ddc5a5a5774aba79fc911a0ab2959afc\tsrc/client/route_aware_http_client.rs\0"
    b"100644 blob c48ff8d29f864b0e159a0481e9fd8724aed5a0f6\tsrc/client/rpc_http_client.rs\0"
    b"100644 blob 468c3dfc7a5a0689c1357f5bab736855d5b4958a\tsrc/client/tests/network_policy_tests.rs\0"
    b"100644 blob 249b63330e59cd8bb553892976809d48866936c6\tsrc/connection.rs\0"
    b"100644 blob d877871b227e5a4a9df313f2107bc5bdc4053a88\tsrc/environment_bootstrap_tests.rs\0"
    b"100644 blob ad557c3b292d32702444da91f1d67535bf810a0c\tsrc/environment_bootstrap.rs\0"
    b"100644 blob b53208b63a87d10210a0be1b12c2a756270c0e81\tsrc/environment_config.rs\0"
    b"100644 blob 2366eb8be24b2d472dbc6245bc876fcc02704e6b\tsrc/environment_provider.rs\0"
    b"100644 blob 8c32e0fb45af19d862509bb8625001f1ee9840aa\tsrc/environment_registry_tests.rs\0"
    b"100644 blob bc0755fd68b4d5634d3728fff7d5201150b29a9e\tsrc/environment_registry.rs\0"
    b"100644 blob e754bce01a8630de69c1629bf84ca9ebdaf023d0\tsrc/environment_toml.rs\0"
    b"100644 blob 251de95d7d9b3abd7795f85e5cb1e4b2a530bbda\tsrc/environment.rs\0"
    b"100644 blob 600512b0803d060e4bca4cc636841541407f0fa6\tsrc/environment/accepted.rs\0"
    b"100644 blob 8cc84b67300df2913d25af4458c4ac39c0231bfd\tsrc/file_read.rs\0"
    b"100644 blob a6740ca882b84c6bac2a47b1ee8ef8fc647a6229\tsrc/forward_tests.rs\0"
    b"100644 blob 09ccc5d586fbe05e582dbbed24d39907671cb579\tsrc/forward.rs\0"
    b"100644 blob 3ca9ecc21e3d9e525a807680f91d8ebe04059a6d\tsrc/fs_helper_main.rs\0"
    b"100644 blob ad6eacf93cfda03b223c197f7c79c2dac1ec0fe4\tsrc/fs_helper.rs\0"
    b"100644 blob ca715ef44ed7c30e4da11149dcc2cf8248c67ab3\tsrc/fs_sandbox.rs\0"
    b"100644 blob 8a2616a2001bcbb06b2b9bd1420c274c1c73cb81\tsrc/lib.rs\0"
    b"100644 blob 8d16d6e8ab4bb17d63ed850d92af8f86c4e5c588\tsrc/local_file_system_authorized_read_tests.rs\0"
    b"100644 blob 34ceeeb6a61b06d45ba5f30054d9b5998d1d5088\tsrc/local_file_system_linux.rs\0"
    b"100644 blob 78a48c5302e65b5598ba5f9a27953367028cfff1\tsrc/local_file_system_path_uri_tests.rs\0"
    b"100644 blob 0a1be1295388173a8aebc3e81980e3edecb9f12a\tsrc/local_file_system.rs\0"
    b"100644 blob 927276f36e75669c7b44384075d8c0d1e98a634e\tsrc/local_process.rs\0"
    b"100644 blob ace0c3e1f3b09b747ccc4625645e29c8f8fb9a45\tsrc/network_policy_decisions_tests.rs\0"
    b"100644 blob 129ae30c33468fc70c8005d68a86f2db7a0d830d\tsrc/network_policy_decisions.rs\0"
    b"100644 blob 54461e887c9d7e105a2edb20e2bae4a255a5c93d\tsrc/no_follow/mod.rs\0"
    b"100644 blob 23a7fcc83a1e2e3daf1586b7d11f690c1d7faab6\tsrc/no_follow/unix.rs\0"
    b"100644 blob d9e3b0bbeb1abce587f5ebdbc4bc0cd484bb9d86\tsrc/no_follow/windows_tests.rs\0"
    b"100644 blob 14a3db30a9feb76cb0fe22ea7e07951d999957c9\tsrc/no_follow/windows.rs\0"
    b"100644 blob b298e8e580c74d057a8677581b1b169fc16ac8bc\tsrc/noise_channel_tests.rs\0"
    b"100644 blob cde2aae4eeb1ccedf3d3617bd1e7fa2ba2e21796\tsrc/noise_channel.rs\0"
    b"100644 blob 986fd650fe68b7b30ec494d0f6bf66e511540040\tsrc/noise_relay/executor_stream_tests.rs\0"
    b"100644 blob 32c7c0c1d713e0c66c2df73e7913b628b389ac16\tsrc/noise_relay/executor_stream.rs\0"
    b"100644 blob 25deb383ed86cd0839386dedd9f20beebb300992\tsrc/noise_relay/forward_stream_tests.rs\0"
    b"100644 blob 16df1cbf0fd44679870093a4d89a1b8d832058cd\tsrc/noise_relay/harness_tests.rs\0"
    b"100644 blob 472d9c8184433f7149460c56a90f0629e69ce1e0\tsrc/noise_relay/harness.rs\0"
    b"100644 blob 563e9e3bade2a86d193c9b5e71991e653c51db2a\tsrc/noise_relay/message_framing_tests.rs\0"
    b"100644 blob af9fbd49986f0e23da32acf44ecee4ac377f536c\tsrc/noise_relay/message_framing.rs\0"
    b"100644 blob 12bbdd6f135e0d4da90ef9cd1be30bda9f74d214\tsrc/noise_relay/mod.rs\0"
    b"100644 blob 6aa86fcdf0559f68d6e05b55d0f6db60094b2f09\tsrc/noise_relay/ordered_ciphertext_tests.rs\0"
    b"100644 blob 92bbd291d72f8130881a9364e43323a5566571ad\tsrc/noise_relay/ordered_ciphertext.rs\0"
    b"100644 blob 0015176684495f656c72b9b72cb746157c9215a3\tsrc/noise_relay/stream_handler_tests.rs\0"
    b"100644 blob a85d5ca7f773c115731feceaf3d2c453637626da\tsrc/noise_relay/stream_handler.rs\0"
    b"100644 blob a66387ee0d892b82ba3fcf45662a13ef6b13c4c3\tsrc/process_sandbox_tests.rs\0"
    b"100644 blob 0bf5853a1d82df037d406fdffbe31d6bada1b2b4\tsrc/process_sandbox.rs\0"
    b"100644 blob bf3cc752f07a5d41097c5bf9ce727da5310746b1\tsrc/process.rs\0"
    b"100644 blob a9d2100137230b80e014f7e99cb0d8a8093d2473\tsrc/proto/codex.exec_server.relay.v1.proto\0"
    b"100644 blob 4694ed4024da99232dbae8d626fd551e9b6ba25f\tsrc/proto/codex.exec_server.relay.v1.rs\0"
    b"100644 blob 4cda98114c246e2ecc1d4d6a964a0752f9e72b14\tsrc/regular_file_tests.rs\0"
    b"100644 blob c4126b0abe53ce7ed55ecd30722ce06282e19e8b\tsrc/regular_file.rs\0"
    b"100644 blob 99eda6de8a511e63bcb66851ce9febd472cff44b\tsrc/relay_noise_tests.rs\0"
    b"100644 blob da7cb5296d46bb7c76a5baeb452909608fbb4c14\tsrc/relay_proto.rs\0"
    b"100644 blob f53a09a3e28dc0609192f9eef8593fa63202b08b\tsrc/relay.rs\0"
    b"100644 blob 107dea51d7d551c67ccfaa680426b3ee805725b2\tsrc/remote_file_stream.rs\0"
    b"100644 blob 31a558947344e36b9eb3cabcc024639c169f0d47\tsrc/remote_file_system_path_uri_tests.rs\0"
    b"100644 blob ed942b3f6a784b3cac0adc5d6cf48202f67cd60c\tsrc/remote_file_system.rs\0"
    b"100644 blob 4c2d4c8e63514a3f8157f1b0275662f5407fcd68\tsrc/remote_process.rs\0"
    b"100644 blob 8836e4065a0e228eb39f3c7d361aba3be07cd18d\tsrc/remote.rs\0"
    b"100644 blob c59328227a5e1f87dc3027cb4bb42698a34eab48\tsrc/remote/noise_tests.rs\0"
    b"100644 blob 078b2b982b215331e2f1c781bd87ffb4f28f91ee\tsrc/resolved_capability.rs\0"
    b"100644 blob 05692c32aaaecb87ba6505de570ce13a83a5843a\tsrc/rpc_server_requests_tests.rs\0"
    b"100644 blob b7d158802b8ecaa49a9055e29848b99e4d194e62\tsrc/rpc_server_requests.rs\0"
    b"100644 blob 83d43783445ad65fe50f398573f2df3ab8df1793\tsrc/rpc.rs\0"
    b"100644 blob 1d3713b1c1e49e6d2ccd6a106826b05d0535630f\tsrc/runtime_paths.rs\0"
    b"100644 blob 93c78706a472d882908e124117cc0a9e94057ca3\tsrc/sandboxed_file_open.rs\0"
    b"100644 blob 031d89080f21a369010161dec5a5971bdb26aa27\tsrc/sandboxed_file_system_path_uri_tests.rs\0"
    b"100644 blob 61c3c061267bb79b8fc2eef490501190dece8d0a\tsrc/sandboxed_file_system.rs\0"
    b"100644 blob c04e1fa166faed43e55a608b98f74cec915efd6d\tsrc/server.rs\0"
    b"100644 blob 28d84babcf665651e7ebdb38530082704cd135fa\tsrc/server/file_system_handler.rs\0"
    b"100644 blob 4b54a2a1c8e2b3c89aa21a9de16dce34a65c4bc9\tsrc/server/handler.rs\0"
    b"100644 blob 1fb96850ed0f9954034de9e0cd0600664890ee8f\tsrc/server/handler/tests.rs\0"
    b"100644 blob 4d933afbe119912bd0747be8cbc3bad4e1434677\tsrc/server/process_handler.rs\0"
    b"100644 blob edc8d41c4645f5c57a89aba8adb17b07b8a5a5af\tsrc/server/processor.rs\0"
    b"100644 blob 9637f1beae7593092b70f4031a2a4c5ebb4a1b69\tsrc/server/registry.rs\0"
    b"100644 blob 3772e621ae7090383b31e1ca9206c5d629808fee\tsrc/server/request_dispatcher_tests.rs\0"
    b"100644 blob 5460921e685e7f3225907da0759f12aa635a03b7\tsrc/server/request_dispatcher.rs\0"
    b"100644 blob 89a861ab7be7a7f19708cb9ab376bcfdd18960fc\tsrc/server/session_registry.rs\0"
    b"100644 blob c26109a3b8cc373d86070314f842d27b0c116e1b\tsrc/server/transport_tests.rs\0"
    b"100644 blob 9d556b0dba63d77a70eaec7b0b0f0bf6eb1117a4\tsrc/server/transport.rs\0"
    b"100644 blob 1f24ef5de8b1ae9b648af676876d95d704833275\tsrc/shell_snapshot_tests.rs\0"
    b"100644 blob 0471d92ebf2a7521c877b189b9f0f7c4d47c9e88\tsrc/shell_snapshot.rs\0"
    b"100644 blob e78d2ec4550615236afee128b3ffd9ee7d486a94\tsrc/telemetry.rs\0"
    b"100644 blob 92a820afc43a4bdf2eb78104a6ab7cdec144ef44\tsrc/trace_context_tests.rs\0"
    b"100644 blob f6fd898c0575dcadd1d652c0f79eedf3f623267c\tsrc/trace_context.rs\0"
    b"100644 blob 2b15a0d95223a71e148e09721a12a7821ee8488f\tsrc/websocket_pong_watchdog_tests.rs\0"
    b"100644 blob b656772b3d276155353ed4e80b9eb72bb8286e50\tsrc/websocket_pong_watchdog.rs\0"
    b"100644 blob 93cb4ceab9127c9792e349e1138632da760f6d05\ttesting/BUILD.bazel\0"
    b"100644 blob 36c7685ceb0eb411b8ff2a98f7f97a6a0e30cdf8\ttesting/exec_server.rs\0"
    b"100644 blob 77f8e990d430bef30ce7c7c21cd34cd878910e77\ttesting/README.md\0"
    b"100755 blob 109a61cefa2fc268ecd9fa7f875d60132a1318ad\ttesting/run_version_skew_test.sh\0"
    b"100755 blob dd52dc63ebacaaed454848edbe9c2603a498af26\ttesting/run_version_skew.sh\0"
    b"100644 blob a3643f8668c99baec60a6d1f382021b1607a8d42\ttesting/wine_exec_server.rs\0"
    b"100644 blob 41cd6bfc1531c414b135936480ae6c37985de772\ttesting/wine_remote_test_runner.rs\0"
    b"100644 blob 9e7ee669ef8c7e187598addecc9328eba3e329c3\ttests/accepted_websocket.rs\0"
    b"100644 blob bd7ed59e9a58f0a940ad9ed45f93d4546f3d06be\ttests/authorized_read_rpc.rs\0"
    b"100644 blob a547c978ba9a12e453d7d529c4c936282c0b7367\ttests/capability_discovery.rs\0"
    b"100644 blob d754fa8c4b7fec9cc4b7413896cca3d57c11141a\ttests/chatgpt_cloudflare_affinity.rs\0"
    b"100644 blob ea4f5b166cac271930382ef158edd5ac7db66253\ttests/common/exec_server.rs\0"
    b"100644 blob ddd293648026b30b567f20df20b6d6527aa98384\ttests/common/fake_bwrap.rs\0"
    b"100644 blob e95aa5563976b289f026168d7499bfd89fd97662\ttests/common/mod.rs\0"
    b"100644 blob 977b70d1ba423ab02d60305ab62d858d1658f05d\ttests/common/relay.rs\0"
    b"100644 blob d08b9ab5e622ebbfe5215fe6660c2eff69ced12a\ttests/deferred_environment.rs\0"
    b"100644 blob 2dff179253ace11a8a3c2684b1d170db178f1fb4\ttests/environment_config.rs\0"
    b"100644 blob 814ae7f2d25257501411a75df596e71c4e89209d\ttests/environment.rs\0"
    b"100644 blob 0e7e757303c4f762020982769967d0e41d35f99d\ttests/exec_process.rs\0"
    b"100644 blob 9fd3201eebf17ddcfeb911a34c680b1bac3d21d5\ttests/file_stream.rs\0"
    b"100644 blob 2ebd7e53986eb4cceaabaad4b8bc1b3f55ba1d64\ttests/file_system_unix.rs\0"
    b"100644 blob 41916edbfc0cbfbfa6dc6d7ccf0b627f62821b86\ttests/file_system_windows.rs\0"
    b"100644 blob 96dfa143492f1ca2e6413711985343a764dea72a\ttests/file_system/shared.rs\0"
    b"100644 blob aa7122810a84276ab5e5d2c5c5b865593fa3bd0c\ttests/file_system/support.rs\0"
    b"100644 blob 02c272bdaef11e8106769444bdc75adb3af33cc7\ttests/forward.rs\0"
    b"100644 blob 05915fe9684033670d8461eb9e0c85003e9be4dd\ttests/health.rs\0"
    b"100644 blob ebe8471dee5c6abb55ada84858601baf2ce176fd\ttests/http_client.rs\0"
    b"100644 blob 45e26499575fe93e993d55e020f49a0e9141dca2\ttests/http_request_logging.rs\0"
    b"100644 blob 55144de11eca27bf9f4e6654162dba43c6c429b1\ttests/http_request.rs\0"
    b"100644 blob 9c38945ffec5a6c933ac9b44f4eb89bc289dda99\ttests/initialize.rs\0"
    b"100644 blob 60045e8b3318cf9cbd0eba5b29247c00c0a907b9\ttests/process.rs\0"
    b"100644 blob 32015383667db1ff184041db8346186ccf2e3fa8\ttests/relay.rs\0"
    b"100644 blob 7543ae8c54ece8e0b1aef61824fab595a2f2be1c\ttests/relay/version_skew.rs\0"
    b"100644 blob 3c621e1c82b6219e4e65453c303bc03561424774\ttests/selected_capability_roots.rs\0"
    b"100644 blob 8e09d7dafd8ad4561af48751fe0b4a7cd4db1518\ttests/support/BUILD.bazel\0"
    b"100644 blob 85ad347b6c5494746f3f017096c7c6a8f4392435\ttests/support/Cargo.toml\0"
    b"100644 blob 52343635649f15834c639cb3920aa3e61f271bd6\ttests/support/lib.rs\0"
    b"100644 blob d4b0fd8adc3d1f466aba874c0546d7afc72bf3ff\ttests/websocket.rs\0"
)
BINDING = (
    "codex-rs/exec-server",
    "6e7fb23cad63c4d9cd0c7ae24faae16c16def394",
    "040d2b09f7f1ed6dcf930c0c6032868e32b52764",
)


class DependencyProjectionTests(unittest.TestCase):
    def project(self, listing=PINNED_LISTING, binding=BINDING):
        return identity._exec_server_test_projection(*binding, listing)

    def test_complete_reviewed_tree_preserves_actual_and_original_identities(self):
        self.assertEqual(self.project(), {
            "schema": "codex.hia.path-dependency-test-projection.v1",
            "dependency": "codex-rs/exec-server",
            "actual_tree": "040d2b09f7f1ed6dcf930c0c6032868e32b52764",
            "original_tree": "6e7fb23cad63c4d9cd0c7ae24faae16c16def394",
            "leaf_count": 143,
            "projected_original_tree": "6e7fb23cad63c4d9cd0c7ae24faae16c16def394",
            "projection": {
                "path": "testing/wine_remote_test_runner.rs", "mode": "100644",
                "actual_blob": "41cd6bfc1531c414b135936480ae6c37985de772",
                "original_blob": "6e73e68e9b6c7237181beca458741045b3dfe972",
            },
        })

    def test_record_order_does_not_replace_canonical_tree_order(self):
        records = PINNED_LISTING[:-1].split(b"\0")
        reversed_listing = b"\0".join(reversed(records)) + b"\0"
        self.assertEqual(self.project(reversed_listing), self.project())

    def test_only_the_exact_dependency_and_both_tree_pins_are_accepted(self):
        for binding in (
            ("codex-rs/utils/path-uri", BINDING[1], BINDING[2]),
            (BINDING[0], "0" * 40, BINDING[2]),
            (BINDING[0], BINDING[1], BINDING[1]),
            (BINDING[0], BINDING[1], "0" * 40),
        ):
            with self.subTest(binding=binding), self.assertRaises(RuntimeError):
                self.project(binding=binding)

    def test_missing_extra_duplicate_and_incomplete_records_are_rejected(self):
        records = PINNED_LISTING[:-1].split(b"\0")
        extra = b"100644 blob " + b"0" * 40 + b"\textra.txt"
        malformed = (
            b"\0".join(records[1:]) + b"\0",
            b"\0".join(records + [extra]) + b"\0",
            b"\0".join(records[:-1] + [records[0]]) + b"\0",
            PINNED_LISTING[:-1],
            PINNED_LISTING + b"\0",
            b"",
        )
        for index, listing in enumerate(malformed):
            with self.subTest(index=index), self.assertRaises(RuntimeError):
                self.project(listing)

    def test_other_library_source_blob_drift_is_rejected(self):
        source = b"8a2616a2001bcbb06b2b9bd1420c274c1c73cb81\tsrc/lib.rs\0"
        changed = PINNED_LISTING.replace(source, b"0" * 40 + b"\tsrc/lib.rs\0", 1)
        self.assertNotEqual(changed, PINNED_LISTING)
        with self.assertRaises(RuntimeError):
            self.project(changed)

    def test_modes_kinds_noncanonical_paths_and_file_directory_collisions_are_rejected(self):
        first = b"100644 blob edd3380811608c669440f20c0083b01fe60874a7\tBUILD.bazel\0"
        for changed in (
            first.replace(b"100644", b"100755", 1),
            first.replace(b"100644", b"120000", 1),
            first.replace(b"blob ", b"commit ", 1),
            first.replace(b"edd338", b"EDD338", 1),
            first.replace(b"BUILD.bazel", b"../BUILD.bazel", 1),
            first.replace(b"BUILD.bazel", b"/BUILD.bazel", 1),
            first.replace(b"BUILD.bazel", b"src//BUILD.bazel", 1),
            first.replace(b"BUILD.bazel", b"src", 1),
            first.replace(b"BUILD.bazel", b"\xff", 1),
        ):
            listing = PINNED_LISTING.replace(first, changed, 1)
            self.assertNotEqual(listing, PINNED_LISTING)
            with self.subTest(record=changed), self.assertRaises(RuntimeError):
                self.project(listing)

    def test_exact_wine_leaf_blob_mode_and_path_are_required(self):
        original = (
            b"100644 blob 41cd6bfc1531c414b135936480ae6c37985de772"
            b"\ttesting/wine_remote_test_runner.rs\0"
        )
        for changed in (
            original.replace(b"41cd6bfc1531c414b135936480ae6c37985de772",
                             b"6e73e68e9b6c7237181beca458741045b3dfe972", 1),
            original.replace(b"100644", b"100755", 1),
            original.replace(b"wine_remote_test_runner.rs", b"other_runner.rs", 1),
        ):
            listing = PINNED_LISTING.replace(original, changed, 1)
            self.assertNotEqual(listing, PINNED_LISTING)
            with self.subTest(record=changed), self.assertRaises(RuntimeError):
                self.project(listing)


class IndependentLibraryCopyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.source = root / "producer.rlib"
        self.source.write_bytes(b"!<arch>\nfixture")
        self.stage = root / "stage"
        self.stage.mkdir()
        self.staged = self.stage / "snapshot.rlib"
        self.digest = identity.sha(self.source)
        self.size = self.source.stat().st_size

    def graph(self):
        return {"stage": str(self.stage), "files": {
            self.staged.name: {"source": str(self.source), "path": str(self.staged),
                               "bytes": self.size, "sha256": self.digest},
        }}

    def test_copy_is_independent_and_later_producer_mutation_is_detected(self):
        original = self.source.read_bytes()
        self.assertEqual(cargo.stage_library(self.source, self.staged, self.digest), self.size)
        self.assertEqual(self.staged.read_bytes(), original)
        self.assertFalse(self.source.samefile(self.staged))
        cargo.verify_graph(self.graph())
        self.source.write_bytes(b"x" * self.size)
        self.assertEqual(self.staged.read_bytes(), original)
        with self.assertRaises(RuntimeError):
            cargo.verify_graph(self.graph())

    def test_matching_hardlink_is_rejected_even_with_exact_bytes(self):
        self.staged.hardlink_to(self.source)
        with self.assertRaises(RuntimeError):
            cargo.verify_graph(self.graph())

    def test_existing_snapshot_is_not_overwritten(self):
        self.staged.write_bytes(b"retained evidence")
        with self.assertRaises(FileExistsError):
            cargo.stage_library(self.source, self.staged, self.digest)
        self.assertEqual(self.staged.read_bytes(), b"retained evidence")

    def test_source_digest_mismatch_is_rejected(self):
        self.source.write_bytes(b"x" * self.size)
        with self.assertRaises(RuntimeError):
            cargo.stage_library(self.source, self.staged, self.digest)


if __name__ == "__main__":
    unittest.main()
