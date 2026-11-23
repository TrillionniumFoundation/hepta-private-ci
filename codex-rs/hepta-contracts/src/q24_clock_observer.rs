//! Opt-in private-job timing only. Records static event names, never frames or credentials.
use std::cell::RefCell;
use std::io::Write;
use std::sync::OnceLock;
use std::time::Instant;

pub fn micros(at: Instant) -> u64 {
    static START: OnceLock<Instant> = OnceLock::new();
    at.saturating_duration_since(*START.get_or_init(Instant::now)).as_micros() as u64
}
struct Active {
    case: &'static str,
    role: &'static str,
    id: u64,
    cut: u64,
    io: &'static str,
    depth: u32,
    points: Vec<(&'static str, u64)>,
    bound: Option<(&'static str, u64)>,
}
thread_local! { static ACTIVE: RefCell<Option<Active>> = const { RefCell::new(None) }; }
pub struct Scope { previous: Option<Active>, installed: bool }
pub fn enter(case: Option<&'static str>, role: &'static str, id: u64, cut: u64) -> Scope {
    with_io(case, role, id, cut, "outer",0)
}
fn with_io(case: Option<&'static str>, role: &'static str, id: u64, cut: u64, io: &'static str, depth:u32) -> Scope {
    match case {
        Some(case) => {
            let now = micros(Instant::now());
            let previous = ACTIVE.with(|a| a.replace(Some(Active {
                case, role, id, cut, io, depth, points: vec![("enter",now)], bound: None,
            })));
            Scope {previous,installed:true}
        }
        None => Scope {previous:None,installed:false},
    }
}
pub fn channel(io: &'static str) -> Scope {
    let info=ACTIVE.with(|a|a.borrow().as_ref().map(|a|(a.case,a.role,a.id,a.cut,a.depth+1)));
    match info {
        Some((case,role,id,cut,depth))=>with_io(Some(case),role,id,cut,io,depth),
        None=>Scope{previous:None,installed:false},
    }
}
pub fn event(name: &'static str) {
    ACTIVE.with(|a| { if let Some(item)=a.borrow_mut().as_mut() {
        item.points.push((name, micros(Instant::now())));
    }});
}
pub fn bound(deadline: Instant, end: Instant) {
    ACTIVE.with(|a| { if let Some(item)=a.borrow_mut().as_mut() {
        item.bound=Some((if deadline==end {"lifetime"} else {"per_request"},micros(deadline)));
    }});
}
pub fn outcome(error:&crate::HostIssuerTransportError) {
    use crate::HostIssuerTransportError::*;
    event(match error {
        InvalidConfiguration=>"err_invalid_config",PeerDenied=>"err_peer_denied",Closed=>"err_closed",
        InvalidRequest=>"err_invalid_request",DeadlineElapsed=>"err_deadline_elapsed",Unavailable=>"err_unavailable",
    });
}
impl Drop for Scope {
    fn drop(&mut self) {
        if !self.installed { return; }
        let done=micros(Instant::now());
        let active=ACTIVE.with(|a| a.replace(self.previous.take()));
        if let Some(mut a)=active {
            a.points.push(("exit",done));
            let (kind,deadline)=a.bound.unwrap_or(("unselected",0));
            let mut line=format!("\nQ24_CLOCK case={} pid={} thread={:?} role={} id={} cut={} io={} depth={} bound={} deadline={} points=",a.case,std::process::id(),std::thread::current().id(),a.role,a.id,a.cut,a.io,a.depth,kind,deadline);
            for (n,t) in a.points {use std::fmt::Write as _;let _=write!(line,"{n}@{t},");}
            line.push('\n');let _=std::io::stderr().lock().write_all(line.as_bytes());
        }
    }
}
