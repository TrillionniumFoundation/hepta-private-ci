#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{relative}: expected one match, found {count}: {old!r}")
    path.write_text(text.replace(old, new, 1))


replace_once(
    "codex-rs/hepta-agentd/src/intelligence_learning_outbox.rs",
    "matches!(Self::Acknowledged | Self::Rejected | Self::Revoked, self)",
    "matches!(self, Self::Acknowledged | Self::Rejected | Self::Revoked)",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_learning_outbox.rs",
    "matches!(Self::Prepared | Self::Indeterminate, self)",
    "matches!(self, Self::Prepared | Self::Indeterminate)",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_learning_host.rs",
    """                    writer.append_decision(
                        parse_digest(&expected_predecessor)?,
                        decision.try_into()?,
                        &evidence.try_into()?,
                        now,
                    )
                }
                LearningCommandWireV1::Outcome {
""",
    """                    writer.append_decision(
                        parse_digest(&expected_predecessor)?,
                        decision.try_into()?,
                        &evidence.try_into()?,
                        now,
                    )
                },
                LearningCommandWireV1::Outcome {
""",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_learning_host.rs",
    """                    writer.append_outcome(
                        parse_digest(&expected_predecessor)?,
                        outcome,
                        &evidence.try_into()?,
                        now,
                    )
                }
            }
""",
    """                    writer.append_outcome(
                        parse_digest(&expected_predecessor)?,
                        outcome,
                        &evidence.try_into()?,
                        now,
                    )
                },
            }
""",
)

state = ROOT / "codex-rs/hepta-agentd/src/state.rs"
text = state.read_text()
bad = "            intelligence_invocation: std::sync::OnceLock::new()\n            intelligence_learning:"
good = "            intelligence_invocation: std::sync::OnceLock::new(),\n            intelligence_learning:"
if bad in text:
    text = text.replace(bad, good, 1)
elif good not in text:
    raise RuntimeError("state.rs: canonical intelligence constructor wiring is missing")
state.write_text(text)
