from price3 import *
rng=np.random.default_rng(7)
t26=c26[c26.SEG.str.startswith('MMP $')].copy(); t25=c25[(c25.P0=='Mighty Monthly Pass')&(c25.PRICE0.round().isin([295,340]))].copy()
# total wallet (all products) by month offset
allm = sales.groupby(['GCK','M']).NET.sum()
def wallet(c, base):
    for k in range(0,8):
        m=pd.Period(base,'M')+k
        x=allm.xs(m,level='M') if m in allm.index.get_level_values('M') else pd.Series(dtype=float)
        c[f'W{k}']=c.GCK.map(x).fillna(0)
wallet(t26,'2026-02'); wallet(t25,'2025-02')
t26['PT']=t26.PRICE0.round(); t25['PT']=t25.PRICE0.round()
def adj(a,b,fn):
    """reweight b (2025) to a's (2026) tenure x price-tier mix; fn(df)->scalar"""
    w=a.groupby(['PT','TB'],observed=True).size()/len(a); tot=0; wt=0
    for (pt,tb),wi in w.items():
        sub=b[(b.PT==pt)&(b.TB==tb)]
        if len(sub)<5: sub=b[b.TB==tb]
        tot+=wi*fn(sub); wt+=wi
    return tot/wt
if __name__=='__main__':
    out={}
    print('k  bill26 bill25adj | autopay rev ratio 26 / 25adj | wallet ratio 26 / 25adj')
    base_ap=t26.AMT0.sum(); base_w=t26.W0.sum(); cum_a=cum_c=cumw_a=cumw_c=0
    for k in range(1,8):
        b26=t26[f'B{k}'].mean(); b25=adj(t26,t25,lambda d:d[f'B{k}'].mean())
        r26=t26[f'AMT{k}'].sum()/base_ap; r25=adj(t26,t25,lambda d:d[f'AMT{k}'].sum()/d.AMT0.sum())
        w26=t26[f'W{k}'].sum()/base_w; w25=adj(t26,t25,lambda d:d[f'W{k}'].sum()/d.W0.sum())
        if k>=2: cum_a+=r26*base_ap; cum_c+=r25*base_ap; cumw_a+=w26*base_w; cumw_c+=w25*base_w
        print(k, round(b26,3),round(b25,3),'|',round(r26,3),round(r25,3),'|',round(w26,3),round(w25,3), '| $ap', round(r26*base_ap), round(r25*base_ap))
    print('base autopay',base_ap,'base wallet',base_w)
    print('cum Apr-Sep autopay actual %.0f vs counterfactual %.0f diff %.0f'%(cum_a,cum_c,cum_a-cum_c))
    print('cum Apr-Sep wallet actual %.0f vs counterfactual %.0f diff %.0f'%(cumw_a,cumw_c,cumw_a-cumw_c))
    # elasticity w/ bootstrap
    def el(a,b,col):
        ra=a[col].mean(); rb=adj(a,b,lambda d:d[col].mean()); dp=((a.PT.map({295:330/295-1,340:360/340-1})).mean())
        return (ra/rb-1)/dp, ra, rb, dp
    for col in ('RET','B7'):
        for lab,f in (('all',lambda d:d),('295',lambda d:d[d.PT==295]),('340',lambda d:d[d.PT==340])):
            a,b=f(t26),f(t25); e=el(a,b,col)
            bs=[el(a.sample(len(a),replace=True,random_state=rng.integers(1e9)),b.sample(len(b),replace=True,random_state=rng.integers(1e9)),col)[0] for _ in range(600)]
            print(col,lab,'elasticity %.2f  ret26 %.3f cf %.3f dP %.3f  CI90 [%.2f, %.2f]  P(e<0)=%.2f P(e<-1)=%.2f'%(e[0],e[1],e[2],e[3],np.percentile(bs,5),np.percentile(bs,95),(np.array(bs)<0).mean(),(np.array(bs)<-1).mean()))
    # where did lapsed members go: still buying packs?
    for nm,c in (('2026',t26),('2025',t25)):
        l=c[~c.RET]; print(nm,'lapsed',len(l),'share with any purchase in months 6-7:',((l.W6>0)|(l.W7>0)).mean().round(3),'avg wallet m6+m7 per lapsed',((l.W6+l.W7).mean()).round(1))
    # same-store new members YoY from official table
    m=pd.read_pickle('mem.pkl'); m['S']=m.STUDIO.str.replace('Mighty Pilates ','').map(CODE)
    for col in ['NEW_MEMBERS','CHURNED','REACTIVATED','ACTIVE_EOM']: m[col]=pd.to_numeric(m[col])
    for per,(a,b) in {'Apr-Sep 2025':('2025-04','2025-09'),'Apr-Sep 2026':('2026-04','2026-09'),'Jan-Mar 2025':('2025-01','2025-03'),'Jan-Mar 2026':('2026-01','2026-03')}.items():
        x=m[m.MONTH.between(a,b)].groupby('S')[['NEW_MEMBERS','CHURNED','REACTIVATED']].sum().T; x['SAME6']=x[['BK','LF','PH','SM','WW']].sum(axis=1); x['ALL']=x.drop(columns='SAME6').sum(axis=1); print(per); print(x.to_string())
    e=m.pivot_table(index='MONTH',columns='S',values='ACTIVE_EOM'); print(e.loc[['2025-03','2025-09','2025-12','2026-03','2026-06','2026-09']].to_string())
