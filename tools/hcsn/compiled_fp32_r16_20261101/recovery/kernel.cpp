#include "arithmetic.hpp"
#include <algorithm>
#include <cfenv>
#include <cstring>
#include <memory>

namespace hx {
inline int binomial(int n,int k){int v=1;for(int j=1;j<=k;++j)v=v*(n-j+1)/j;return v;}

template<class V>struct FullHX{
    using D=Dual<V>;
    std::array<D,9>theta{};
    D r,delta,sigma,alpha,tax,liquidity,m,C,P,s2,R,a,z,zt,eta,gamma,s,c,p,q,discount,cost,b;
    explicit FullHX(const float*input){
        for(int i=0;i<9;++i)theta[i]=D::input(input[i],i);
        r=theta[0];delta=theta[1];sigma=theta[2];alpha=theta[3];tax=theta[4];liquidity=theta[5];m=theta[6];C=theta[7];P=theta[8];
        s2=sigma*sigma;R=r+liquidity;a=(r-delta-s2/2)/s2;
        z=sqrt(a*a+2*r/s2);zt=sqrt(a*a+2*R/s2);
        eta=a.v>=integer<V>(0)?2*r/(s2*(z+a)):z-a;gamma=2*r/(s2*eta);
        s=sigma*sqrt(m);c=C/m;p=P/m;q=p-c/R;discount=exp(-R*m);
        cost=(1-tax)*C-expm1(-R*m)*q;
        D bs=B(-zt)+B(zt);
        b=(cost/eta+q*discount*(B(-a)+B(a))+(c/R)*bs)/(.5*s2*(gamma+1)+alpha/m*bs);
        D flow=delta*b-(1-tax)*C+(alpha*b-P)/m;
        V scale=absolute(delta.v*b.v)+absolute((integer<V>(1)-tax.v)*C.v)+(absolute(alpha.v*b.v)+absolute(P.v))/m.v;
        if(scale<integer<V>(1))scale=integer<V>(1);
        V epsilon;
        if constexpr(std::is_same_v<V,double>)epsilon=fixed<V>(0x1p-52);else epsilon=fixed<V>(0x1p-23);
        if(!finite(b.v)||b.v<=integer<V>(0)||flow.v>=-integer<V>(64)*epsilon*scale)
            throw std::runtime_error("Unresolved or inadmissible local stopping boundary");
    }

    D B(const D&y)const{
        D denominator=z+y;
        if(absolute(denominator.v)<fixed<V>(.001)*(integer<V>(1)+z.v)){
            D result=number<V>(0);
            for(int i=0;i<8;++i){
                D at=-z+NODES[i]*denominator;
                D exponent=.5*(z-at)*(z+at)*s*s;
                result=result+WEIGHTS[i]*(s*exp_phi(number<V>(0),at*s)+at*s*s*exp_cdf(exponent,-z*s));
            }
            return result;
        }
        return (Phi(y*s)-exp_cdf(.5*(z-y)*(z+y)*s*s,-z*s))/denominator;
    }

    std::array<D,2>first_hit(const D&x,const D&horizon)const{
        D st=sigma*sqrt(horizon);
        D f=Phi(-x/st-a*st)+exp_cdf(-2*a*x,-x/st+a*st);
        D g=exp_cdf((-a+zt)*x,-x/st-zt*st)+exp_cdf((-a-zt)*x,-x/st+zt*st);
        return {f,g};
    }

    D A(const D&x,const D&y)const{
        auto numerator=[&](const D&u,bool derivative){
            D exponent=.5*(z*z-u*u)*s*s;
            D common=-cdf_interval(exponent-gamma*x,z*s-x/s,z*s);
            common=common+exp_cdf(exponent+eta*x,-x/s-z*s);
            D positive=exp_cdf(-(a+u)*x,-x/s+u*s);
            D negative=exp_cdf(-(a-u)*x,-x/s-u*s);
            if(derivative)return s*exp_phi(-gamma*x,u*s)-u*s*s*common+x*positive
                -s*exp_phi(-(a+u)*x,-x/s+u*s)-x*negative+s*exp_phi(-(a-u)*x,-x/s-u*s);
            return exp(-gamma*x)*Phi(u*s)+common-positive-negative;
        };
        D result=number<V>(0);
        for(const D&u:std::array<D,2>{y,-y}){
            D denominator=z-u;
            if(absolute(denominator.v)<fixed<V>(.01)*(integer<V>(1)+z.v)){
                for(int i=0;i<8;++i)result=result-WEIGHTS[i]*numerator(z-NODES[i]*denominator,true);
            }else result=result+numerator(u,false)/denominator;
        }
        return result;
    }

    D raw_equity(const D&x)const{
        D result=b*exp(x)-delta*b/(z*s2)*exp(-gamma*x)/(gamma+1);
        result=result-cost/(z*s2)*(1/eta-expm1(-gamma*x)/gamma);
        result=result+(discount*q*A(x,a)-(alpha*b/m-c/R)*A(x,zt))/(z*s2);
        return result;
    }

    D taylor_equity(const D&x)const{
        auto derivatives=[&](const D&k,const D&argument){
            D density=exp_phi(number<V>(0),argument);
            std::array<D,8>hermite{};hermite[0]=number<V>(1);hermite[1]=argument;
            for(int n=1;n<7;++n)hermite[n+1]=argument*hermite[n]-number<V>(n)*hermite[n-1];
            std::array<D,9>result{};result[0]=Phi(argument);
            for(int n=1;n<9;++n){
                D value=pow(k,n)*result[0];
                for(int j=1;j<=n;++j)value=value+number<V>(binomial(n,j))*pow(k,n-j)*pow(-1/s,j)
                    *number<V>(j%2?1:-1)*hermite[j-1]*density;
                result[n]=value;
            }
            return result;
        };
        auto f0=derivatives(number<V>(0),-a*s),f1=derivatives(-2*a,a*s);
        auto g0=derivatives(-a+zt,-zt*s),g1=derivatives(-a-zt,zt*s);
        D recovery=alpha*b/m-c/R;
        D flow0=delta*b-(1-tax)*C+alpha*b/m-p;
        std::array<D,11>e{};e[0]=number<V>(0);e[1]=number<V>(0);
        for(int n=0;n<9;++n){
            D flow=n==0?flow0:delta*b-discount*q*(f0[n]+f1[n])+recovery*(g0[n]+g1[n]);
            e[n+2]=2*r/s2*e[n]-2*a*e[n+1]-2*flow/s2;
        }
        D value=number<V>(0);
        for(int n=10;n>=2;--n)value=value*x+e[n]/FACTORIAL[n];
        return x*x*value;
    }

    D equity(const D&x)const{
        D abs_a=a.v>=integer<V>(0)?a:-a;
        std::array<D,3>limits{D(Fixed(.002)),.02*s,.05/(1+abs_a+zt)};
        D limit=limits[0];for(int i=1;i<3;++i)if(limits[i].v<limit.v)limit=limits[i];
        if(x.v<=fixed<V>(.5)*limit.v)return taylor_equity(x);
        if(x.v>=limit.v)return raw_equity(x);
        D u=2*x/limit-1,weight=pow(u,3)*(10+u*(-15+6*u));
        return (1-weight)*taylor_equity(x)+weight*raw_equity(x);
    }

    std::array<D,5>state(float input,int coordinate)const{
        D argument=D::input(input,9);
        D e,f,g,debt;
        // True default is decided on finite values before taking a logarithm.
        // An invalid continuation margin must never be reclassified as default.
        if(coordinate==1 && argument.v<=b.v){
            e=number<V>(0);f=number<V>(1);g=number<V>(1);debt=alpha*b/m;
        }else{
            D x=coordinate==1?log(argument/b):argument;
            if(!finite(x.v))throw std::runtime_error("Nonfinite continuation margin");
            e=equity(x);auto fg=first_hit(x,m);f=fg[0];g=fg[1];
            debt=c/R+discount*q*(1-f);debt=debt+(alpha*b/m-c/R)*g;
        }
        return {b,e,f,g,debt};
    }
};

inline bool valid(const float*theta,float state,int coordinate){
    constexpr float lo[9]={.04f,.01f,.08f,0.f,0.f,1e-4f,.01f,.5f,20.f};
    constexpr float hi[9]={.15f,.2f,.8f,1.f,.6f,.1f,20.f,10.f,100.f};
    for(int i=0;i<9;++i)if(!std::isfinite(theta[i])||theta[i]<lo[i]||theta[i]>hi[i])return false;
    return (coordinate==0||coordinate==1)&&std::isfinite(state)&&(coordinate==1?state>0.f:state>=0.f);
}
inline double transport(float value){return static_cast<double>(value);}
inline double transport(double value){return value;}
inline double transport(Pair value){return static_cast<double>(value.rounded());}

template<class V>int batch(int count,const float*theta,const float*states,const int*coordinates,
                          int reuse_span,double*output,int*status){
    std::unique_ptr<FullHX<V>> model;
    int failures=0;
    for(int row=0;row<count;++row){
        if(reuse_span>0 && row%reuse_span==0)model.reset();
        double*destination=output+55*row;
        std::fill(destination,destination+55,std::numeric_limits<double>::quiet_NaN());
        status[row]=0;
        if(!valid(theta+9*row,states[row],coordinates[row])){status[row]=1;++failures;continue;}
        try{
            if(reuse_span>0 && row%reuse_span!=0 && std::memcmp(theta+9*row,theta+9*(row-row%reuse_span),9*sizeof(float))!=0)
                throw std::runtime_error("Reuse group has different parameters");
            if(reuse_span<=0||row%reuse_span==0||!model)model=std::make_unique<FullHX<V>>(theta+9*row);
            auto fields=model->state(states[row],coordinates[row]);
            for(int field=0;field<5;++field){
                if(!finite(fields[field].v))throw std::runtime_error("Nonfinite value");
                destination[field]=transport(fields[field].v);
                for(int column=0;column<10;++column){
                    if(!finite(fields[field].g[column]))throw std::runtime_error("Nonfinite tangent");
                    destination[5+field*10+column]=transport(fields[field].g[column]);
                }
            }
        }catch(const std::exception&){status[row]=2;++failures;model.reset();}
    }
    return failures;
}
}

extern "C" __attribute__((visibility("default"))) int hcsn_batch(int mode,int count,const float*theta,const float*states,const int*coordinates,
                          int reuse_span,double*output,int*status){
    if(count<0||reuse_span<0||std::fegetround()!=FE_TONEAREST)return -1;
    if(mode==0)return hx::batch<double>(count,theta,states,coordinates,reuse_span,output,status);
    if(mode==1)return hx::batch<float>(count,theta,states,coordinates,reuse_span,output,status);
    if(mode==2)return hx::batch<hx::Pair>(count,theta,states,coordinates,reuse_span,output,status);
    return -2;
}

extern "C" __attribute__((visibility("default"))) int hcsn_primitive(int operation,const float*input,float*output){
    using namespace hx;Pair a(input[0],input[1]),b(input[2],input[3]),result;
    try{
        switch(operation){
            case 0:result=a+b;break;case 1:result=a-b;break;case 2:result=a*b;break;case 3:result=a/b;break;
            case 4:result=real_exp(a);break;case 5:result=real_expm1(a);break;case 6:result=real_log(a);break;
            case 7:result=real_sqrt(a);break;case 8:result=real_cdf(a);break;case 9:result=real_logcdf(a);break;
            default:return -1;
        }
        output[0]=result.hi;output[1]=result.lo;return finite(result)?0:1;
    }catch(const std::exception&){return 2;}
}
