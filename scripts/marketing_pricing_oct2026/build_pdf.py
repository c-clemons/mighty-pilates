"""Make print HTML (light or dark) from the published page and print it with headless Chrome."""
import sys, base64, subprocess, os
here=os.path.dirname(os.path.abspath(__file__))
theme=sys.argv[1] if len(sys.argv)>1 else 'light'
page=open(os.path.join(here,'mighty-marketing-pricing.html')).read()
css=open('/Users/chandlerclemons/mighty-pilates/.claude/worktrees/infallible-mendeleev-a9f031/scripts/marketing_pricing_oct2026/print.css').read()
fonts=''  # web fonts load from Google; the spacing bug was tabular-nums leaking from table.pg, fixed in print.css
bg='#faf9f5' if theme=='light' else '#1c1915'
css=css.replace('html{background:#faf9f5}',f'html,body{{background:{bg}}}')
i=page.rindex('</section>'); j=page.index('</footer>')+len('</footer>')
page=page[:i]+page[i+len('</section>'):j]+'</section>'+page[j:]   # print: footnote travels with the last section
a='<div class="wrap">'; assert page.count(a)==1
page=page.replace(a,'<table class="pg"><thead><tr><td><div class="pgm"></div></td></tr></thead><tfoot><tr><td><div class="pgm"></div></td></tr></tfoot><tbody><tr><td>'+a)
i=page.index('<script>'); page=page[:i]+'</td></tr></tbody></table>\n'+page[i:]
html=f'<!doctype html><html data-theme="{theme}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{{margin:0}}</style></head><body>{page}<style>{fonts}{css}</style></body></html>'
src=os.path.join(here,f'print_{theme}.html'); open(src,'w').write(html)
out=os.path.join(here,f'out_{theme}.pdf')
subprocess.run(['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','--headless=new','--disable-gpu','--no-pdf-header-footer','--window-size=900,1200','--virtual-time-budget=15000',f'--print-to-pdf={out}','file://'+src],capture_output=True)
print(out)
