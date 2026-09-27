#!/usr/bin/env python3
"""Harden generated memory federation runtime ownership and tests."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text.rstrip() + "\n", encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{label}: expected one replacement, found {text.count(old)}")
    return text.replace(old, new, 1)


def patch_aggregator() -> None:
    path = "codex-rs/hepta-memory/src/cognitive_runtime_federation/aggregator.rs"
    text = read(path)
    text = replace_once(
        text,
        "                    if matches!(\n                        failure.error,\n",
        "                    if matches!(\n                        &failure.error,\n",
        "borrow attempt error for cancellation classification",
    )
    write(path, text)


def patch_telemetry_tests() -> None:
    path = "codex-rs/hepta-memory/src/cognitive_runtime_federation/telemetry.rs"
    text = read(path)
    marker = "    #[test]\n    fn cancellation_control_emits_bounded_canonical_receipt() {"
    extra = r'''    #[test]
    fn diagnostic_binding_is_completion_order_independent() {
        let first = FederatedPeerDiagnosticV2 {
            peer_digest: "b".to_string(),
            phase: FederationProductPhaseV2::Transport,
            disposition: FederationProductDispositionV2::Failed,
            failure: Some(FederationProductFailureV2::TransportUnavailable),
            cancellation_receipt_digest: None,
        };
        let second = FederatedPeerDiagnosticV2 {
            peer_digest: "a".to_string(),
            phase: FederationProductPhaseV2::Discovery,
            disposition: FederationProductDispositionV2::Truncated,
            failure: None,
            cancellation_receipt_digest: None,
        };
        let left = FederatedDiagnosticLedgerV2 {
            entries: vec![first.clone(), second.clone()],
            omitted_entries: 0,
        };
        let right = FederatedDiagnosticLedgerV2 {
            entries: vec![second, first],
            omitted_entries: 0,
        };
        assert_eq!(
            left.binding_sha256().expect("left binding"),
            right.binding_sha256().expect("right binding")
        );
    }

'''
    text = replace_once(text, marker, extra + marker, "diagnostic ordering test")
    write(path, text)


def patch_state_generator() -> None:
    path = "scripts/hepta-memory-federation-state.py"
    text = read(path)
    anchor = '    "scripts/memory_federation_codec_hardening.py",\n'
    addition = anchor + '    "scripts/memory_federation_runtime_hardening.py",\n'
    if addition not in text:
        text = replace_once(text, anchor, addition, "runtime hardening source path")
    write(path, text)


def main() -> None:
    patch_aggregator()
    patch_telemetry_tests()
    patch_state_generator()
    print("memory.federation generated runtime ownership hardened")


if __name__ == "__main__":
    main()
