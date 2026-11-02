//! Native nine-parameter static-boundary/finite-generator sensitivities.
//! This differentiates the declared quadrature and piecewise reset map;
//! it is not a continuum neural free-boundary or full financial value model.
use crate::dual::Dual;
use std::error::Error;
pub type Result<T> = std::result::Result<T, Box<dyn Error>>;
pub const LOWER: [f64;9] = [0.079,0.0195,0.59,0.265,6.30,61.0,0.15,0.002,0.5];
pub const UPPER: [f64;9] = [0.081,0.0205,0.61,0.275,6.48,62.4,0.4,0.04,2.0];
pub struct Model { pub words: Vec<Dual>, pub lower: usize, pub reset: f64 }
const X: [f64; 8] = [
    0.0950125098376374405,
    0.281603550779258915,
    0.458016777657227370,
    0.617876244402643771,
    0.755404408355002999,
    0.865631202387831755,
    0.944575023073232600,
    0.989400934991649939,
];
const W: [f64; 8] = [
    0.189450610455068641,
    0.182603415044923639,
    0.169156519395002647,
    0.149595988816576708,
    0.124628971255534071,
    0.0951585116824926053,
    0.0622535239386474565,
    0.0271524594117541762,
];


fn ensure(condition: bool, message: &str) -> Result<()> {
    if condition { Ok(()) } else { Err(message.into()) }
}
fn integrate(a:f64,b:f64,f:impl Fn(f64)->Dual)->Dual {
    let (middle,half)=((a+b)/2.0,(b-a)/2.0);
    let mut sum=Dual::constant(0.0);
    for (x,w) in X.iter().zip(W) { sum=sum+w*(f(middle-half*x)+f(middle+half*x)); }
    half*sum
}
fn normal_tail(x:Dual)->Result<Dual> {
    ensure(x.v.is_finite() && x.v<0.0 && x.v>=-12.0,"tail argument outside negative profile")?;
    let mut integral=Dual::constant(0.0);
    for k in 0..12 {
        integral=integral+integrate(k as f64,(k+1) as f64,|t|(x*t-t*t/2.0).exp());
    }
    Ok((-x*x/2.0).exp()*integral/(2.0*std::f64::consts::PI).sqrt())
}
fn b_function(z:Dual,s:Dual,y:Dual,tail:Dual)->Dual {
    integrate(0.0,1.0,|t|{
        let at=-z+t*(z+y);
        s*(-0.5*at*at*s*s).exp()/(2.0*std::f64::consts::PI).sqrt()
        +at*s*s*(0.5*(z-at)*(z+at)*s*s).exp()*tail
    })
}
pub fn construct(theta:[f64;9])->Result<Model> {
    for i in 0..9 {
        ensure(theta[i].is_finite() && theta[i]>=LOWER[i] && theta[i]<=UPPER[i],"parameter outside nine-coordinate box")?;
    }
    let [r,delta,alpha,tax,coupon,principal,sigma,liquidity,maturity]=
        std::array::from_fn(|i|Dual::variable(theta[i],i));
    let s2=sigma*sigma;
    let rate=r+liquidity;
    let a=(r-delta-s2/2.0)/s2;
    let z=(a*a+2.0*r/s2).sqrt();
    let zt=(a*a+2.0*rate/s2).sqrt();
    let eta=if a.v>=0.0 { 2.0*r/(s2*(z+a)) } else { z-a };
    let gamma=2.0*r/(s2*eta);
    let scale_s=sigma*maturity.sqrt();
    let c=coupon/maturity;
    let q=principal/maturity-c/rate;
    let discount=(-rate*maturity).exp();
    let cost=(1.0-tax)*coupon-(-rate*maturity).exp_m1()*q;
    let tail=normal_tail(-z*scale_s)?;
    let bs=b_function(z,scale_s,-zt,tail)+b_function(z,scale_s,zt,tail);
    let ba=b_function(z,scale_s,-a,tail)+b_function(z,scale_s,a,tail);
    let denominator=0.5*s2*(gamma+1.0)+alpha/maturity*bs;
    ensure(denominator.v.is_finite() && denominator.v>0.0,"nonpositive boundary denominator")?;
    let boundary=(cost/eta+q*discount*ba+c/rate*bs)/denominator;
    let flow=delta*boundary-(1.0-tax)*coupon+(alpha*boundary-principal)/maturity;
    let flow_scale=(delta.v*boundary.v).abs()+((1.0-tax.v)*coupon.v).abs()
        +((alpha.v*boundary.v).abs()+principal.v.abs())/maturity.v;
    ensure(boundary.v.is_finite() && boundary.v>0.0 && flow.v < -64.0*f64::EPSILON*flow_scale.max(1.0),"inadmissible static boundary")?;
    let reset=(90.0/boundary).ln();
    let centers:[f64;8]=std::array::from_fn(|i|(i as f64+0.5)*0.1);
    ensure(reset.v>centers[0] && reset.v<centers[7],"reset outside represented centers")?;
    ensure(centers.iter().all(|x|(reset.v-x).abs()>32.0*f64::EPSILON),"reset interpolation knot")?;
    let lower=centers.iter().take_while(|x|**x<reset.v).count()-1;
    let fraction=(reset-centers[lower])/0.1;
    let zero=Dual::constant(0.0);
    let mut weights=[zero;8];
    weights[lower]=1.0-fraction;
    weights[lower+1]=fraction;
    let diffusion=s2/2.0;
    let drift=r-delta-diffusion;
    let up=diffusion/0.01+drift/0.2;
    let down=diffusion/0.01-drift/0.2;
    let absorption=2.0*diffusion/0.01;
    ensure([up,down,absorption].iter().all(|x|x.v.is_finite() && x.v>0.0),"invalid centered rate")?;
    let mut matrix=vec![zero;1600];
    let edge=|matrix:&mut Vec<Dual>,source:usize,destination:usize,rate:Dual|{
        matrix[40*source+destination]=matrix[40*source+destination]+rate;
        matrix[40*source+source]=matrix[40*source+source]-rate;
    };
    let mut prior=[zero;40];
    for phase in 0..8 {
        for content in 0..4 {
            let source=4*phase+content;
            if phase<7 {edge(&mut matrix,source,source+4,up);}
            if phase>0 {edge(&mut matrix,source,source-4,down);} else {edge(&mut matrix,source,32+content,absorption);}
            prior[source]=weights[phase]/4.0;
        }
    }
    let recovery=Dual::constant(2.0/0.35);
    for content in 0..4 {
        edge(&mut matrix,32+content,36+content,recovery);
        for (phase,weight) in weights.iter().enumerate() {
            for destination in 0..4 {
                let retention=if content==destination {0.875} else {0.125/3.0};
                edge(&mut matrix,36+content,4*phase+destination,recovery*(*weight)*retention);
            }
        }
    }
    let mut words=vec![boundary];
    words.extend(matrix);
    for state in 0..40 {
        for observation in 0..5 {
            let value=if state>=32 {if observation==4 {1.0} else {0.0}}
                else if observation==4 {0.0} else if observation==state%4 {0.7} else {0.1};
            words.push(Dual::constant(value));
        }
    }
    for state in 0..40 {
        for observation in 0..4 {
            words.push(Dual::constant(if observation==state%4 {0.97} else {0.01}));
        }
    }
    words.extend(prior);
    ensure(words.iter().all(|x|x.v.is_finite() && x.g.iter().all(|y|y.is_finite())),"nonfinite constructed sensitivity")?;
    Ok(Model{words,lower,reset:reset.v})
}
