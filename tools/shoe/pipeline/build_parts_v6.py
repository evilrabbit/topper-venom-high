import bpy, numpy as np, json
G={
 'outsole':[64,81,82,83],'midsole':[63,80],'toe_bumper':[78],'sole_heel_insert':[30],
 'sole_window_front':[6,38],'sole_window_mid':[1,41],'sole_window_logo':[0,2,43],
 'sole_stripes':[3,4,28,29,31,37,40,42,60,61,62],
 'toe_cap':[65],'vamp':[68],'vamp_accent':[12],
 'forefoot_panel.R':[5],'forefoot_panel.L':[34],
 'side_frame.R':[7],'side_frame.L':[32],
 'side_triangle_top.R':[15],'side_triangle_top.L':[56],
 'side_triangle_upper.R':[14],'side_triangle_upper.L':[53],
 'side_triangle_lower.R':[9],'side_triangle_lower.L':[35],
 'side_triangle_front.R':[8],'side_triangle_front.L':[33],
 'heel_wedge':[13],'heel_overlay':[69],'heel_pull_tab':[84],
 'eyelets':[21,22,27,52,54,59],'laces':[66,67,75,76,77,79,86],
 'tongue':[20,71,73],'tongue_logo':[16,17,18,19,57,36],
 'collar':[70],'lining':[72,74,85],
}
names=list(G.keys())
obj=bpy.data.objects['shoe']; me=obj.data; F=len(me.polygons)
lab=np.load('/tmp/shoe-parts/lab_w1.npy'); L=np.load('/tmp/shoe-parts/faceL.npy'); col=np.load('/tmp/shoe-parts/facecol.npy')
g=np.full(F,-1)
for gi,nm in enumerate(names):
    for r in G[nm]: g[lab==r]=gi
# adjacency
ei=np.zeros(len(me.loops),np.int32); me.loops.foreach_get('edge_index',ei)
fid=np.repeat(np.arange(F),3); o=np.argsort(ei,kind='stable'); es=ei[o]; fs=fid[o]; same=es[1:]==es[:-1]
A=fs[:-1][same]; B=fs[1:][same]
def fill_unassigned():
    for _ in range(200):
        un=g<0
        if not un.any(): return
        cand=np.full(F,-1); m=un[A]&(g[B]>=0); cand[A[m]]=g[B[m]]; m=un[B]&(g[A]>=0); cand[B[m]]=g[A[m]]
        u=cand>=0
        if not u.any(): break
        g[u]=cand[u]
fill_unassigned()
print('unassigned after fill',int((g<0).sum()))
c=np.zeros(F*3); me.polygons.foreach_get('center',c); c=c.reshape(F,3)
un=np.nonzero(g<0)[0]
if len(un):
    from mathutils.kdtree import KDTree
    asg=np.nonzero(g>=0)[0]; kd=KDTree(len(asg))
    for j,f in enumerate(asg): kd.insert(c[f],j)
    kd.balance()
    for f in un: g[f]=g[asg[kd.find(c[f])[1]]]
print('unassigned final',int((g<0).sum()))
io,im=names.index('outsole'),names.index('midsole')
sole=(g==io)|(g==im)
si=np.nonzero(sole)[0]
nrm=np.zeros(F*3); me.polygons.foreach_get('normal',nrm); nrm=nrm.reshape(F,3)
BAND=float(__import__('os').environ.get('BAND','0.03'))
ys=c[si,1]; y0,y1=ys.min(),ys.max(); NB=120
bi=np.clip(((ys-y0)/(y1-y0)*NB).astype(int),0,NB-1)
gl=np.full(NB,np.inf); np.minimum.at(gl,bi,c[si,2])
idx=np.arange(NB); ok=np.isfinite(gl); gl=np.interp(idx,idx[ok],gl[ok])
# lower envelope smoothing: running min then box smooth
k=4; gl=np.array([gl[max(0,i-k):i+k+1].min() for i in range(NB)])
for _ in range(3): gl=np.convolve(np.pad(gl,6,mode='edge'),np.ones(13)/13,mode='valid')
# --- band = two-seed watershed on groove depth: outsole grows up from the ground, midsole down from above,
#     they meet in the molded outsole/midsole groove, so the edge follows the sole's own baseline line
import heapq, os
ist=names.index('sole_stripes')
region=sole|(g==ist)
fd=np.load('/tmp/shoe-parts/fd.npy')
LO=float(os.environ.get('LO','0.012')); HI=float(os.environ.get('HI','0.065'))
ri=np.nonzero(region)[0]
rb=np.clip(((c[ri,1]-y0)/(y1-y0)*NB).astype(int),0,NB-1)
h_above=c[ri,2]-gl[rb]
lab2=np.full(F,-1)
lab2[ri[h_above<LO]]=1      # outsole seed
lab2[ri[h_above>HI]]=0      # midsole seed
order=np.argsort(np.concatenate([A,B])); src=np.concatenate([A,B])[order]; dst=np.concatenate([B,A])[order]
start=np.searchsorted(src,np.arange(F+1)).tolist(); dstl=dst.tolist()
reg=region.tolist(); fdl=fd.tolist(); L2=lab2.tolist()
hq=[]
for f in np.nonzero(lab2>=0)[0].tolist():
    for j in range(start[f],start[f+1]):
        k=dstl[j]
        if reg[k] and L2[k]<0: hq.append((fdl[k],k,L2[f]))
heapq.heapify(hq)
while hq:
    v,k,l=heapq.heappop(hq)
    if L2[k]>=0: continue
    L2[k]=l
    for j in range(start[k],start[k+1]):
        m=dstl[j]
        if reg[m] and L2[m]<0: heapq.heappush(hq,(fdl[m],m,l))
lab2=np.array(L2)
# --- regularise: boundary height as a function of angle around the sole outline, de-spiked
hab=np.full(F,np.nan); hab[ri]=h_above
isO=(lab2==1); isM=(lab2==0)
nbM=np.zeros(F,bool); m=isO[A]&isM[B]; nbM[A[m]]=True; m=isO[B]&isM[A]; nbM[B[m]]=True
cx,cy=c[ri,0].mean(),c[ri,1].mean(); lx=np.ptp(c[ri,0])/2; ly=np.ptp(c[ri,1])/2
ang=np.arctan2((c[:,1]-cy)/ly,(c[:,0]-cx)/lx)
NBA=int(os.environ.get('NBA','240'))
ab=np.clip(((ang+np.pi)/(2*np.pi)*NBA).astype(int),0,NBA-1)
itf=np.nonzero(nbM&region&(nrm[:,2]>-0.5))[0]
bnd=np.full(NBA,np.nan)
for i in range(NBA):
    v=hab[itf[ab[itf]==i]]
    if len(v)>=3: bnd[i]=np.percentile(v,float(os.environ.get('PCT','50')))
ok=~np.isnan(bnd); idx=np.arange(NBA)
bnd=np.interp(idx,idx[ok],bnd[ok],period=NBA)
MW=int(os.environ.get('MW','15'))
bnd=np.array([np.median(np.take(bnd,range(i-MW//2,i+MW//2+1),mode='wrap')) for i in range(NBA)])
for _ in range(2): bnd=np.array([np.mean(np.take(bnd,range(i-3,i+4),mode='wrap')) for i in range(NBA)])
# --- rib zones (heel under the TOPPER plate, midfoot under the window): navy fills the recesses up to the rib tops
st=np.nonzero(g==ist)[0]
abs_=np.clip((((np.arctan2((c[st,1]-cy)/ly,(c[st,0]-cx)/lx))+np.pi)/(2*np.pi)*NBA).astype(int),0,NBA-1)
sb=np.clip(((c[st,1]-y0)/(y1-y0)*NB).astype(int),0,NB-1); sh=c[st,2]-gl[sb]
ceil_=np.full(NBA,np.nan)
for i in np.unique(abs_):
    v=sh[abs_==i]
    if len(v)>=5: ceil_[i]=np.percentile(v,95)
has=~np.isnan(ceil_)
GAP=int(os.environ.get('RGAP','8')); EXT=int(os.environ.get('REXT','2')); RM=float(os.environ.get('RMARGIN','0.004'))
# close gaps between ribs and extend a little past the outer ribs (circular)
zone=has.copy()
idx=np.nonzero(has)[0]
for a_,b_ in zip(idx,np.roll(idx,-1)):
    d_=(b_-a_)%NBA
    if 0<d_<=GAP: zone[[ (a_+k)%NBA for k in range(d_+1)]]=True
for i in np.nonzero(zone.copy())[0]:
    for k in range(-EXT,EXT+1): zone[(i+k)%NBA]=True
cz=ceil_.copy(); ok2=~np.isnan(cz)
cz=np.interp(np.arange(NBA),np.nonzero(ok2)[0],cz[ok2],period=NBA)
# cap below the white parts sitting above the ribs (window frames / TOPPER plate keep a white lip)
capn=[names.index(n_) for n_ in ('sole_window_front','sole_window_mid','sole_heel_insert','sole_window_logo')]
cf_=np.nonzero(np.isin(g,capn))[0]
ab2=np.clip((((np.arctan2((c[cf_,1]-cy)/ly,(c[cf_,0]-cx)/lx))+np.pi)/(2*np.pi)*NBA).astype(int),0,NBA-1)
cb2=np.clip(((c[cf_,1]-y0)/(y1-y0)*NB).astype(int),0,NB-1); ch2=c[cf_,2]-gl[cb2]
cap=np.full(NBA,np.inf)
np.minimum.at(cap,ab2,ch2)
LIP=float(os.environ.get('LIP','0.008'))
cz=np.minimum(cz,cap-LIP)
RIBCEIL=np.where(zone,cz-RM,-np.inf)
for i in range(NBA):
    pass
runs=[];cur=None
for i in range(NBA):
    if zone[i] and cur is None: cur=[i,i]
    elif zone[i]: cur[1]=i
    elif cur: runs.append(tuple(cur)); cur=None
if cur: runs.append(tuple(cur))
print('RIB runs',[(a_,b_,round(float(np.max(RIBCEIL[a_:b_+1])),3)) for a_,b_ in runs])
print('RIB bins',int(zone.sum()),'ceil range',round(float(np.nanmin(ceil_)),4),round(float(np.nanmax(ceil_)),4))
print('BND min/med/max',round(bnd.min(),4),round(float(np.median(bnd)),4),round(bnd.max(),4))
bnd=np.maximum(bnd,RIBCEIL)
# sample the boundary with linear interpolation between bins for a smooth edge
fa=(ang+np.pi)/(2*np.pi)*NBA-0.5; i0=np.floor(fa).astype(int)%NBA; i1=(i0+1)%NBA; t=fa-np.floor(fa)
bf=bnd[i0]*(1-t)+bnd[i1]*t
newo=np.zeros(F,bool); newo[ri]=h_above<bf[ri]
newo&=(g!=ist)
np.savez('/tmp/shoe-parts/band.npz',off=np.array(obj.matrix_world.translation),gl=gl,bnd=bnd,y0=y0,y1=y1,NB=NB,NBA=NBA,cx=cx,cy=cy,lx=lx,ly=ly)
allb=np.clip(((c[:,1]-y0)/(y1-y0)*NB).astype(int),0,NB-1); hall=c[:,2]-gl[allb]
inband=(hall<bf)&(np.abs(c[:,0]-cx)<lx*1.2)
for gi_,nm_ in enumerate(names):
    k_=int((inband&(g==gi_)&~region).sum())
    if k_: print('INBAND_OTHER',nm_,k_)
print('WS outsole',int(newo.sum()),'unl',int((region&(lab2<0)).sum()))
keep83=np.zeros(F,bool)
g[sole]=im; g[newo|keep83]=io
# smooth sole boundary (majority vote among outsole/midsole)
for _ in range(int(__import__('os').environ.get('SMOOTH','4'))):
    isO=(g==io).astype(float); s=np.bincount(A,weights=isO[B],minlength=F)+np.bincount(B,weights=isO[A],minlength=F)
    d=np.bincount(A,minlength=F)+np.bincount(B,minlength=F); fr=s/np.maximum(d,1)
    sole=(g==io)|(g==im); g[sole&(fr>0.5)]=io; g[sole&(fr<0.5)]=im
cnt=np.bincount(g,minlength=len(names))
for nm,k in zip(names,cnt): print('PART',nm,int(k))
# materials
base=me.materials[0]
nt0=base.node_tree
bsdf=[n for n in nt0.nodes if n.type=='BSDF_PRINCIPLED'][0]
lk=bsdf.inputs['Base Color'].links
print('BASE LINK', lk[0].from_node.type if lk else None, [ (l.from_node.type,l.to_socket.name) for l in nt0.links])
# node group: tint keeping scan detail
ng=bpy.data.node_groups.new('ShoePartColor','ShaderNodeTree')
ng.interface.new_socket('Texture',in_out='INPUT',socket_type='NodeSocketColor')
s=ng.interface.new_socket('Color',in_out='INPUT',socket_type='NodeSocketColor')
s=ng.interface.new_socket('Detail',in_out='INPUT',socket_type='NodeSocketFloat'); s.default_value=0.7; s.min_value=0; s.max_value=1
s=ng.interface.new_socket('Texture Mean',in_out='INPUT',socket_type='NodeSocketFloat'); s.default_value=0.5
s=ng.interface.new_socket('Original',in_out='INPUT',socket_type='NodeSocketFloat'); s.default_value=0.0; s.min_value=0; s.max_value=1
s=ng.interface.new_socket('Ink Color',in_out='INPUT',socket_type='NodeSocketColor'); s.default_value=(0.004,0.004,0.004,1)
s=ng.interface.new_socket('Ink Threshold',in_out='INPUT',socket_type='NodeSocketFloat'); s.default_value=0.0; s.min_value=0; s.max_value=1
ng.interface.new_socket('Base Color',in_out='OUTPUT',socket_type='NodeSocketColor')
N=ng.nodes; Lk=ng.links
gi=N.new('NodeGroupInput'); go=N.new('NodeGroupOutput')
bw=N.new('ShaderNodeRGBToBW'); Lk.new(gi.outputs['Texture'],bw.inputs[0])
mx=N.new('ShaderNodeMath'); mx.operation='MAXIMUM'; mx.inputs[1].default_value=0.004; Lk.new(gi.outputs['Texture Mean'],mx.inputs[0])
dv=N.new('ShaderNodeMath'); dv.operation='DIVIDE'; Lk.new(bw.outputs[0],dv.inputs[0]); Lk.new(mx.outputs[0],dv.inputs[1])
cl=N.new('ShaderNodeClamp'); cl.inputs['Min'].default_value=0.35; cl.inputs['Max'].default_value=1.6; Lk.new(dv.outputs[0],cl.inputs['Value'])
lp=N.new('ShaderNodeMix'); lp.data_type='FLOAT'; lp.inputs['A'].default_value=1.0
Lk.new(gi.outputs['Detail'],lp.inputs['Factor']); Lk.new(cl.outputs[0],lp.inputs['B'])
mul=N.new('ShaderNodeMix'); mul.data_type='RGBA'; mul.blend_type='MULTIPLY'; mul.inputs['Factor'].default_value=1.0
Lk.new(gi.outputs['Color'],mul.inputs[6]); Lk.new(lp.outputs[0],mul.inputs[7])
og=N.new('ShaderNodeMix'); og.data_type='RGBA'; Lk.new(gi.outputs['Original'],og.inputs['Factor']); Lk.new(mul.outputs[2],og.inputs[6]); Lk.new(gi.outputs['Texture'],og.inputs[7])
# ink: where texture is much darker than the part mean -> ink colour
lo=N.new('ShaderNodeMath'); lo.operation='SUBTRACT'; Lk.new(gi.outputs['Ink Threshold'],lo.inputs[0]); lo.inputs[1].default_value=0.08
mr=N.new('ShaderNodeMapRange'); Lk.new(dv.outputs[0],mr.inputs['Value']); Lk.new(lo.outputs[0],mr.inputs['From Min']); Lk.new(gi.outputs['Ink Threshold'],mr.inputs['From Max'])
mr.inputs['To Min'].default_value=1.0; mr.inputs['To Max'].default_value=0.0
gt=N.new('ShaderNodeMath'); gt.operation='GREATER_THAN'; gt.inputs[1].default_value=0.0; Lk.new(gi.outputs['Ink Threshold'],gt.inputs[0])
mf=N.new('ShaderNodeMath'); mf.operation='MULTIPLY'; Lk.new(mr.outputs[0],mf.inputs[0]); Lk.new(gt.outputs[0],mf.inputs[1])
ink=N.new('ShaderNodeMix'); ink.data_type='RGBA'; Lk.new(mf.outputs[0],ink.inputs['Factor']); Lk.new(og.outputs[2],ink.inputs[6]); Lk.new(gi.outputs['Ink Color'],ink.inputs[7])
Lk.new(ink.outputs[2],go.inputs['Base Color'])
mats=[]
for i,nm in enumerate(names):
    m=base.copy(); m.name=f'shoe_{nm}'
    nt=m.node_tree; b=[n for n in nt.nodes if n.type=='BSDF_PRINCIPLED'][0]
    l=b.inputs['Base Color'].links[0]; tex_out=l.from_socket; nt.links.remove(l)
    grp=nt.nodes.new('ShaderNodeGroup'); grp.node_tree=ng; grp.label='PART COLOR'; grp.location=(b.location.x-250,b.location.y+200)
    sel=g==i
    mean=col[sel].mean(0) if sel.any() else np.array([.5,.5,.5])
    grp.inputs['Color'].default_value=(*[float(v) for v in mean],1)
    grp.inputs['Texture Mean'].default_value=float(L[sel].mean()) if sel.any() else 0.5
    nt.links.new(tex_out,grp.inputs['Texture']); nt.links.new(grp.outputs['Base Color'],b.inputs['Base Color'])
    m.diffuse_color=(*[float(v) for v in mean],1)
    mats.append(m)
me.materials.clear()
for m in mats: me.materials.append(m)
me.polygons.foreach_set('material_index',g.astype(np.int32)); me.update()
# apply transform, separate by material
bpy.context.view_layer.objects.active=obj; obj.select_set(True)
bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT'); bpy.ops.mesh.separate(type='MATERIAL'); bpy.ops.object.mode_set(mode='OBJECT')
coll=bpy.data.collections.new('Topper Shoe'); bpy.context.scene.collection.children.link(coll)
root=bpy.data.objects.new('TopperShoe',None); coll.objects.link(root)
parts=[o for o in bpy.data.objects if o.type=='MESH']
for o in parts:
    # drop unused material slots
    used=set(p.material_index for p in o.data.polygons)
    mname=o.data.materials[next(iter(used))].name
    o.data.materials.clear(); o.data.materials.append(bpy.data.materials[mname])
    for p in o.data.polygons: pass
    o.data.polygons.foreach_set('material_index',np.zeros(len(o.data.polygons),np.int32))
    nm=mname[len('shoe_'):]; o.name=nm; o.data.name=nm
    for cc in o.users_collection: cc.objects.unlink(o)
    coll.objects.link(o); o.parent=root
    bpy.context.view_layer.objects.active=o
bpy.data.materials.remove(base) if base.users==0 else None
for o in bpy.data.objects:
    if o.type=='CAMERA': bpy.data.objects.remove(o)
bpy.ops.outliner.orphans_purge(do_recursive=True) if hasattr(bpy.ops.outliner,'orphans_purge') else None
print('OBJECTS',len(parts),sorted(o.name for o in parts))
bpy.ops.wm.save_as_mainfile(filepath='/tmp/shoe-parts/parts_v2.blend')
print('SAVED')
