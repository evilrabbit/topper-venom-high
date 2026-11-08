import sys
from PIL import Image
tag=sys.argv[1]; out=[]
for k in ['side','other']:
    a=Image.open(f'/tmp/shoe-parts/{tag}_{k}.png').convert('RGB'); L=a.convert('L'); bg=L.getpixel((5,5))
    x0,y0,x1,y1=Image.eval(L,lambda v:255 if abs(v-bg)>6 else 0).getbbox(); h=y1-y0
    out.append(a.crop((x0-10,y0+int(h*0.55),x1+10,y1+10)))
W=max(o.width for o in out); H=sum(o.height for o in out)
t=Image.new('RGB',(W,H),'white'); yy=0
for o in out: t.paste(o,(0,yy)); yy+=o.height
t.resize((int(W*1.6),int(H*1.6))).save(f'/tmp/shoe-parts/{tag}_sole.png')
