import bpy, numpy as np
def load(p):
    im=bpy.data.images.load(p); im.colorspace_settings.name='Non-Color'
    a=np.array(im.pixels[:],np.float32).reshape(im.size[1],im.size[0],im.channels)[...,:3]; return a,im.size
old,sz=load('/Users/evilrabbit/topper-venom/tools/shoe/navy-color.orig.webp')
new,_=load('/tmp/shoe-parts/navy-color-bake.png')
unb=new.max(2)<=2/255
# fill any remaining gaps by repeated dilation from baked pixels (never from the navy background)
out=new.copy(); filled=~unb
for _ in range(64):
    if filled.all(): break
    acc=np.zeros_like(out); cnt=np.zeros(out.shape[:2],np.float32)
    for dy,dx in ((1,0),(-1,0),(0,1),(0,-1)):
        f=np.roll(filled,(dy,dx),(0,1)); v=np.roll(out,(dy,dx),(0,1))
        acc+=v*f[...,None]; cnt+=f
    grow=(~filled)&(cnt>0)
    out[grow]=acc[grow]/cnt[grow][:,None]; filled|=grow
sat=old.max(2)-old.min(2)
red=(sat>0.18)&(old[...,0]>old[...,2]+30/255)
out[red]=old[red]
print('unbaked px',int(unb.sum()),'still empty',int((~filled).sum()),'red px',int(red.sum()))
im=bpy.data.images.new('comp',sz[0],sz[1],alpha=True,float_buffer=False); im.colorspace_settings.name='Non-Color'
im.pixels[:]=np.concatenate([out,np.ones(out.shape[:2]+(1,),np.float32)],2).ravel()
im.filepath_raw='/tmp/shoe-parts/navy-color-final.png'; im.file_format='PNG'; im.save(); print('WROTE')
