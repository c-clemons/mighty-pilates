from price2 import *
firstap = ap[ap.NET>0].groupby('GCK').SALE_DATE.min()
def prep(c, base):
    c=c.copy(); c['TEN']=((pd.Timestamp(base+'-01')-c.GCK.map(firstap)).dt.days/30.4).clip(lower=0)
    c['TB']=pd.cut(c.TEN,[-1,3,6,12,24,999],labels=['0-3m','3-6m','6-12m','12-24m','24m+'])
    c['REG']=c.S0.map(REGION)
    def seg(r):
        if r.FAM=='Mighty Monthly Pass (10)' and r.P0=='Mighty Monthly Pass':
            p=round(r.PRICE0)
            if p==295: return 'MMP $295 -> $330 (+11.9%)'
            if p==340: return 'MMP $340 -> $360 (+5.9%)'
            if p in (330,360): return 'MMP already at new price'
            return 'MMP other price'
        if r.FAM=='Mini / 8 / 12 / 15 / 20 tiers' or 'Mini' in r.P0: return 'Other tiers (8/12/15/20/Mini)'
        if r.FAM in('Founders / pre-opening','Student'): return r.FAM+' (no increase)'
        return 'Other'
    c['SEG']=c.apply(seg,axis=1)
    for k in range(1,8): c[f'B{k}']=c[f'AMT{k}']>0
    c['RET']=c.B6|c.B7
    return c
c26=prep(c26,'2026-02'); c25=prep(c25,'2025-02')
if __name__=='__main__':
    for nm,c in (('2026',c26),('2025',c25)):
        g=c.groupby('SEG').agg(n=('GCK','count'),ten=('TEN','median'),rev0=('AMT0','sum'),**{f'b{k}':(f'B{k}','mean') for k in range(1,8)},ret=('RET','mean'),ros7=('ROS7','mean'),rev7=('AMT7','sum'))
        g['revret']=g.rev7/g.rev0; print(nm); print(g.round(3).to_string())
    # tenure-adjusted: MMP legacy 2026 vs MMP 2025 (all at 295/340 then)
    t26=c26[c26.SEG.str.startswith('MMP $')]; t25=c25[(c25.P0=='Mighty Monthly Pass')&(c25.PRICE0.round().isin([295,340]))]
    for lab,f in (('all',lambda d:d),('295',lambda d:d[d.PRICE0.round()==295]),('340',lambda d:d[d.PRICE0.round()==340])):
        a,b=f(t26),f(t25)
        w=a.TB.value_counts(normalize=True)
        tb=pd.DataFrame({'n26':a.groupby('TB',observed=False).size(),'n25':b.groupby('TB',observed=False).size(),'ret26':a.groupby('TB',observed=False).RET.mean(),'ret25':b.groupby('TB',observed=False).RET.mean(),
            'b7_26':a.groupby('TB',observed=False).B7.mean(),'b7_25':b.groupby('TB',observed=False).B7.mean(),'rr26':a.groupby('TB',observed=False).AMT7.sum()/a.groupby('TB',observed=False).AMT0.sum(),'rr25':b.groupby('TB',observed=False).AMT7.sum()/b.groupby('TB',observed=False).AMT0.sum()})
        print(lab, 'n',len(a),len(b)); print(tb.round(3).to_string())
        adj=lambda col:(tb[col]*w.reindex(tb.index)).sum()
        print('  raw ret26 %.3f ret25 %.3f | tenure-adj ret25 %.3f | b7: %.3f vs adj %.3f | revret %.3f vs adj %.3f'%(a.RET.mean(),b.RET.mean(),adj('ret25'),a.B7.mean(),adj('b7_25'),a.AMT7.sum()/a.AMT0.sum(),adj('rr25')))
    # downgrades among those still billed at month 7
    for nm,c in (('2026',t26),('2025',t25)):
        st=c[c.B7]; print(nm,'still billed',len(st),'paying less than base:',(st.AMT7<st.AMT0-1).mean().round(3),'more:',(st.AMT7>st.AMT0+1).mean().round(3),'avg amt7/amt0',(st.AMT7.sum()/st.AMT0.sum()).round(3))
    # by studio, treated
    g=t26.groupby('S0').agg(n=('GCK','count'),p=('PRICE0','median'),ret=('RET','mean'),rr=('AMT7','sum'),r0=('AMT0','sum')); g['rr']=g.rr/g.r0
    h=t25.groupby('S0').agg(n25=('GCK','count'),ret25=('RET','mean'),rr25=('AMT7','sum'),r025=('AMT0','sum')); h['rr25']=h.rr25/h.r025
    print(g.join(h).round(3).to_string())
    m=pd.read_pickle('mem.pkl'); 
    for col in m.columns[2:]: m[col]=pd.to_numeric(m[col])
    tt=m.groupby('MONTH').sum(numeric_only=True); tt['bom']=tt.ACTIVE_EOM.shift(1); tt['gross_churn']=tt.CHURNED/tt.bom; tt['net_churn']=(tt.CHURNED-tt.REACTIVATED)/tt.bom
    print(tt.loc['2025-01':'2026-09'].round(3).to_string())
