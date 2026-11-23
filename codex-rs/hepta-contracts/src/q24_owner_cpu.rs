//! Linux qualification-job totals of existing synchronous calls. Static labels only.
use std::{cell::RefCell, collections::BTreeMap, io::Write, time::Instant};

type Cpu = fn() -> Option<u64>;
struct Acc { n:u64, wall:u64, cpu:u64, errors:u64 }
struct Run { case:&'static str, id:u64, cut:u64, start:Instant, first_cpu:u64, clock:Cpu, bad:u64, sums:BTreeMap<&'static str,Acc>, errors:Vec<(&'static str,&'static str,u64)> }
thread_local! { static ACTIVE: RefCell<Option<Run>>=const{RefCell::new(None)}; }
pub struct Owner(bool, Option<Run>);
pub fn begin(clock:Cpu)->Owner {
    if let Some((case,id,cut))=super::published_service() {
        let start=Instant::now();
        let first=clock();
        let replaced=ACTIVE.with(|s|s.replace(Some(Run{case,id,cut,start,first_cpu:first.unwrap_or(0),clock,bad:u64::from(first.is_none()),sums:BTreeMap::new(),errors:Vec::new()})));
        Owner(true,replaced)
    } else {Owner(false,None)}
}
impl Drop for Owner {
    fn drop(&mut self) {
        if !self.0{return}
        if let Some(mut s)=ACTIVE.with(|r|r.replace(self.1.take())) {
            let last=(s.clock)();let wall=s.start.elapsed().as_nanos() as u64;
            if last.is_none(){s.bad+=1}
            let cpu=last.unwrap_or(0).saturating_sub(s.first_cpu);
            let mut line=format!("\nQ24_OWNER case={} pid={} thread={:?} id={} cut={} wall_ns={} cpu_ns={} bad={} metrics=",
                s.case,std::process::id(),std::thread::current().id(),s.id,s.cut,wall,cpu,s.bad);
            {use std::fmt::Write as _;for (name,a) in s.sums {let _=write!(line,"{}:{}:{}:{}:{},",name,a.n,a.wall,a.cpu,a.errors);}
             line.push_str(" errors="); for(name,class,at)in s.errors{let _=write!(line,"{name}:{class}:{at},");}}
            line.push('\n');let _=std::io::stderr().lock().write_all(line.as_bytes());
        }
    }
}
pub struct Meter { label:&'static str, start:Option<(Instant,Option<u64>)>, outcome:&'static str }
impl Meter {
    pub fn start(label:&'static str)->Self {
        let c=ACTIVE.with(|r|r.borrow().as_ref().map(|s|s.clock));
        Self{label,start:c.map(|clock|(Instant::now(),clock())),outcome:"early_return"}
    }
    pub fn finish(&mut self,outcome:&'static str){self.outcome=outcome}
}
impl Drop for Meter {
    fn drop(&mut self) {
        let Some((start,begin))=self.start else{return};
        ACTIVE.with(|r|{if let Some(s)=r.borrow_mut().as_mut(){
            let end=(s.clock)();let now=Instant::now();let wall=now.duration_since(start).as_nanos() as u64;
            let cpu=match (begin,end){(Some(a),Some(b)) if a<=b=>b-a,_=>{s.bad+=1;0}};
            let k=s.sums.entry(self.label).or_insert(Acc{n:0,wall:0,cpu:0,errors:0});k.n+=1;k.wall+=wall;k.cpu+=cpu;
            if self.outcome!="ok"{k.errors+=1;s.errors.push((self.label,self.outcome,super::micros(now)))}
        }});
    }
}
