from price import *
P=lambda s: pd.Period(s,'M')
def cohort(base, months_fwd=7):
    """Members billed in `base` month; follow billing & roster forward."""
    b = mmb[mmb.M==P(base)].copy()
    b = b.rename(columns={'AMT':'AMT0','P':'P0','S':'S0','PRICE':'PRICE0'})[['GCK','AMT0','P0','S0','PRICE0']]
    for k in range(1,months_fwd+1):
        m=P(base)+k
        x=mmb[mmb.M==m].set_index('GCK')
        b[f'AMT{k}']=b.GCK.map(x.AMT).fillna(0); b[f'PR{k}']=b.GCK.map(x.PRICE)
        r=roster[roster.M==m].set_index('GCK')
        b[f'ROS{k}']=b.GCK.isin(r.index)
    return b
c26=cohort('2026-02'); c25=cohort('2025-02')
# price change actually experienced: price in month +2 (April) vs base, for those billed both
for c in (c26,c25):
    c['D2']=c.PR2/c.PRICE0-1
def fam(p):
    p=p.lower()
    if 'student' in p: return 'Student'
    if 'found' in p or 'pre-opening' in p: return 'Founders / pre-opening'
    if 'private' in p: return 'Private memberships'
    if 'livestream' in p: return 'Livestream'
    if re.search(r'mighty monthly pass',p): return 'Mighty Monthly Pass (10)'
    if 'mini' in p: return 'Mini / 8 / 12 / 15 / 20 tiers'
    if re.search(r'monthly\s+\d+',p): return 'Mini / 8 / 12 / 15 / 20 tiers'
    return 'Other'
for c in (c26,c25): c['FAM']=c.P0.map(fam)
if __name__=='__main__':
    for nm,c in (('2026',c26),('2025',c25)):
        g=c.groupby('FAM').agg(n=('GCK','count'),rev0=('AMT0','sum'),med_price=('PRICE0','median'),med_d2=('D2','median'),pct_up=('D2',lambda v:(v>0.02).mean()),
            billed4=('AMT2','count'),ret7=('AMT7',lambda v:(v>0).mean()),ret67=('GCK','count'),rev7=('AMT7','sum'),ros7=('ROS7','mean'))
        g['ret67']=c.assign(a=(c.AMT6>0)|(c.AMT7>0)).groupby('FAM').a.mean(); g['revret']=g.rev7/g.rev0
        print(nm); print(g.round(3).to_string())
        print('ALL n',len(c),'ret7',(c.AMT7>0).mean().round(3),'ret6or7',((c.AMT6>0)|(c.AMT7>0)).mean().round(3),'ros7',c.ROS7.mean().round(3),'revret',(c.AMT7.sum()/c.AMT0.sum()).round(3))
    print(c26[c26.FAM=='Other'].P0.value_counts().head(10))
    print(c26.groupby(['FAM','P0']).agg(n=('GCK','count'),p=('PRICE0','median'),d=('D2','median')).query('n>=8').to_string())
