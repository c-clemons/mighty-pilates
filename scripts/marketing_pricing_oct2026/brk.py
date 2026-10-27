"""Interrupted time series / structural break: new clients by studio-month, break at April 2026 (marketing cut)."""
from base import *
import statsmodels.api as sm, statsmodels.formula.api as smf, warnings
warnings.filterwarnings('ignore')
new=pd.read_pickle('new.pkl')
OPEN={'BK':'2023-09','LF':'2022-08','PH':'2021-01','SM':'2021-01','WW':'2023-11','MR':'2023-04','RH':'2024-12','OP':'2025-03','DN':'2025-04','CC':'2025-07','SB':'2025-10'}
REGION2={'BK':'EB','LF':'EB','DN':'EB','PH':'SF','RH':'SF','MR':'SF','SM':'LA','WW':'LA','OP':'LA','CC':'LA','SB':'SB'}
months=pd.period_range('2023-01','2026-09',freq='M')
cnt=new.groupby(['S0','M0']).size()
rows=[]
for s,o in OPEN.items():
    o=pd.Period(o,'M')
    for m in months:
        age=(m-o).n
        if age<0: continue
        rows.append(dict(S=s,M=m,y=int(cnt.get((s,m),0)),age=age))
P=pd.DataFrame(rows)
P['moy']=P.M.dt.month.astype(str)
P['t']=P.M.apply(lambda p:(p-pd.Period('2023-01','M')).n)
P['agebin']=pd.cut(P.age,[-1,0,2,5,11,23,999],labels=['a0','a1_2','a3_5','a6_11','a12_23','a24p']).astype(str)
P['post']=(P.M>=pd.Period('2026-04','M')).astype(int)
P['jan26']=(P.M>=pd.Period('2026-01','M')).astype(int)
# cannibalisation: other studios open in same region (excluding self)
openp={s:pd.Period(o,'M') for s,o in OPEN.items()}
P['nbrs']=[sum(1 for s2,o2 in openp.items() if s2!=s and REGION2[s2]==REGION2[s] and o2<=m) for s,m in zip(P.S,P.M)]
P['sm']=P.S+'_'+P.moy
def fit(formula,data=P,label=''):
    r=smf.glm(formula,data=data,family=sm.families.Poisson()).fit(cov_type='cluster',cov_kwds={'groups':pd.factorize(data.M)[0]})
    b=r.params['post']; se=r.bse['post']
    d=data.copy(); d0=d.copy(); d0['post']=0
    post=d.post==1
    lost=(r.predict(d0)[post]-r.predict(d)[post]).sum()/post.loc[post].index.size* 0  # placeholder
    nm=d.loc[post,'M'].nunique()
    lost=(r.predict(d0)[post].sum()-r.predict(d)[post].sum())/nm
    lo=(np.exp(-(b-1.96*se))-1); hi=(np.exp(-(b+1.96*se))-1)
    return dict(label=label,beta=b,se=se,pct=np.exp(b)-1,lost_per_month=lost,ci_pct=(np.exp(b-1.96*se)-1,np.exp(b+1.96*se)-1),n=len(data))
if __name__=='__main__':
    specs=[
     ('A: studio + month-of-year + launch ramp','y ~ C(S) + C(moy) + C(agebin) + post'),
     ('B: A + Jan-2026 price break','y ~ C(S) + C(moy) + C(agebin) + jan26 + post'),
     ('C: A + common linear trend','y ~ C(S) + C(moy) + C(agebin) + t + post'),
     ('D: A + neighbouring openings','y ~ C(S) + C(moy) + C(agebin) + nbrs + post'),
     ('E: B + D','y ~ C(S) + C(moy) + C(agebin) + nbrs + jan26 + post'),
     ('F: B + D, studios open 12+ months only','y ~ C(S) + C(moy) + nbrs + jan26 + post'),
    ]
    out=[]
    for lab,f in specs:
        d=P if not lab.startswith('F') else P[P.age>=12]
        r=fit(f,d,lab); out.append(r)
        print(f"{lab:48s} effect {r['pct']*100:6.1f}%  (95% {r['ci_pct'][0]*100:5.1f}% to {r['ci_pct'][1]*100:5.1f}%)  lost/month {r['lost_per_month']:6.1f}  n={r['n']}")
    act=P[P.post==1].groupby('M').y.sum(); print('actual post months', act.to_dict())
