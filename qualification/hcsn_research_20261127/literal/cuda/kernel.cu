// Calibrated He--Xiong primitives and first derivatives on the open continuation region.
#include <cuda_runtime.h>
#include <cmath>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <limits>

static void check(cudaError_t e) {
    if(e!=cudaSuccess){std::fprintf(stderr,"CUDA: %s\n",cudaGetErrorString(e));std::exit(2);}
}
template<class T> struct D {
    T v,x,p;
    __host__ __device__ D(T a=0,T b=0,T c=0):v(a),x(b),p(c){}
    friend __device__ D operator+(D a,D b){return {a.v+b.v,a.x+b.x,a.p+b.p};}
    friend __device__ D operator-(D a,D b){return {a.v-b.v,a.x-b.x,a.p-b.p};}
    friend __device__ D operator-(D a){return {-a.v,-a.x,-a.p};}
    friend __device__ D operator*(D a,D b){return {a.v*b.v,a.x*b.v+a.v*b.x,a.p*b.v+a.v*b.p};}
    friend __device__ D operator/(D a,D b){T q=a.v/b.v;return {q,(a.x-q*b.x)/b.v,(a.p-q*b.p)/b.v};}
};
template<class T> __device__ D<T> dexp(D<T> a){T v=exp(a.v);return {v,v*a.x,v*a.p};}
template<class T> __device__ D<T> dexpm1(D<T> a){T v=expm1(a.v),d=exp(a.v);return {v,d*a.x,d*a.p};}
template<class T> __device__ D<T> dlog(D<T> a){return {log(a.v),a.x/a.v,a.p/a.v};}
template<class T> __device__ D<T> dphi(D<T> a){T v=exp(-a.v*a.v/T(2))/T(2.5066282746310005024);return {v,-a.v*v*a.x,-a.v*v*a.p};}
template<class T> __device__ D<T> dcdf(D<T> a){T v=erfc(-a.v/T(1.4142135623730950488))/T(2);T d=exp(-a.v*a.v/T(2))/T(2.5066282746310005024);return {v,d*a.x,d*a.p};}
template<class T> __device__ D<T> dtanh(D<T> a){T v=tanh(a.v),d=T(1)-v*v;return {v,d*a.x,d*a.p};}
struct Const {
    double a,z,zb,eta,gamma,bc,bp,base,disc;
};
static double phi_cdf(double z){return .5*std::erfc(-z/std::sqrt(2.));}
static Const calibration(){
    double var=.23*.23,a=(.08-.02-.5*var)/var,z=std::sqrt(a*a+2*.08/var),zb=std::sqrt(a*a+2*.09/var),disc=std::exp(-.09),eta=z-a;
    auto small=[&](double y){return disc*(phi_cdf(y*.23)-std::exp(.08)*phi_cdf(-z*.23))/(z+y);};
    auto big=[&](double y){return (phi_cdf(y*.23)-std::exp((z*z-y*y)*var*.5)*phi_cdf(-z*.23))/(z+y);};
    double u=big(zb)+big(-zb),w=(1-disc)/eta+small(a)+small(-a),den=.02/(eta-1)+.60*u;
    double bc=((1-.27)/eta+(u-w)/.09)/den,bp=w/den;
    return {a,z,zb,eta,z+a,bc,bp,bc*6.39+bp*61.68,disc};
}
template<class T> __device__ D<T> tail(D<T> x,T y,T j,T a){
    T v=T(.23*.23),s=T(.23);
    return dexp(T(.5)*((j-a)*(j-a)-y*y)*v-j*x)*dcdf((-x+(j-a)*v)/s)-dexp(-(a+y)*x)*dcdf((-x+y*v)/s);
}
template<class T> __device__ D<T> full(D<T> x,T y,T j,T a){
    T v=T(.23*.23),s=T(.23);
    T coeff=erfc(-y*s/T(1.4142135623730950488))/T(2)-exp(((j-a)*(j-a)-y*y)*v/T(2))*erfc(-(j-a)*s/T(1.4142135623730950488))/T(2);
    return coeff*dexp(-j*x)+tail(x,y,j,a);
}
template<class T> __device__ D<T> aux(D<T> x,T y,T a,T z,T eta,T g){
    return (full(x,y,g,a)+tail(x,-y,-eta,a))/(z-y)+(full(x,-y,g,a)+tail(x,y,-eta,a))/(z+y);
}
template<class T> __device__ D<T> hitting(D<T> x,T dt,T a){
    T s=T(.23)*sqrt(dt),m=a*T(.23*.23)*dt;
    return dcdf((-x-m)/s)+dexp(-T(2)*a*x)*dcdf((-x+m)/s);
}
template<class T> __device__ D<T> posmean(D<T> m,T s){return m*dcdf(m/s)+s*dphi(m/s);}
template<class T,bool ordinary> __global__ void forward(const T* input,T* out,int n,Const c){
    int i=blockIdx.x*blockDim.x+threadIdx.x;if(i>=n)return;
    D<T> x(input[2*i],1,0),P(input[2*i+1],0,1);
    T a=T(c.a),z=T(c.z),zb=T(c.zb),eta=T(c.eta),g=T(c.gamma),var=T(.23*.23),disc=T(c.disc);
    D<T> B=T(c.bc*6.39)+T(c.bp)*P,lb=dlog(B/T(c.base));
    D<T> A,F,M;
    if(x.v<=0){A=D<T>(0);F=D<T>(1);M=D<T>(T(.30));}
    else if(ordinary){
        D<T> h=dtanh(T(3)*(x-T(.18))+T(.002)*(P-T(61.68)));
        A=T(14)*h+T(12);F=T(.5)-T(.4)*h;M=T(.2)+T(.15)*dtanh(x);
    } else {
        D<T> adj=P-T(6.39/.09),ec=T((1-.27)*6.39)+(T(1)-disc)*adj;
        D<T> pay=-T(.02)*B*dexp(-g*x)/(g+T(1));
        D<T> cost=-ec*(T(1)/eta-dexpm1(-g*x)/g);
        D<T> gap=T(.6)*B-T(6.39/.09);
        A=B*dexp(x)+(pay+cost+disc*adj*aux(x,a,a,z,eta,g)-gap*aux(x,zb,a,z,eta,g))/(z*var);
        F=hitting(x,T(1),a);
        T s=T(.23*.5),drift=a*var*T(.25);
        M=posmean(x+drift,s)-dexp(-T(2)*a*x)*posmean(-x+drift,s)+T(.30)*hitting(x,T(.25),a);
    }
    D<T> r[4]={A,F,lb,M};
    for(int k=0;k<4;++k){out[i*12+3*k]=r[k].v;out[i*12+3*k+1]=r[k].x;out[i*12+3*k+2]=r[k].p;}
}
static double now(){return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();}
template<class T,bool ordinary> void benchmark(int n,Const c,FILE* witness){
    double start=now();
    std::vector<T> data(n*2),out(n*12);
    for(int i=0;i<n;++i){data[2*i]=T(i==0?0.:(i%127-3)*.0103);data[2*i+1]=T(46+((i*17)%73)*.43);}
    T *in_dev,*out_dev;
    check(cudaMalloc(&in_dev,data.size()*sizeof(T)));check(cudaMalloc(&out_dev,out.size()*sizeof(T)));
    check(cudaMemcpy(in_dev,data.data(),data.size()*sizeof(T),cudaMemcpyHostToDevice));
    double input_ready=now();
    auto launch=[&](){forward<T,ordinary><<<(n+127)/128,128>>>(in_dev,out_dev,n,c);check(cudaGetLastError());};
    launch();check(cudaDeviceSynchronize());
    double first=now();
    for(int i=0;i<5;i++)launch();
    check(cudaDeviceSynchronize());
    cudaEvent_t lo,hi;check(cudaEventCreate(&lo));check(cudaEventCreate(&hi));
    std::vector<float> times;
    for(int i=0;i<21;i++){
        check(cudaEventRecord(lo));launch();check(cudaEventRecord(hi));check(cudaEventSynchronize(hi));
        float ms;check(cudaEventElapsedTime(&ms,lo,hi));times.push_back(ms);
    }
    double before_copy=now();
    check(cudaMemcpy(out.data(),out_dev,out.size()*sizeof(T),cudaMemcpyDeviceToHost));
    double after_copy=now();
    check(cudaFree(in_dev));check(cudaFree(out_dev));check(cudaEventDestroy(lo));check(cudaEventDestroy(hi));
    std::printf("{\"kind\":\"%s\",\"dtype_bytes\":%zu,\"n\":%d,\"allocate_and_input_s\":%.10g,\"first_launch_s\":%.10g,\"output_copy_s\":%.10g,\"whole_trial_s\":%.10g,\"kernel_ms\":[",ordinary?"ordinary":"literal",sizeof(T),n,input_ready-start,first-input_ready,after_copy-before_copy,now()-start);
    for(int k=0;k<21;k++){std::printf("%s%.8g",k?",":"",times[k]);}
    std::printf("]}\n");std::fflush(stdout);
    if(n==256&&!ordinary){for(int i=0;i<n;i++){std::fprintf(witness,"%zu,%d,%.17g,%.17g",sizeof(T),i,double(data[2*i]),double(data[2*i+1]));for(int j=0;j<12;j++)std::fprintf(witness,",%.17g",double(out[12*i+j]));std::fprintf(witness,"\n");}}
}
int main(){
    int devices=0;check(cudaGetDeviceCount(&devices));if(!devices)return 3;
    cudaDeviceProp p;check(cudaGetDeviceProperties(&p,0));std::fprintf(stderr,"GPU %s CC %d.%d (%zu bytes)\n",p.name,p.major,p.minor,p.totalGlobalMem);
    Const c=calibration();FILE* witness=std::fopen("witness.csv","w");if(!witness)return 4;
    for(int n:{256,4096,65536,262144}){
        benchmark<double,false>(n,c,witness);benchmark<double,true>(n,c,witness);
        benchmark<float,true>(n,c,witness);benchmark<float,false>(n,c,witness);
    }
    std::fclose(witness);
}
