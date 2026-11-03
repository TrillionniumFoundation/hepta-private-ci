mod safe_yaml;
#[path = "baseline/parser.rs"]
mod baseline_parser;
#[path = "candidate/parser.rs"]
mod candidate_parser;
#[path = "baseline/command.rs"]
mod baseline_command;
#[path = "candidate/command.rs"]
mod candidate_command;
#[cfg(test)]
mod compatibility_tests;
