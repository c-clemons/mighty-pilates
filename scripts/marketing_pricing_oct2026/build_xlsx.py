from price4 import *
import json
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter as L
M=pd.read_pickle('model.pkl'); D=json.load(open('data.json')); new=pd.read_pickle('new.pkl'); rev=pd.read_pickle('rev.pkl')
NAME={v:k for k,v in CODE.items()}
ST=['MR','DN','PH','OP','BK','CC','RH','LF','SB','WW','SM']
F=lambda **k: Font(**{'name':'Arial','size':10,**k})
BLUE=F(color='0000FF'); BOLD=F(bold=True); HDR=F(bold=True,color='FFFFFF'); NOTE=F(italic=True,color='595959',size=9); TITLE=Font(name='Arial',size=13,bold=True)
HFILL=PatternFill('solid',fgColor='5C4A3A'); YEL=PatternFill('solid',fgColor='FFFF00'); LIGHT=PatternFill('solid',fgColor='F3EFE6')
thin=Side(style='thin',color='BFBFBF')
USD='$#,##0;($#,##0);-'; PCT='0.0%'; X='0.0"x"'; INT='#,##0;(#,##0);-'
wb=Workbook(); wb.remove(wb.active)
def sheet(name,title,sub=None):
    ws=wb.create_sheet(name); ws['A1']=title; ws['A1'].font=TITLE
    if sub: ws['A2']=sub; ws['A2'].font=NOTE
    ws.sheet_view.showGridLines=False; return ws
def header(ws,r,cols,c0=1):
    for i,h in enumerate(cols):
        c=ws.cell(r,c0+i,h); c.font=HDR; c.fill=HFILL; c.alignment=Alignment(wrap_text=True,vertical='bottom',horizontal='center' if i else 'left')
    ws.row_dimensions[r].height=30
def put(ws,r,c,v,fmt=None,font=None,fill=None):
    x=ws.cell(r,c,v); x.font=font or F()
    if fmt: x.number_format=fmt
    if fill: x.fill=fill
    return x
def widths(ws,w):
    for i,v in enumerate(w,1): ws.column_dimensions[L(i)].width=v

# ---------- Read me
ws=sheet('Read me','Mighty Pilates: marketing ROI and membership price increase, supporting data')
rows=[('Prepared','Empirica Analytics for Cat Martin, October 2026.'),
('Data through','Client, sales, visit and membership data: MindBody through 30 Sep 2026. Marketing spend: Crew Finance P&L packages (2025 full year; August 2026), through Aug 2026.'),
('New client','A person making their first-ever paid class or service purchase (MindBody pricing option), counted once across all studios and assigned to the studio of that purchase. People whose history predates 2021 are excluded.'),
('Value per client','Net sales collected from that client through MindBody in the N days after their first purchase, all products. Not recognized revenue; excludes ClassPass payouts.'),
('Marketing spend','P&L account 601000 Sales & Marketing (total), with 601001 Paid Ads shown separately. Head Office spend is included in totals but not in studio columns.'),
('Members','Month-end count of people with an active or suspended membership, including students and founders. A person with memberships at two studios counts once in the network total and once per studio in the studio table.'),
('Cost per new client (model)','Poisson regression of monthly new clients by studio, Jan 2023 to Sep 2026, with studio, month-of-year, studio launch stage, neighbouring openings and a January 2026 price-change step, plus a step at April 2026 when marketing was cut. See the Break model tab.'),
('Cost per new client (100% attribution)','All of the year-on-year drop in new clients (Apr-Sep 2026 vs Apr-Sep 2025) attributed to the drop in marketing spend (Apr-Aug).'),
('Colour key','Blue text: inputs you can change on the Scenarios tab. Black: formulas or source data.')]
for i,(k,v) in enumerate(rows,4):
    put(ws,i,1,k,font=BOLD); x=put(ws,i,2,v); x.alignment=Alignment(wrap_text=True,vertical='top'); ws.row_dimensions[i].height=45
put(ws,14,1,'Tabs',font=BOLD)
for i,(k,v) in enumerate([('Scenarios','$105K quarter and $2K-$5K per studio, live formulas'),('Marketing spend','Monthly sales & marketing and paid ads by studio'),('New clients','Monthly new clients by studio, 2023 onward'),('Q4 2025 by studio','What Q4 2025 new clients did, by studio'),('Value curves','Spend per new client by days since first purchase, Q4 groups'),('Break model','Actual vs expected new clients; model estimates'),('Members','Month-end members, sign-ups and cancellations'),('Price increase','Repriced-member retention and billing vs baseline')],15):
    put(ws,i,1,k); put(ws,i,2,v)
widths(ws,[30,110])

# ---------- Scenarios (formulas)
ws=sheet('Scenarios','Scenarios','Change the blue inputs; everything else recalculates.')
inp=[('Marketing per new client, model ($)',round(M['cac'],2),USD),('Marketing per new client, 100% attribution ($)',round(M['cac100'],2),USD),
('Value per new client, 90 days ($)',round(M['v90'],2),USD),('Value per new client, 180 days ($)',round(M['v180'],2),USD),('Value per new client, 9 months ($)',round(M['v270'],2),USD),
('Value per new client, 24 months, projected ($)',round(M['v24'],2),USD),('Current marketing pace, per quarter ($)',round(M['cur_q'],0),USD),('Q4 2026 marketing budget ($)',105000,USD),('New clients expected in Q4 2026 with no added spend',int(M['base_q']),INT)]
put(ws,4,1,'Inputs',font=BOLD)
for i,(k,v,f) in enumerate(inp,5):
    put(ws,i,1,k); put(ws,i,2,v,f,BLUE)
ws['C5']='Model estimate; see Break model tab'; ws['C6']='Year-on-year drop in new clients over drop in spend'; ws['C11']='Apr-Aug 2026 average x 3'; ws['C13']='Q3 2026 actual'
ws['C9']='9-month value x 1.735, the 24-month / 9-month ratio for clients who joined Oct 2022 - Sep 2024'
for c in ('C5','C6','C9','C11','C13'): ws[c].font=NOTE
r=15; put(ws,r,1,'Q4 2026 at the budget above',font=BOLD); header(ws,r+1,['','Model','Return','100% attribution','Return'])
put(ws,r+2,1,'Added marketing ($)'); 
for col in (2,4): put(ws,r+2,col,'=$B$12-$B$11',USD)
put(ws,r+3,1,'Additional new clients'); put(ws,r+3,2,'=B17/$B$5',INT); put(ws,r+3,4,'=D17/$B$6',INT)
put(ws,r+4,1,'Total new clients in Q4 2026'); put(ws,r+4,2,'=$B$13+B18',INT); put(ws,r+4,4,'=$B$13+D18',INT)
for i,(lab,ref) in enumerate([('Additional sales, 90 days','$B$7'),('Additional sales, 180 days','$B$8'),('Additional sales, 9 months','$B$9'),('Additional sales, 24 months (projected)','$B$10')]):
    rr=r+5+i; put(ws,rr,1,lab)
    put(ws,rr,2,f'=B18*{ref}',USD); put(ws,rr,3,f'=IF(B17=0,0,B{rr}/B17)',X)
    put(ws,rr,4,f'=D18*{ref}',USD); put(ws,rr,5,f'=IF(D17=0,0,D{rr}/D17)',X)
r=26; put(ws,r,1,'Monthly spend per studio (inputs)',font=BOLD)
lv=[2000,3000,4000,5000]
for i,v in enumerate(lv): put(ws,r,3+i,v,USD,BLUE)
header(ws,r+1,['Studio','Value per new client, 9 months']+[f'9-month value of one quarter at col {L(3+i)} spend' for i in range(4)]+['Return at 9 months','New clients per quarter at first spend level'])
for c in range(3,7): ws.cell(r+1,c).value=f'=TEXT({L(c)}${r},"$#,##0")&" a month"'
studios={s['code']:s for s in D['studios']}
for i,s in enumerate(ST):
    rr=r+2+i; put(ws,rr,1,NAME[s]); put(ws,rr,2,f"=INDEX('Q4 2025 by studio'!$G$5:$G$15,MATCH(A{rr},'Q4 2025 by studio'!$A$5:$A$15,0))",USD,F(color='008000'))
    for j in range(4): put(ws,rr,3+j,f'=3*{L(3+j)}${r}/$B$5*$B{rr}',USD)
    put(ws,rr,7,f'=$B{rr}/$B$5',X); put(ws,rr,8,f'=3*$C${r}/$B$5',INT)
rt=r+2+len(ST); put(ws,rt,1,'All 11 studios',font=BOLD); put(ws,rt,2,f'=AVERAGE(B{r+2}:B{rt-1})',USD,BOLD)
for j in range(4): put(ws,rt,3+j,f'=SUM({L(3+j)}{r+2}:{L(3+j)}{rt-1})',USD,BOLD)
put(ws,rt,7,f'=B{rt}/$B$5',X,BOLD); put(ws,rt,8,f'=SUM(H{r+2}:H{rt-1})',INT,BOLD)
put(ws,rt+1,1,'All 11 studios, 100% attribution'); put(ws,rt+1,2,f'=B{rt}',USD)
for j in range(4): put(ws,rt+1,3+j,f'={L(3+j)}{rt}*$B$5/$B$6',USD)
put(ws,rt+1,7,f'=B{rt+1}/$B$6',X); put(ws,rt+1,8,f'=H{rt}*$B$5/$B$6',INT)
put(ws,rt+3,1,'Assumes the same marketing cost per new client in every studio. Returns may fall at higher spend.',font=NOTE)
widths(ws,[44,16,18,18,18,18,14,16])

# ---------- Marketing spend
ws=sheet('Marketing spend','Sales and marketing spend by studio and month ($)','Source: Crew Finance P&L packages. 601000 total; 601001 paid ads below. HO = Head Office.')
mk=json.load(open('mkt.json'))
months=[m for m in pd.period_range('2025-01','2026-08',freq='M')]
cols=ST+['WP','HO']; names=[NAME.get(c,{'WP':'West Portal','HO':'Head Office'}.get(c)) for c in cols]
for blk,acct,r0 in (('Total sales & marketing (601000)','Total 601000 Sales & Marketing',4),('Paid ads (601001)','601001 Paid Ads',4+len(months)+5)):
    put(ws,r0,1,blk,font=BOLD); header(ws,r0+1,['Month']+names+['Total'])
    for i,m in enumerate(months):
        rr=r0+2+i; put(ws,rr,1,m.strftime('%b %Y'))
        for j,cd in enumerate(cols):
            v=mk.get(cd,{}).get(acct,{}).get(m.strftime('%b %Y'),0.0); put(ws,rr,2+j,round(v,2),USD)
        put(ws,rr,2+len(cols),f'=SUM(B{rr}:{L(1+len(cols))}{rr})',USD,BOLD)
widths(ws,[12]+[13]*(len(cols)+1)); ws.freeze_panes='B6'

# ---------- New clients
ws=sheet('New clients','New clients by studio and month','First paid class or service purchase, assigned to the studio of that purchase. West Portal omitted (19 in total).')
months=pd.period_range('2023-01','2026-09',freq='M'); cnt=new.groupby(['S0','M0']).size()
header(ws,4,['Month']+[NAME[s] for s in ST]+['Total'])
for i,m in enumerate(months):
    rr=5+i; put(ws,rr,1,m.strftime('%b %Y'))
    for j,s in enumerate(ST): put(ws,rr,2+j,int(cnt.get((s,m),0)),INT)
    put(ws,rr,2+len(ST),f'=SUM(B{rr}:{L(1+len(ST))}{rr})',INT,BOLD)
widths(ws,[12]+[13]*(len(ST)+1)); ws.freeze_panes='B5'

# ---------- Q4 2025 by studio
ws=sheet('Q4 2025 by studio','Clients who made their first purchase in Q4 2025, by studio','Marketing = total sales & marketing tagged to the studio in Oct-Dec 2025. Class fill = machine classes, signed in / capacity.')
q4=new[new.Q0=='2025Q4']
g=q4.groupby('S0').agg(n=('GCK','count'),intro=('INTRO0','mean'),r90=('R90','mean'),r180=('R180','mean'),rep90=('REPEAT90','mean'),a46=('ACT_M4_6','mean'),mem=('MEMBER180','mean'),r270=('R270','mean'))
header(ws,4,['Studio','Marketing Q4 2025 ($)','New clients','Started on a new client special','Bought again within 90 days','Active at 4-6 months','Value per client, 9 months ($)','Became members within 6 months','Value per client, 90 days ($)','Value per client, 180 days ($)','Class fill Q3 2026','Class fill Q4 2025'])
for i,s in enumerate(ST):
    rr=5+i; x=g.loc[s]; sd=studios[s]
    vals=[NAME[s],sd['mkt'],int(x.n),x.intro,x.rep90,x.a46,x.r270,x.mem,x.r90,x.r180,sd['fill']/100,(sd['fill']-sd['fill_chg'])/100]
    fm=[None,USD,INT,PCT,PCT,PCT,USD,PCT,USD,USD,'0%','0%']
    for j,(v,f) in enumerate(zip(vals,fm)): put(ws,rr,1+j,float(v) if isinstance(v,(np.floating,)) else v,f)
rr=16; put(ws,rr,1,'11 studios',font=BOLD); put(ws,rr,2,'=SUM(B5:B15)',USD,BOLD); put(ws,rr,3,'=SUM(C5:C15)',INT,BOLD)
for j,col in enumerate(['D','E','F','G','H','I','J'],4): put(ws,rr,j,f'=SUMPRODUCT({col}5:{col}15,$C$5:$C$15)/$C$16',PCT if col in 'DEFH' else USD,BOLD)
put(ws,18,1,'All new clients in Q4 2025 incl. West Portal: 1,964. Total Q4 2025 sales & marketing incl. Head Office and West Portal: $103,425.',font=NOTE)
widths(ws,[18,14,11,14,14,13,14,14,14,14,11,11])

# ---------- Value curves
ws=sheet('Value curves','Cumulative spend per new client, by days since first purchase ($)','Average across all new clients who joined in that quarter. Blank = not enough time has passed.')
days=[30,90,180,270,365,730,1095]; header(ws,4,['Joined']+[f'{d} days' for d in days]+['Clients'])
for i,qq in enumerate([p for p in pd.period_range('2022Q1','2026Q2',freq='Q')]):
    x=new[new.Q0==qq]; rr=5+i; put(ws,rr,1,str(qq).replace('Q',' Q'))
    end=qq.end_time
    for j,d in enumerate(days):
        if (pd.Timestamp('2026-09-30')-end).days>=d: put(ws,rr,2+j,float(x[f'R{d}'].mean()),USD)
    put(ws,rr,2+len(days),len(x),INT)
widths(ws,[12]+[11]*8)

# ---------- Break model
ws=sheet('Break model','New clients per month: actual vs model','Model fit before April 2026; expected without the cut from April. Sums of studio-level predictions.')
net=M['net']; header(ws,4,['Month','Actual new clients','Model fit','Expected without the cut','Difference (expected - actual)','Sales & marketing ($)'])
mkm=MKT.groupby('M').SPEND.sum()
for i,m in enumerate(net.index):
    rr=5+i; put(ws,rr,1,m.strftime('%b %Y')); put(ws,rr,2,int(net.y[m]),INT); put(ws,rr,3,round(float(net.fit[m]),1),'#,##0.0'); put(ws,rr,4,round(float(net.cf[m]),1),'#,##0.0')
    put(ws,rr,5,f'=D{rr}-C{rr}','#,##0.0'); 
    if m in mkm.index: put(ws,rr,6,round(float(mkm[m]),2),USD)
c0=8; put(ws,4,c0,'Model summary',font=BOLD)
summ=[('Drop in new clients after April 2026',M['pct'],PCT),('  95% range, smaller drop',M['pct_lo'],PCT),('  95% range, larger drop',M['pct_hi'],PCT),('New clients lost per month',M['lost'],'#,##0'),('  range, low',M['lost_lo'],'#,##0'),('  range, high',M['lost_hi'],'#,##0'),
('Sales & marketing per month, Apr 2025-Mar 2026',M['pre12'],USD),('Sales & marketing per month, Apr-Aug 2026',M['post_mk'],USD),('Drop in spend per month',M['dsp'],USD),('Marketing per lost new client',M['cac'],USD),('  range',f"${M['cac_lo']:,.0f} to ${M['cac_hi']:,.0f}",None),
('100% attribution: drop in new clients per month (Apr-Sep YoY)',M['yoy_drop'],'#,##0'),('100% attribution: drop in spend per month (Apr-Aug YoY)',M['dsp_yoy'],USD),('100% attribution: marketing per new client',M['cac100'],USD)]
for i,(k,v,f) in enumerate(summ,5): put(ws,i,c0,k); put(ws,i,c0+1,float(v) if not isinstance(v,str) else v,f)
put(ws,21,c0,'Sensitivity: same model with different controls',font=BOLD); header(ws,22,['Specification','Drop in new clients','95% low','95% high','Lost per month'],c0)
for i,sp in enumerate(M['specs']):
    rr=23+i; put(ws,rr,c0,sp['label']); put(ws,rr,c0+1,float(sp['pct']),PCT); put(ws,rr,c0+2,float(sp['ci_pct'][1]),PCT); put(ws,rr,c0+3,float(sp['ci_pct'][0]),PCT); put(ws,rr,c0+4,float(sp['lost_per_month']),'#,##0')
put(ws,30,c0,'Chosen specification: studio, month-of-year, launch stage, new studios nearby, January 2026 price step, April 2026 marketing step. Poisson, errors clustered by month.',font=NOTE)
widths(ws,[12,13,12,14,16,14,3,52,14,11,11,13])

# ---------- Members
ws=sheet('Members','Members, sign-ups and cancellations by month','Month-end. Members = active + suspended, people counted once across studios. Sign-ups and cancellations summed across studios (a move between studios can count in both).')
mp=pd.read_pickle('members_people.pkl').set_index('MONTH'); fl=pd.read_pickle('memflows.pkl')
header(ws,4,['Month','Members (active + suspended)','Active','Suspended','New members','Reactivated','Cancelled'])
for i,m in enumerate(mp.index):
    rr=5+i; put(ws,rr,1,pd.Period(m,'M').strftime('%b %Y')); put(ws,rr,2,f'=C{rr}+D{rr}',INT,BOLD); put(ws,rr,3,int(mp.loc[m,'ACTIVE_PEOPLE']),INT); put(ws,rr,4,int(mp.loc[m,'SUSPENDED_ONLY_PEOPLE']),INT)
    for j,col in enumerate(['NEW_MEMBERS','REACTIVATED','CHURNED']): put(ws,rr,5+j,int(fl.loc[m,col]),INT)
r0=5+len(mp)+2; put(ws,r0,1,'Members by studio, month-end (active + suspended)',font=BOLD)
mm=pd.read_pickle('mem.pkl'); mm['S']=mm.STUDIO.str.replace('Mighty Pilates ','').map(CODE)
for col in ['ACTIVE_EOM','SUSPENDED_EOM']: mm[col]=pd.to_numeric(mm[col])
mm['T']=mm.ACTIVE_EOM.fillna(0)+mm.SUSPENDED_EOM.fillna(0); pv=mm.pivot_table(index='MONTH',columns='S',values='T',aggfunc='sum').fillna(0)
header(ws,r0+1,['Month']+[NAME[s] for s in ST])
for i,m in enumerate([x for x in pv.index if x>='2025-01']):
    rr=r0+2+i; put(ws,rr,1,pd.Period(m,'M').strftime('%b %Y'))
    for j,s in enumerate(ST): put(ws,rr,2+j,int(pv.loc[m,s]) if s in pv.columns else 0,INT)
widths(ws,[12]+[13]*11)

# ---------- Price increase
ws=sheet('Price increase','April 2026 membership price increase','387 Mighty Monthly Pass members billed at the old price in Feb 2026, vs. the same pass in Feb 2025 (no increase), matched on tenure and price.')
put(ws,4,1,'Retention six to seven months later',font=BOLD); header(ws,5,['','Normal (2025, no increase)','Repriced (2026)','Difference'])
put(ws,6,1,'Share still paying'); put(ws,6,2,float(adj(t26,t25,lambda d:d.RET.mean())),PCT); put(ws,6,3,float(t26.RET.mean()),PCT); put(ws,6,4,'=C6-B6',PCT)
put(ws,7,1,'Members in the group'); put(ws,7,2,len(t26),INT); put(ws,7,3,len(t26),INT)
put(ws,8,1,'Members still paying'); put(ws,8,2,'=B6*B7',INT); put(ws,8,3,'=C6*C7',INT); put(ws,8,4,'=C8-B8',INT)
put(ws,10,1,'Monthly billings from the repriced members ($)',font=BOLD)
header(ws,11,['Month (2026)','Actual billings','Expected without increase','Gained from higher price','Lost to attrition above normal','Net','Cumulative net','Members billed','Expected billed'])
for i,x in rev.iterrows():
    rr=12+i; put(ws,rr,1,x.month); put(ws,rr,2,float(x.actual),USD); put(ws,rr,3,float(x.expected),USD); put(ws,rr,4,float(x.price_gain),USD); put(ws,rr,5,f'=F{rr}-D{rr}',USD); put(ws,rr,6,f'=B{rr}-C{rr}',USD)
    put(ws,rr,7,f'=SUM($F$12:F{rr})',USD); put(ws,rr,8,int(x.billed),INT); put(ws,rr,9,float(x.expected_billed),INT)
put(ws,18,1,'Apr-Sep',font=BOLD)
for c in 'BCDEF': put(ws,18,'BCDEF'.index(c)+2,f'=SUM({c}12:{c}17)',USD,BOLD)
put(ws,20,1,'Retention by tenure (share still paying six to seven months later)',font=BOLD); header(ws,21,['Tenure at Feb','Members (2026)','Repriced 2026','Same pass 2025, no increase','Difference'])
for i,tb in enumerate(['0-3m','3-6m','6-12m','12-24m','24m+']):
    rr=22+i; put(ws,rr,1,{'0-3m':'Under 3 months','3-6m':'3-6 months','6-12m':'6-12 months','12-24m':'1-2 years','24m+':'2+ years'}[tb]); put(ws,rr,2,int((t26.TB==tb).sum()),INT)
    put(ws,rr,3,float(t26[t26.TB==tb].RET.mean()),PCT); put(ws,rr,4,float(t25[t25.TB==tb].RET.mean()),PCT); put(ws,rr,5,f'=C{rr}-D{rr}',PCT)
put(ws,28,1,'Price changes',font=BOLD); header(ws,29,['When','What changed','Old','New'])
for i,row in enumerate([('Jan 2026','Drop-in class','$42','$47'),('Jan 2026','3 / 10 / 20 class packs','$117 / $370 / $670','$138 / $420 / $760'),('Jan 2026','Mighty Monthly Pass, new joins','$295 / $340','$330 / $360'),('Apr 2026','Mighty Monthly Pass, existing members, East Bay and LA','$295','$330'),('Apr 2026','Mighty Monthly Pass, existing members, SF and Marin','$340','$360'),('Mar-Apr 2026','8, 12, 15 and Mini passes','$180-400','$210-435'),('No change','Student and Founders passes','$160 / $245','$160 / $245')]):
    for j,v in enumerate(row): put(ws,30+i,1+j,v)
widths(ws,[44,18,18,18,18,14,14,12,12])
order=['Read me','Scenarios','Marketing spend','New clients','Q4 2025 by studio','Value curves','Break model','Members','Price increase']
wb._sheets=[wb[n] for n in order]
out='/Users/chandlerclemons/mighty-pilates/.claude/worktrees/infallible-mendeleev-a9f031/outputs/Mighty_Marketing_ROI_and_Pricing_data.xlsx'
wb.save(out); print(out, wb.sheetnames)
