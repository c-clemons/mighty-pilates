const fs=require('fs');
const {Document,Packer,Paragraph,TextRun,Table,TableRow,TableCell,ImageRun,HeadingLevel,AlignmentType,WidthType,BorderStyle,ShadingType,LevelFormat,Footer,PageNumber}=require('docx');
const D=JSON.parse(fs.readFileSync('../work/data.json','utf8'));
const CLAY='B5623F',INK='211D16',MUT='6B6456',RULE='D9CFBA',FILL='F3EFE6';
const W=9360; // content width, US Letter with 1" margins
const usd=v=>'$'+Math.round(v).toLocaleString('en-US');
// rich text: **bold** segments
const runs=(s,o={})=>s.split(/(\*\*[^*]+\*\*)/).filter(Boolean).map(t=>t.startsWith('**')?new TextRun({text:t.slice(2,-2),bold:true,...o}):new TextRun({text:t,...o}));
const P=(s,o={})=>new Paragraph({spacing:{after:140,line:300},children:runs(s),...o});
const H1=s=>new Paragraph({heading:HeadingLevel.HEADING_1,children:[new TextRun(s)]});
const H2=s=>new Paragraph({heading:HeadingLevel.HEADING_2,children:[new TextRun(s)]});
const LBL=s=>new Paragraph({pageBreakBefore:true,keepNext:true,spacing:{before:0,after:40},children:[new TextRun({text:s.toUpperCase(),size:16,color:CLAY,bold:true,characterSpacing:20})]});
const B=s=>new Paragraph({numbering:{reference:'bul',level:0},spacing:{after:100,line:300},children:runs(s)});
const CAP=s=>new Paragraph({spacing:{after:200},children:[new TextRun({text:s,size:18,color:MUT,italics:true})]});
const IMG=(f,h)=>new Paragraph({spacing:{before:80,after:60},children:[new ImageRun({type:'png',data:fs.readFileSync(f),transformation:{width:624,height:h}})]});
const bd=(c,sz)=>({style:BorderStyle.SINGLE,size:sz,color:c}), none={style:BorderStyle.NONE,size:0,color:'FFFFFF'};
function table(head,rows,widths,opts={}){
  const cell=(t,i,kind)=>new TableCell({width:{size:widths[i],type:WidthType.DXA},margins:{top:60,bottom:60,left:widths.length>8?50:80,right:widths.length>8?50:80},
    shading:kind==='head'?{type:ShadingType.CLEAR,fill:FILL,color:'auto'}:undefined,
    borders:{top:kind==='foot'?bd(INK,8):none,bottom:kind==='head'?bd(INK,8):bd(RULE,4),left:none,right:none},
    children:[new Paragraph({keepNext:kind!=='last'&&kind!=='foot',alignment:i===0||(opts.left||[]).includes(i)?AlignmentType.LEFT:AlignmentType.RIGHT,children:runs(String(t),{size:kind==='head'?(widths.length>8?14:16):(widths.length>8?17:19),bold:kind==='head'||kind==='foot'||undefined,color:kind==='head'?MUT:INK})})]});
  const tr=(r,kind)=>new TableRow({tableHeader:kind==='head',cantSplit:true,children:r.map((t,i)=>cell(t,i,kind))});
  return new Table({width:{size:W,type:WidthType.DXA},columnWidths:widths,rows:[tr(head,'head'),...rows.map((r,i)=>tr(r,i===rows.length-1?(opts.foot?'foot':'last'):'body'))]});
}
const gap=()=>new Paragraph({spacing:{after:120},children:[]});


const x1=v=>v.toFixed(1)+'x', R=v=>usd(Math.round(v/1000)*1000);
const SH=s=>new Paragraph({spacing:{before:160,after:60},children:[new TextRun({text:s.toUpperCase(),size:16,color:CLAY,bold:true,characterSpacing:20})]});
const S=D.studios;
const studioRows=S.map(r=>[r.name,usd(r.mkt),r.new,r.a46+'%',r.mem+'%',usd(r.v270),r.fill+'%',(r.fill_chg>0?'+':r.fill_chg<0?'−':'')+Math.abs(r.fill_chg)+' pts']);
studioRows.push(['11 studios',usd(S.reduce((a,r)=>a+r.mkt,0)),S.reduce((a,r)=>a+r.new,0).toLocaleString('en-US'),'28%','7%','$354','','']);
const q4=D.q4mk,n=D.q4n;
const roiRow=(lab,c)=>{const k=Math.min(q4/c,n);return [lab,Math.round(k).toLocaleString('en-US'),Math.round(k/n*100)+'%',usd(c),x1(D.v90/c),x1(D.v270/c),x1(D.v24/c)]};
const add=105000-D.cur_q;
const r105=[['Additional new clients',Math.round(add/D.cac).toLocaleString('en-US'),'',Math.round(add/D.cac100).toLocaleString('en-US'),''],
 ['Total new clients in Q4 2026',(Math.round((D.base_q+add/D.cac)/10)*10).toLocaleString('en-US'),'',(Math.round((D.base_q+add/D.cac100)/10)*10).toLocaleString('en-US'),'']];
[['Additional sales, 90 days',D.v90],['Additional sales, 180 days',D.v180],['Additional sales, 9 months',D.v270],['Additional sales, 24 months (projected)',D.v24]].forEach(([l,v])=>r105.push([l,R(add/D.cac*v),x1(v/D.cac),R(add/D.cac100*v),x1(v/D.cac100)]));
const lv=[2000,3000,4000,5000]; let tot=lv.map(()=>0);
const ps=S.map(r=>{const vals=lv.map(l=>3*l/D.cac*r.v270);vals.forEach((v,i)=>tot[i]+=v);return [r.name,usd(r.v270),...vals.map(v=>usd(Math.round(v/100)*100)),x1(r.v270/D.cac)]});
const avg=tot[0]/(3*2000*S.length/D.cac);
ps.push(['All 11 studios',usd(avg),...tot.map(v=>R(v)),x1(avg/D.cac)]);
ps.push(['All 11 studios, 100% attribution',usd(avg),...lv.map(l=>R(S.length*3*l/D.cac100*avg)),x1(avg/D.cac100)]);

const kids=[
  new Paragraph({spacing:{after:60},children:[new TextRun({text:'MIGHTY PILATES · PREPARED FOR CAT MARTIN · OCTOBER 2026',size:16,color:MUT,characterSpacing:20})]}),
  new Paragraph({spacing:{after:100},children:[new TextRun({text:'Marketing ROI and the membership price increase',size:44,bold:true,color:INK})]}),
  new Paragraph({spacing:{after:240},border:{bottom:bd(RULE,6)},children:[new TextRun({text:'Client, sales and membership data through 30 September 2026. Marketing spend from the P&L through August 2026.',color:MUT})]}),
  H1('Summary Analysis'),
  SH('Marketing'),
  B("**Q4 2025 marketing was $103,425 and 1,964 new clients arrived.** Each has spent $354 so far and should reach about $610 over two years."),
  B("**Marketing generated roughly half of Q4 2025's new clients.** The return on those new clients is about 1.9x in 90 days and 5.7x over two years. If the whole drop in new clients since the April cut is put down to marketing, it is two thirds, and 2.6x and 7.8x."),
  B("**$105,000 of marketing in Q4 2026 would bring about 770 more new clients.** They would spend about $272,000 within nine months, 3.3x the extra spend (1,050 clients and 4.5x on the 100% view)."),
  B("**Every studio returns at least 2x within nine months.** Marin, Danville and Presidio Heights return the most, because their new clients spend the most."),
  SH('Membership'),
  B("**Members fell from 887 in March to 728 in September.** That count includes students, founders and suspended members. New sign-ups halved while cancellations held steady."),
  B("**The April price increase cost about 35 members beyond normal attrition (9% of the 387 repriced) but raised their membership revenue by $16,900 (3.5%) over six months.** It has paid off so far, narrowly. Retention is the risk: 59% of repriced members were still paying six months later against a normal 68%, and by September the monthly effect had turned negative (−$9,400)."),

  LBL('Marketing'),
  H1('Sales and marketing ran $17–41K a month in 2025 and $6–10K a month since April 2026'),
  IMG('ads.png',251),
  CAP('Sales and marketing spend per month, all studios, from Crew Finance’s packages. September is not yet reported.'),
  H2('What Q4 2025 bought'),
  table(['Q4 2025 new clients','Result'],[['New clients (first paid class)','1,964'],['Bought again within 90 days','31%'],['Still active at 4–6 months','28%'],['Became members within 6 months','7%'],['Spent per client at 90 days / 9 months','$207 / $354'],['Projected per client at 24 months','about $610']],[6360,3000]),
  gap(),
  P('Clients who started on a new client special were worth $428 each over nine months, against $193 for everyone else.'),
  table(['Studio','Marketing Q4 2025','New clients Q4 2025','Active at 4–6 months','Became members','Value per client, 9 months','Class fill, Q3 2026','Fill change since Q4 2025'],studioRows,[1760,1160,1060,1060,1000,1160,1080,1080],{foot:true}),
  gap(),
  H2('What the April cut did to new clients'),
  IMG('brk.png',251),
  CAP('New clients per month, all studios. Before April the blue line is the model’s fit; from April it shows what the model expects had marketing continued.'),
  P('The model follows new clients at each studio every month from January 2023 to September 2026. It allows for the time of year, each studio’s opening surge, new studios opening nearby, and January’s list price increase, then measures the step change when marketing was cut in April 2026.'),
  P('New clients fell 30% below the expected level (likely range 21% to 39%), about 190 a month. Marketing fell by about $20,400 a month, so each lost new client corresponds to about $108 of marketing (likely range $74 to $181).'),
  P('If instead the whole year-on-year drop in new clients (231 a month) is put down to the cut, the figure is about $79 per new client. This is the 100% attribution view below.'),
  table(['Q4 2025, $103,425 of marketing','New clients credited','Share of new clients','Marketing per client','Return in 90 days','Return in 9 months','Return over 24 months'],[roiRow('**Model estimate**',D.cac),roiRow('100% of the drop attributed to the cut',D.cac100),roiRow('Every new client credited to marketing',q4/n)],[2760,1100,1100,1100,1100,1100,1100]),
  gap(),
  H2('Q4 2026 at $105,000'),
  P('Marketing is currently running at about $22,000 a quarter. Spending $105,000 in Q4 2026 adds about $83,000. Without it, expect about 1,300 new clients, in line with Q3.'),
  table(['Q4 2026, $105,000 of marketing','Model','Return','100% attribution','Return'],r105,[3560,1600,1000,2200,1000]),
  gap(),
  CAP('For scale, Q4 2025 spent $103,425 and brought 1,964 new clients in total. The model’s 2,060 is close to that. The 100% view’s 2,340 would be the best quarter yet, so treat it as the upper end.'),
  H2('Spending $2,000 to $5,000 a month per studio'),
  P('Each column is one quarter at that monthly spend, and what the new clients it brings spend in their first nine months. At the model’s $108 per new client, $2,000 a month brings about 56 new clients a quarter to a studio, and $5,000 a month about 139.'),
  table(['Studio','Value per new client, 9 months','$2K a month','$3K a month','$4K a month','$5K a month','Return at 9 months'],ps,[2560,1300,1100,1100,1100,1100,1100],{foot:false}),
  gap(),
  CAP('Uses the model’s $108 per new client in every studio, and each studio’s own nine-month value per new client. There is not enough data to measure how each studio responds separately, and returns may fall at higher spend.'),

  LBL('Membership'),
  H1('887 members in March, 728 in September'),
  table(['Membership','2025','2026'],[['Members at 31 March, incl. suspended','758','887'],['Members at 30 September, incl. suspended','847','728'],['New members, April–September','483','226'],['Cancellations, April–September','511','502'],['Monthly membership billings, September','$215,644','$203,906']],[5360,2000,2000]),
  gap(),
  P('Counts include students, founders and suspended members; 63 of the 728 were suspended at 30 September. Most of the decline is fewer sign-ups, not more cancellations, because there are fewer new clients to convert. The price increase explains about 35 of the 159 members lost.'),
  H2('The April price increase'),
  P('Existing members were repriced in April 2026: the Mighty Monthly Pass went from $295 to $330 in the East Bay and LA, and from $340 to $360 in SF and Marin. Student and Founders passes did not change. Drop-in, pack and new-member prices had already risen 12–18% in January.'),
  P('Some members leave every month whatever the price, so the measure is attrition above the normal rate. I followed the 387 members paying the old price in February 2026. The baseline is members on the same pass in February 2025, when there was no increase, matched on how long each had been a member and which price they paid.'),
  table(['Six to seven months later','Normal attrition (2025, no increase)','Repriced members (2026)','Difference'],[['Still paying','67.9%','58.9%','−9.0 pts'],['Left','32.1%','41.1%','+9.0 pts'],['Members still paying, of 387','263','228','−35']],[3360,2200,2000,1800]),
  gap(),
  table(['April–September 2026, repriced members vs. baseline','Amount'],[['Gained from the higher price','+$37,300'],['Lost to attrition above the normal rate','−$20,400'],['Net gain so far (3.5%)','+$16,900']],[6360,3000],{foot:true}),
  gap(),
  H2('Net effect on monthly billings from repriced members'),
  IMG('net.png',243),
  CAP('The price lift arrives in full in April. The extra cancellations build up after it.'),
  B('August and September together averaged a $4,500 monthly loss. At that pace the $16,900 gain is used up around January; at September’s pace, by November.'),
  B('Members of two years or more stayed at the same rate as before (70%). Members between three months and two years dropped 11 to 18 points against the baseline.'),
  new Paragraph({spacing:{before:360},border:{top:bd(RULE,6)},children:[new TextRun({text:'Client spend is net sales collected through MindBody, so it will not tie to recognized revenue. Marketing spend is total sales and marketing from Crew Finance’s 2025 and August 2026 packages. Q4 2026 figures are projections. Supporting data: Mighty_Marketing_ROI_and_Pricing_data.xlsx.',size:18,color:MUT})]}),
];

const doc=new Document({
  creator:'Chandler Clemons',title:'Marketing ROI and the membership price increase',
  styles:{default:{document:{run:{font:'Arial',size:21,color:INK}}},
    paragraphStyles:[
      {id:'Heading1',name:'Heading 1',basedOn:'Normal',next:'Normal',quickFormat:true,run:{font:'Arial',size:30,bold:true,color:INK},paragraph:{spacing:{before:120,after:160},keepNext:true,outlineLevel:0}},
      {id:'Heading2',name:'Heading 2',basedOn:'Normal',next:'Normal',quickFormat:true,run:{font:'Arial',size:22,bold:true,color:INK},paragraph:{spacing:{before:200,after:60},keepNext:true,outlineLevel:1}}]},
  numbering:{config:[{reference:'bul',levels:[{level:0,format:LevelFormat.BULLET,text:'•',alignment:AlignmentType.LEFT,style:{paragraph:{indent:{left:500,hanging:260}}}}]}]},
  sections:[{properties:{page:{size:{width:12240,height:15840},margin:{top:1300,bottom:1300,left:1440,right:1440}}},
    footers:{default:new Footer({children:[new Paragraph({alignment:AlignmentType.RIGHT,children:[new TextRun({text:'Empirica Analytics · ',size:16,color:MUT}),new TextRun({children:[PageNumber.CURRENT],size:16,color:MUT})]})]})},
    children:kids}]});
Packer.toBuffer(doc).then(b=>{fs.writeFileSync('Mighty_Marketing_ROI_and_Pricing_v4.docx',b);console.log('written',b.length)});
