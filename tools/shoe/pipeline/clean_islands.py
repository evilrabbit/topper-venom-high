# Remove stray specks after border smoothing: any island of a part smaller than MINC faces joins its
# most common neighbouring part.   blender -b in.blend --python clean_islands.py -- OUT.blend
import bpy, numpy as np, sys, os
OUT = sys.argv[sys.argv.index('--') + 1]; MINC = int(os.environ.get('MINC', '400'))
objs = [o for o in bpy.data.objects if o.type == 'MESH']
for o in bpy.data.objects: o.select_set(False)
for o in objs: o.select_set(True)
bpy.context.view_layer.objects.active = objs[0]; bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active; me = obj.data
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT'); bpy.ops.mesh.remove_doubles(threshold=1e-6); bpy.ops.object.mode_set(mode='OBJECT')
F = len(me.polygons); lab = np.zeros(F, np.int32); me.polygons.foreach_get('material_index', lab)
lt = np.zeros(F, np.int32); me.polygons.foreach_get('loop_total', lt)
ei = np.zeros(len(me.loops), np.int32); me.loops.foreach_get('edge_index', ei)
fid = np.repeat(np.arange(F), lt); o = np.argsort(ei, kind='stable'); es = ei[o]; fs = fid[o]; same = es[1:] == es[:-1]
A = fs[:-1][same]; B = fs[1:][same]
def components(lab):
    m = lab[A] == lab[B]; a = A[m]; b = B[m]; par = np.arange(F)
    while True:
        pa = par[a]; pb = par[b]; lo = np.minimum(pa, pb)
        np.minimum.at(par, pa, lo); np.minimum.at(par, pb, lo)
        for _ in range(4): par = par[par]
        if (par[a] == par[b]).all(): break
    return np.unique(par, return_inverse=True)[1]
total = 0
for rnd in range(6):
    comp = components(lab); sz = np.bincount(comp)
    small = sz[comp] < MINC
    if not small.any(): break
    # for each small island: the most common label across its outer edges
    m = small[A] & (comp[A] != comp[B]); m2 = small[B] & (comp[A] != comp[B])
    ci = np.concatenate([comp[A[m]], comp[B[m2]]]); nl = np.concatenate([lab[B[m]], lab[A[m2]]])
    if not len(ci): break
    key = ci.astype(np.int64) * (lab.max() + 1) + nl
    uk, cnt = np.unique(key, return_counts=True)
    best = {}
    for k, c in zip(uk.tolist(), cnt.tolist()):
        cc, l = divmod(k, lab.max() + 1)
        if c > best.get(cc, (0, -1))[0]: best[cc] = (c, l)
    tgt = np.full(len(sz), -1); 
    for cc, (c, l) in best.items(): tgt[cc] = l
    ch = small & (tgt[comp] >= 0)
    lab[ch] = tgt[comp][ch]; total += int(ch.sum())
    print(f'round {rnd}: {int(len(np.unique(comp[small])))} islands, {int(ch.sum())} faces reassigned', flush=True)
print('total reassigned', total)
me.polygons.foreach_set('material_index', lab); me.update()
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT'); bpy.ops.mesh.separate(type='MATERIAL'); bpy.ops.object.mode_set(mode='OBJECT')
for ob in [x for x in bpy.data.objects if x.type == 'MESH']:
    used = {p.material_index for p in ob.data.polygons}; mt = ob.data.materials[next(iter(used))]
    ob.data.materials.clear(); ob.data.materials.append(mt)
    ob.data.polygons.foreach_set('material_index', np.zeros(len(ob.data.polygons), np.int32))
    ob.name = mt.name[5:]; ob.data.name = ob.name
print('parts', len([x for x in bpy.data.objects if x.type == 'MESH']))
bpy.ops.wm.save_as_mainfile(filepath=OUT); print('SAVED', OUT)
