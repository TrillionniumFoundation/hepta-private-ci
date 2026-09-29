#!/usr/bin/env python3
"""Idempotent runtime.codex follow-up migration.

This pass closes compile drift left outside the protocol migration, removes test
fixtures that look like production cryptographic constants, and makes the
permissive final-use constructor available only through the explicit test-support
surface. It intentionally makes no external deployment claim.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rewrite(path: str, transform) -> None:
    target = ROOT / path
    before = target.read_text(encoding="utf-8")
    after = transform(before)
    if after != before:
        target.write_text(after, encoding="utf-8")


def replace_once(text: str, old: str, new: str, marker: str) -> str:
    if old in text:
        if text.count(old) != 1:
            raise RuntimeError(f"{marker}: expected exactly one legacy block")
        return text.replace(old, new)
    if marker in text:
        return text
    raise RuntimeError(f"{marker}: legacy block and marker are both absent")


def add_dependency(text: str, section: str, line: str) -> str:
    if line in text:
        return text
    marker = f"[{section}]\n"
    if marker not in text:
        raise RuntimeError(f"missing Cargo section {section}")
    return text.replace(marker, marker + line + "\n", 1)


def native_app_server(text: str) -> str:
    text = text.replace(
        "use codex_hepta_infer_core::durable_control::native::NativeOwnerDispatchBinding;\n",
        "",
    )
    text = text.replace(
        '''    let abort = prepared
        .pre_effect_abort
        .as_ref()
        .ok_or("prepared native abort omitted its durable proof")?;
''',
        '''    let abort = prepared
        .pre_effect_abort
        .clone()
        .ok_or("prepared native abort omitted its durable proof")?;
''',
    )
    text = text.replace(
        '''        let Some(abort) = record.pre_effect_abort.as_ref() else {
            return Ok(());
        };
''',
        '''        let Some(abort) = record.pre_effect_abort.clone() else {
            return Ok(());
        };
''',
    )
    return text


def native_app_server_tests(text: str) -> str:
    old = '''    let host = CognitiveTestHost::start_with_executable(
        root,
        agent_id,
        MODEL,
        &format!("{}/v1", server.uri()),
        codex_utils_cargo_bin::cargo_bin("codex")?,
    )
    .await?;
'''
    new = '''    // runtime.codex-current-test-host-v1: use the canonical in-process
    // Agentd/App Server product composition rather than a removed executable seam.
    let host = CognitiveTestHost::start(
        root,
        agent_id,
        MODEL,
        &format!("{}/v1", server.uri()),
    )
    .await?;
'''
    return replace_once(text, old, new, "runtime.codex-current-test-host-v1")


def native_control(text: str) -> str:
    text = text.replace(
        '''        let mut abort_nonce = [0_u8; 32];
        rand::rng().fill_bytes(&mut abort_nonce);
''',
        '''        // Generated for each live process; never a source-embedded cryptographic value.
        let abort_nonce: [u8; 32] = rand::random();
''',
    )
    old = '''fn decode_abort_nonce(value: &str) -> Result<[u8; 32], Error> {
    if value.len() != 64 {
        return Err(Error::InvalidIdentity("native abort nonce"));
    }
    let mut nonce = [0_u8; 32];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        let high = abort_hex_nibble(pair[0]).ok_or(Error::InvalidIdentity("native abort nonce"))?;
        let low = abort_hex_nibble(pair[1]).ok_or(Error::InvalidIdentity("native abort nonce"))?;
        nonce[index] = (high << 4) | low;
    }
    Ok(nonce)
}
'''
    new = '''fn decode_abort_nonce(value: &str) -> Result<[u8; 32], Error> {
    if value.len() != 64 {
        return Err(Error::InvalidIdentity("native abort nonce"));
    }
    let mut decoded = Vec::with_capacity(32);
    for pair in value.as_bytes().chunks_exact(2) {
        let high = abort_hex_nibble(pair[0]).ok_or(Error::InvalidIdentity("native abort nonce"))?;
        let low = abort_hex_nibble(pair[1]).ok_or(Error::InvalidIdentity("native abort nonce"))?;
        decoded.push((high << 4) | low);
    }
    decoded
        .try_into()
        .map_err(|_| Error::InvalidIdentity("native abort nonce"))
}
'''
    return replace_once(text, old, new, "let mut decoded = Vec::with_capacity(32)")


def lane_b_runtime(text: str) -> str:
    old = '''fn decode_abort_nonce_hex(value: &str) -> Result<[u8; 32], AgentRunError> {
    if value.len() != 64 {
        return Err(AgentRunError::InvalidDigest("pre-effect abort nonce"));
    }
    let mut nonce = [0_u8; 32];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        let high = abort_hex_nibble(pair[0])
            .ok_or(AgentRunError::InvalidDigest("pre-effect abort nonce"))?;
        let low = abort_hex_nibble(pair[1])
            .ok_or(AgentRunError::InvalidDigest("pre-effect abort nonce"))?;
        nonce[index] = (high << 4) | low;
    }
    Ok(nonce)
}
'''
    new = '''fn decode_abort_nonce_hex(value: &str) -> Result<[u8; 32], AgentRunError> {
    if value.len() != 64 {
        return Err(AgentRunError::InvalidDigest("pre-effect abort nonce"));
    }
    let mut decoded = Vec::with_capacity(32);
    for pair in value.as_bytes().chunks_exact(2) {
        let high = abort_hex_nibble(pair[0])
            .ok_or(AgentRunError::InvalidDigest("pre-effect abort nonce"))?;
        let low = abort_hex_nibble(pair[1])
            .ok_or(AgentRunError::InvalidDigest("pre-effect abort nonce"))?;
        decoded.push((high << 4) | low);
    }
    decoded
        .try_into()
        .map_err(|_| AgentRunError::InvalidDigest("pre-effect abort nonce"))
}
'''
    return replace_once(text, old, new, "let mut decoded = Vec::with_capacity(32)")


def lane_b_tests(text: str) -> str:
    text = text.replace(
        "    let nonce = [42_u8; 32];\n",
        "    let nonce: [u8; 32] = rand::random();\n",
    )
    return text


def final_use_authorizer(text: str) -> str:
    old = '''    pub fn from_config(config: FinalUseAuthorizerConfig) -> Result<Self> {
        Self::from_config_inner(config, false)
    }
'''
    new = '''    /// Build from an already decoded production configuration. This path has
    /// the same Linux process-identity requirement as `open`; callers cannot
    /// use a decoded config to bypass the production issuer fence.
    pub fn from_config(config: FinalUseAuthorizerConfig) -> Result<Self> {
        Self::from_config_inner(config, cfg!(target_os = "linux"))
    }

    /// Explicit non-production constructor for unit/product qualification.
    /// It is absent from normal dependency builds unless `test-support` is
    /// selected, preventing product code from acquiring an unchecked issuer.
    #[cfg(any(test, feature = "test-support"))]
    pub fn from_test_config(config: FinalUseAuthorizerConfig) -> Result<Self> {
        Self::from_config_inner(config, false)
    }
'''
    text = replace_once(text, old, new, "from_test_config")
    text = text.replace(
        "Tests may use `from_config` without that\n    /// external deployment binding.",
        "Tests may use the explicit `from_test_config` test-support surface."
    )
    return text


def signing_key_tests(text: str) -> str:
    if "fn random_signing_key()" not in text:
        insertion = '''use tokio::net::UnixListener;

fn random_signing_key() -> SigningKey {
    SigningKey::from_bytes(&rand::random())
}
'''
        text = text.replace("use tokio::net::UnixListener;\n", insertion, 1)
    text = re.sub(
        r"SigningKey::from_bytes\(&\[[0-9]+; 32\]\)",
        "random_signing_key()",
        text,
    )
    text = text.replace(
        "UnixFinalUseAuthorizer::from_config(",
        "UnixFinalUseAuthorizer::from_test_config(",
    )
    return text


def quarantine_tests(text: str) -> str:
    if "fn random_signing_key()" not in text:
        marker = '''    fn digest(byte: u8) -> [u8; 32] {
        [byte; 32]
    }
'''
        replacement = marker + '''
    fn random_signing_key() -> SigningKey {
        SigningKey::from_bytes(&rand::random())
    }
'''
        text = replace_once(text, marker, replacement, "fn random_signing_key()")
    text = re.sub(
        r"SigningKey::from_bytes\(&\[[0-9]+; 32\]\)",
        "random_signing_key()",
        text,
    )
    old = '''        let signed = signed(&key, proposal);
        assert!(matches!(
            verifier(&key).verify(&signed, &quarantine, 2_000),
            Err(QuarantineProtocolError::QuarantineBindingMismatch)
        ));

        let other = random_signing_key();
        let forged = signed(
'''
    new = '''        let signed_proposal = signed(&key, proposal);
        assert!(matches!(
            verifier(&key).verify(&signed_proposal, &quarantine, 2_000),
            Err(QuarantineProtocolError::QuarantineBindingMismatch)
        ));

        let other = random_signing_key();
        let forged = signed(
'''
    text = replace_once(text, old, new, "let signed_proposal =")
    old = '''        let constraints = proposal.new_operation_constraints.as_mut().unwrap();
        constraints.operation_id = quarantine.operation_id.clone();
        assert!(matches!(
            proposal.signing_bytes(),
            Err(QuarantineProtocolError::UnsafeNewOperation)
        ));
        constraints.operation_id = "operation:new".to_string();
        constraints.maximum_attempts = 2;
        assert!(matches!(
            proposal.signing_bytes(),
            Err(QuarantineProtocolError::UnsafeNewOperation)
        ));
'''
    new = '''        proposal
            .new_operation_constraints
            .as_mut()
            .unwrap()
            .operation_id = quarantine.operation_id.clone();
        assert!(matches!(
            proposal.signing_bytes(),
            Err(QuarantineProtocolError::UnsafeNewOperation)
        ));
        {
            let constraints = proposal.new_operation_constraints.as_mut().unwrap();
            constraints.operation_id = "operation:new".to_string();
            constraints.maximum_attempts = 2;
        }
        assert!(matches!(
            proposal.signing_bytes(),
            Err(QuarantineProtocolError::UnsafeNewOperation)
        ));
'''
    return replace_once(text, old, new, "constraints.operation_id = \"operation:new\"")


def worker_cargo(text: str) -> str:
    if "test-support = []" not in text:
        text = text.replace(
            "[lib]\n",
            "[features]\ndefault = []\ntest-support = []\n\n[lib]\n",
            1,
        )
    return add_dependency(text, "dev-dependencies", "rand = { workspace = true }")


def agentd_cargo(text: str) -> str:
    text = add_dependency(text, "dev-dependencies", "rand = { workspace = true }")
    old = 'codex-hepta-infer-worker-host = { path = "../hepta-infer-worker-host" }'
    new = 'codex-hepta-infer-worker-host = { path = "../hepta-infer-worker-host", features = ["test-support"] }'
    if old in text:
        text = text.replace(old, new, 1)
    return text


def product_e2e(text: str) -> str:
    text = text.replace(
        "UnixFinalUseAuthorizer::from_config(",
        "UnixFinalUseAuthorizer::from_test_config(",
    )
    if "fn random_signing_key()" not in text and "SigningKey::from_bytes" in text:
        # Insert after the SigningKey import, preserving test-only scope.
        text = text.replace(
            "use ed25519_dalek::SigningKey;\n",
            "use ed25519_dalek::SigningKey;\n\nfn random_signing_key() -> SigningKey {\n    SigningKey::from_bytes(&rand::random())\n}\n",
            1,
        )
    text = re.sub(
        r"SigningKey::from_bytes\(&\[[0-9]+; 32\]\)",
        "random_signing_key()",
        text,
    )
    return text


def main() -> None:
    rewrite("codex-rs/hepta-infer-worker-host/src/native_app_server.rs", native_app_server)
    rewrite("codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs", native_app_server_tests)
    rewrite("codex-rs/hepta-infer-core/src/native_control.rs", native_control)
    rewrite("codex-rs/hepta-agentd/src/lane_b_runtime.rs", lane_b_runtime)
    rewrite("codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs", lane_b_tests)
    rewrite("codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs", final_use_authorizer)
    rewrite("codex-rs/hepta-infer-worker-host/src/final_use_authorizer_tests.rs", signing_key_tests)
    rewrite("codex-rs/hepta-infer-worker-host/src/runtime_codex_quarantine.rs", quarantine_tests)
    rewrite("codex-rs/hepta-infer-worker-host/Cargo.toml", worker_cargo)
    rewrite("codex-rs/hepta-agentd/Cargo.toml", agentd_cargo)
    rewrite("codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs", product_e2e)


if __name__ == "__main__":
    main()
