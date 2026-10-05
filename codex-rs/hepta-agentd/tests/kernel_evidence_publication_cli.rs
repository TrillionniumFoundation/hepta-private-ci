//! The Agentd binary disables its test harness. Compile its actual publication
//! argument parser here so the CLI regressions execute as an integration target.
#![cfg(unix)]

#[path = "../src/evidence_publication_cli.rs"]
mod evidence_publication_cli;
