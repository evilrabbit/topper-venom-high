import bpy, bmesh, numpy as np
Z=np.load('/tmp/shoe-parts/band.npz'); gl=Z['gl']; bnd=Z['bnd']; y0=float(Z['y0']); y1=float(Z['y1']); NB=int(Z['NB']); NBA=int(Z['NBA'])
cx,cy,lx,ly=[float(Z[k]) for k in ('cx','cy','lx','ly')]
OFF=Z['off']; print('OFF',OFF)
def phi(P):
    P=np.asarray(P)-OFF; yb=(P[:,1]-y0)/(y1-y0)*NB-0.5
    i0=np.clip(np.floor(yb).astype(int),0,NB-1); i1=np.clip(i0+1,0,NB-1); t=np.clip(yb-np.floor(yb),0,1)
    g=gl[i0]*(1-t)+gl[i1]*t                      # interpolated ground line (no stair steps)
    ang=np.arctan2((P[:,1]-cy)/ly,(P[:,0]-cx)/lx); fa=(ang+np.pi)/(2*np.pi)*NBA-0.5
    a0=np.floor(fa).astype(int)%NBA; a1=(a0+1)%NBA; u=fa-np.floor(fa)
    b=bnd[a0]*(1-u)+bnd[a1]*u
    return (P[:,2]-g)-b
out=bpy.data.objects['outsole']; mid=bpy.data.objects['midsole']
mo=out.data.materials[0]; mm=mid.data.materials[0]
mid.data.materials.append(mo)                 # slot 1 = outsole
for o in bpy.data.objects: o.select_set(False)
out.select_set(True); mid.select_set(True); bpy.context.view_layer.objects.active=mid
bpy.ops.object.join()
me=mid.data
bm=bmesh.new(); bm.from_mesh(me)
for it in range(4):
    bm.faces.ensure_lookup_table()
    cen=np.array([f.calc_center_median() for f in bm.faces])
    pf=phi(cen)
    near=[f for f,p in zip(bm.faces,pf) if abs(p)<0.012]
    edges=set()
    for f in near:
        vs=[v.co for v in f.verts]
        pv=phi([tuple(v) for v in vs])
        if pv.min()<0<pv.max():               # face straddles the line
            for e in f.edges:
                if e.calc_length()>0.0015: edges.add(e)
    if not edges: break
    bmesh.ops.subdivide_edges(bm,edges=list(edges),cuts=1,use_grid_fill=True)
    print('REFINE',it,len(edges),len(bm.faces))
bm.faces.ensure_lookup_table()
cen=np.array([f.calc_center_median() for f in bm.faces]); pf=phi(cen)
for f,p in zip(bm.faces,pf): f.material_index=1 if p<0 else 0
# keep the true bottom (ground contact) in the outsole even where phi is odd
for f in bm.faces:
    if f.normal.z<-0.6 and f.material_index==0 and phi([tuple(f.calc_center_median())])[0]<0.01: f.material_index=1
bm.to_mesh(me); bm.free(); me.update()
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT'); bpy.ops.mesh.separate(type='MATERIAL'); bpy.ops.object.mode_set(mode='OBJECT')
for o in [o for o in bpy.data.objects if o.type=='MESH' and o.name.startswith('midsole')]:
    used={p.material_index for p in o.data.polygons}; m=o.data.materials[next(iter(used))]
    o.data.materials.clear(); o.data.materials.append(m); o.data.polygons.foreach_set('material_index',np.zeros(len(o.data.polygons),np.int32))
    nm='outsole' if m==mo else 'midsole'; o.name=nm; o.data.name=nm
    print('OBJ',o.name,len(o.data.polygons))
bpy.ops.wm.save_as_mainfile(filepath='/tmp/shoe-parts/parts_v3.blend'); print('SAVED')
