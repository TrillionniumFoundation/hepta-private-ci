//! Bounded test transport for differential qualification, never a service API.
mod transfer;
use std::collections::BTreeMap;
use std::io::{self, BufRead};
use transfer::{Cell, CellPhase, Operation, Request, Sources, State, transition};

fn byte(value: &str) -> Result<[u8; 32], String> {
    value
        .parse::<u8>()
        .map(|x| [x; 32])
        .map_err(|e| e.to_string())
}
fn main() -> Result<(), String> {
    let mut state = State {
        admin: [2; 32],
        cell: Cell {
            id: "cell".into(),
            owner: [3; 32],
            epoch: 1,
            bundle: [1; 32],
            phase: CellPhase::Active,
        },
        transfers: BTreeMap::new(),
    };
    for line in io::stdin().lock().lines() {
        let line = line.map_err(|e| e.to_string())?;
        if line.len() > 1024 {
            return Err("oversized test command".into());
        }
        let x: Vec<_> = line.split_whitespace().collect();
        if x.len() != 9 {
            return Err("expected nine test fields".into());
        }
        let (op, actor, epoch, expected, target, verified, source, id, cell) =
            (x[0], x[1], x[2], x[3], x[4], x[5], x[6], x[7], x[8]);
        if op == "reset" {
            state.cell = Cell {
                id: "cell".into(),
                owner: byte(actor)?,
                epoch: epoch.parse::<u64>().map_err(|e| e.to_string())?,
                bundle: byte(expected)?,
                phase: CellPhase::Active,
            };
            state.transfers.clear();
            println!("reset");
            continue;
        }
        let operation = match op {
            "prepare" => Operation::Prepare {
                target: byte(target)?,
            },
            "recover_prepare" => Operation::RecoverPrepare {
                target: byte(target)?,
            },
            "ready" => Operation::Ready {
                verified_bundle: byte(verified)?,
            },
            "commit" => Operation::Commit,
            "abort" => Operation::Abort,
            _ => return Err("unsupported test operation".into()),
        };
        let request = Request {
            cell: cell.into(),
            transfer: id.into(),
            actor: byte(actor)?,
            expected_epoch: epoch.parse::<u64>().map_err(|e| e.to_string())?,
            expected_bundle: byte(expected)?,
            operation,
        };
        let sources = match source {
            "1" => Sources::Current,
            "0" => Sources::Stale,
            _ => return Err("invalid source status".into()),
        };
        let outcome = match transition(&state, &request, sources) {
            Ok(next) => {
                state = next;
                "ok"
            }
            Err(_) => "rejected",
        };
        let phase = match state.cell.phase {
            CellPhase::Active => "active",
            CellPhase::Prepared => "prepared",
        };
        let transfer_phase = state
            .transfers
            .get(id)
            .map_or("none".into(), |t| format!("{:?}", t.phase).to_lowercase());
        let history: Vec<_> = state
            .transfers
            .iter()
            .map(|(id, t)| {
                format!(
                    "{}:{}:{}:{}:{}:{}",
                    id,
                    t.source[0],
                    t.target[0],
                    t.epoch,
                    format!("{:?}", t.phase).to_lowercase(),
                    t.recovery_controller.map_or(0, |v| v[0])
                )
            })
            .collect();
        println!(
            "{outcome} {} {} {phase} {transfer_phase} {}",
            state.cell.owner[0],
            state.cell.epoch,
            history.join(",")
        );
    }
    Ok(())
}
