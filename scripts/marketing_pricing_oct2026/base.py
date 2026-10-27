import pandas as pd, numpy as np, json, re
pd.set_option("display.width", 330); pd.set_option("display.max_columns", 60); pd.set_option("display.max_rows", 500)
ASOF = pd.Timestamp('2026-10-08')
CODE = {'Berkeley':'BK','Culver City':'CC','Danville':'DN','Lafayette':'LF','Marin':'MR','Ocean Park':'OP','Presidio Heights':'PH',
        'Russian Hill':'RH','Santa Barbara':'SB','Santa Monica':'SM','West Portal':'WP','Westwood':'WW'}
REGION = {'BK':'East Bay','LF':'East Bay','DN':'East Bay','PH':'SF / Marin','RH':'SF / Marin','MR':'SF / Marin','WP':'SF / Marin',
          'SM':'LA','WW':'LA','OP':'LA','CC':'LA','SB':'Santa Barbara'}
sales = pd.read_pickle('sales.pkl')
sales['SALE_DATE']=pd.to_datetime(sales.SALE_DATE); sales['NET']=sales.NET.astype(float)
sales['S']=sales.STUDIO.str.replace('Mighty Pilates ','').map(CODE)
sales['M']=sales.SALE_DATE.dt.to_period('M')
clients=pd.read_pickle('clients.pkl'); clients['TRUE_FIRST_SALE_DATE']=pd.to_datetime(clients.TRUE_FIRST_SALE_DATE)
fv=pd.read_pickle('firstvisit.pkl')
for k in ['FIRST_VISIT','FIRST_CP_VISIT','FIRST_DIRECT_VISIT']: fv[k]=pd.to_datetime(fv[k])
vm=pd.read_pickle('visitmonth.pkl'); vm['M']=pd.to_datetime(vm.M).dt.to_period('M'); vm['VISITS']=vm.VISITS.astype(int); vm['CP_VISITS']=vm.CP_VISITS.astype(int)
# new client = first paid class/service purchase
po = sales[(sales.ITEM_TYPE=='Pricing Option')&(sales.NET>0)].sort_values(['GCK','SALE_DATE','IS_INTRO_OFFER','NET'],ascending=[True,True,False,False])
new = po.drop_duplicates('GCK').rename(columns={'SALE_DATE':'D0','S':'S0','PRODUCT_DESCRIPTION':'P0','IS_INTRO_OFFER':'INTRO0','NET':'NET0','REVENUE_CATEGORY':'CAT0','IS_AUTOPAY':'AP0'})[['GCK','D0','S0','P0','INTRO0','NET0','CAT0','AP0']]
new = new.merge(clients,on='GCK',how='left').merge(fv,on='GCK',how='left')
new = new[new.TRUE_FIRST_SALE_DATE>='2021-01-01'].copy()   # drop left-censored
new['M0']=new.D0.dt.to_period('M'); new['Q0']=new.D0.dt.to_period('Q')
new['CP_FIRST']=(new.FIRST_CP_VISIT.notna())&(new.FIRST_CP_VISIT<new.D0)
mk=json.load(open('mkt.json'))
def spend(acct='601001 Paid Ads'):
    rows=[]
    for t,d in mk.items():
        if t=='PL': continue
        for m,v in d.get(acct,{}).items(): rows.append((t,pd.Period(pd.to_datetime(m,format='%b %Y'),'M'),v))
    return pd.DataFrame(rows,columns=['S','M','SPEND'])
ADS=spend(); MKT=spend('Total 601000 Sales & Marketing')
