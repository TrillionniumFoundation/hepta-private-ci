use super::*;
use crate::native_presentation::{OwnedComposition, tests::Client};
use hepta_control_core::chat::ChatWorkspace;

fn mode(exits: &Rc<Cell<usize>>) -> LaunchMode {
    LaunchMode::Presentation(OwnedComposition::new(Box::new(Client {
        workspace: ChatWorkspace::default(),
        exits: Rc::clone(exits),
    })))
}

// These closures exercise the actual admission/cleanup mechanism without
// opening a window. They are not evidence of renderer or resource loading.
fn complete_test_loop() {
    let setup = PENDING.with(|slot| slot.borrow_mut().take().unwrap());
    setup.outcome.borrow_mut().adopted = true;
    setup.outcome.borrow_mut().exited = true;
}

#[test]
fn reentrant_admission_cannot_replace_the_first_composition() {
    let first_exits = Rc::new(Cell::new(0));
    let second_exits = Rc::new(Cell::new(0));
    let result = run_with_loop(mode(&first_exits), Box::new(|_| {}), || {
        assert!(PENDING.with(|slot| slot.borrow().is_some()));
        let nested = run_with_loop(mode(&second_exits), Box::new(|_| {}), || {
            panic!("a rejected nested loop must never run");
        });
        assert!(nested.unwrap_err().contains("already running"));
        assert_eq!(second_exits.get(), 1);
        assert_eq!(first_exits.get(), 0);
        complete_test_loop();
    });
    assert!(result.is_ok());
    assert_eq!(first_exits.get(), 1);
    assert!(!RUNNING.with(Cell::get));
    assert!(PENDING.with(|slot| slot.borrow().is_none()));
}

#[test]
fn an_unadopted_loop_cannot_report_success_and_releases_pending_state() {
    let exits = Rc::new(Cell::new(0));
    let result = run_with_loop(mode(&exits), Box::new(|_| {}), || {});
    assert!(result.unwrap_err().contains("did not complete"));
    assert_eq!(exits.get(), 1);
    assert!(!RUNNING.with(Cell::get));
    assert!(PENDING.with(|slot| slot.borrow().is_none()));
    let later = Rc::new(Cell::new(0));
    assert!(run_with_loop(mode(&later), Box::new(|_| {}), complete_test_loop).is_ok());
    assert_eq!(later.get(), 1);
}

#[test]
fn an_unwound_loop_releases_admission_and_closes_the_pending_client_once() {
    let exits = Rc::new(Cell::new(0));
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        run_with_loop(mode(&exits), Box::new(|_| {}), || {
            panic!("test setup failure")
        })
    }));
    assert!(result.is_err());
    assert_eq!(exits.get(), 1);
    assert!(!RUNNING.with(Cell::get));
    assert!(PENDING.with(|slot| slot.borrow().is_none()));
    let later = Rc::new(Cell::new(0));
    assert!(run_with_loop(mode(&later), Box::new(|_| {}), complete_test_loop).is_ok());
    assert_eq!(later.get(), 1);
}
