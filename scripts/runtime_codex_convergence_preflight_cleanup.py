#!/usr/bin/env python3
"""Extend the verified fixer with definitive-rejection cleanup."""

from pathlib import Path

root = Path(__file__).resolve().parents[1]
fixer = root / "scripts/runtime_codex_convergence_fix.py"
content = fixer.read_text(encoding="utf-8")
marker = "# The handoff is already generation-fenced by AgentdClient; the handoff type\n"
insertion = r"""# A typed overload/invalid-request response proves that no turn was admitted;
# close its preparatory ephemeral thread before returning the rejection.
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    r'''                        control.reject_native_before_start(
                            request_id,
                            NativeDispatchRejection {
                                status,
                                reason: reason.clone(),
                                response_digest: response_digest.to_string(),
                                retry_safe_before_admission,
                            },
                        )?;
                        let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
''',
    r'''                        control.reject_native_before_start(
                            request_id,
                            NativeDispatchRejection {
                                status,
                                reason: reason.clone(),
                                response_digest: response_digest.to_string(),
                                retry_safe_before_admission,
                            },
                        )?;
                        thread_lifecycle.close(&mut client, RPC_TIMEOUT).await;
                        let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
''',
)

"""
if content.count(marker) != 1:
    raise SystemExit(f"expected one fixer insertion marker, found {content.count(marker)}")
fixer.write_text(content.replace(marker, insertion + marker, 1), encoding="utf-8")
Path(__file__).unlink()
