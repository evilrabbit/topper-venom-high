# Re-trace part boundaries onto the real seams of the scan (Blender 5, headless).
#   blender -b shoe-navy.blend --python retrace_parts.py -- OUT.blend
# 1) rejoin parts, 2) drop tiny stray islands, 3) erode every boundary by K face rings,
# 4) regrow all parts together with a priority flood on groove depth -> boundaries settle in the seams.
import bpy, numpy as np, heapq, sys, os, time
argv = sys.argv[sys.argv.index('--') + 1:]; OUT = argv[0]
K = int(os.environ.get('K', '4')); IT = int(os.environ.get('IT', '10')); MINC = int(os.environ.get('MINC', '150'))
FIX = {'outsole', 'midsole', 'sole_stripes'}
t0 = time.time()
objs = [o for o in bpy.data.objects if o.type == 'MESH']
for o in bpy.data.objects: o.select_set(False)
for o in objs: o.select_set(True)
bpy.context.view_layer.objects.active = objs[0]
bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active; me = obj.data
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.remove_doubles(threshold=1e-6); bpy.ops.object.mode_set(mode='OBJECT')
names = [m.name[5:] for m in me.materials]
F = len(me.polygons); V = len(me.vertices)
lab = np.zeros(F, np.int32); me.polygons.foreach_get('material_index', lab)
fix = np.isin(lab, [i for i, n in enumerate(names) if n in FIX])
# adjacency (faces sharing an edge)
ls = np.zeros(F, np.int32); me.polygons.foreach_get('loop_start', ls); lt = np.zeros(F, np.int32); me.polygons.foreach_get('loop_total', lt)
ei = np.zeros(len(me.loops), np.int32); me.loops.foreach_get('edge_index', ei)
fid = np.repeat(np.arange(F), lt); o = np.argsort(ei, kind='stable'); es = ei[o]; fs = fid[o]; same = es[1:] == es[:-1]
A = fs[:-1][same]; B = fs[1:][same]
order = np.argsort(np.concatenate([A, B])); src = np.concatenate([A, B])[order]; dst = np.concatenate([B, A])[order]
start = np.searchsorted(src, np.arange(F + 1))
# groove depth: Laplacian-smoothed position minus original, along the normal (positive in seams/grooves)
P = np.zeros(V * 3); me.vertices.foreach_get('co', P); P = P.reshape(V, 3)
N = np.zeros(V * 3); me.vertices.foreach_get('normal', N); N = N.reshape(V, 3)
E = np.zeros(len(me.edges) * 2, np.int64); me.edges.foreach_get('vertices', E); E = E.reshape(-1, 2)
deg = np.bincount(E.ravel(), minlength=V).astype(float); S = P.copy()
for _ in range(IT):
    acc = np.zeros_like(S)
    for k in range(3): acc[:, k] = np.bincount(E[:, 0], weights=S[E[:, 1], k], minlength=V) + np.bincount(E[:, 1], weights=S[E[:, 0], k], minlength=V)
    S = 0.5 * S + 0.5 * acc / np.maximum(deg, 1)[:, None]
d = ((S - P) * N).sum(1)
fv = np.zeros(len(me.loops), np.int64); me.loops.foreach_get('vertex_index', fv)
fd = np.add.reduceat(d[fv], ls) / lt
def components(lab):
    m = lab[A] == lab[B]; a = A[m]; b = B[m]; par = np.arange(F)
    while True:
        pa = par[a]; pb = par[b]; lo = np.minimum(pa, pb)
        np.minimum.at(par, pa, lo); np.minimum.at(par, pb, lo)
        for _ in range(4): par = par[par]
        if (par[a] == par[b]).all(): break
    return np.unique(par, return_inverse=True)[1]
before = lab.copy()
# 2) stray islands
comp = components(lab); sz = np.bincount(comp)
stray = (sz[comp] < MINC) & ~fix
lab[stray] = -1
print('stray faces', int(stray.sum()), 'in', int(len(np.unique(comp[stray]))), 'islands')
# 3) erode K rings around every boundary (fixed sole parts are never eroded)
bnd = np.zeros(F, bool); m = (lab[A] != lab[B]); bnd[A[m]] = True; bnd[B[m]] = True
band = bnd.copy()
for _ in range(K - 1):
    g = np.zeros(F, bool); g[A[band[B]]] = True; g[B[band[A]]] = True; band |= g
lab[band & ~fix] = -1
print('eroded faces', int((band & ~fix).sum()))
# 4) priority flood on groove depth (flat/convex first, grooves last)
L = lab.tolist(); fdl = fd.tolist(); st = start.tolist(); dl = dst.tolist(); fx = fix.tolist()
h = []
for f in np.nonzero(lab >= 0)[0].tolist():
    for j in range(st[f], st[f + 1]):
        g2 = dl[j]
        if L[g2] < 0: h.append((fdl[g2], g2, L[f]))
heapq.heapify(h)
while h:
    v, f, l = heapq.heappop(h)
    if L[f] >= 0: continue
    L[f] = l
    for j in range(st[f], st[f + 1]):
        g2 = dl[j]
        if L[g2] < 0 and not fx[g2]: heapq.heappush(h, (fdl[g2], g2, l))
lab = np.array(L)
print('unassigned after flood', int((lab < 0).sum()))
lab[lab < 0] = before[lab < 0]
# final pass: any island still under MINC joins its most common neighbour
comp = components(lab); sz = np.bincount(comp)
small = np.nonzero((sz[comp] < MINC) & ~fix)[0]
for _ in range(3):
    if not len(small): break
    cand = {}
    for f in small.tolist():
        for j in range(st[f], st[f + 1]):
            g2 = dl[j]
            if comp[g2] != comp[f]: cand.setdefault(comp[f], []).append(lab[g2])
    for c, ls_ in cand.items():
        lab[comp == c] = np.bincount(ls_).argmax()
    comp = components(lab); sz = np.bincount(comp); small = np.nonzero((sz[comp] < MINC) & ~fix)[0]
changed = lab != before
print('faces changed', int(changed.sum()), f'({changed.mean()*100:.1f}%)')
cnt0 = np.bincount(before, minlength=len(names)); cnt1 = np.bincount(lab, minlength=len(names))
for i, n in enumerate(names):
    if cnt0[i] != cnt1[i]: print(f'  {n:24s} {cnt0[i]:7d} -> {cnt1[i]:7d}')
me.polygons.foreach_set('material_index', lab.astype(np.int32)); me.update()
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT'); bpy.ops.mesh.separate(type='MATERIAL'); bpy.ops.object.mode_set(mode='OBJECT')
for ob in [x for x in bpy.data.objects if x.type == 'MESH']:
    used = {p.material_index for p in ob.data.polygons}
    if not used: bpy.data.objects.remove(ob); continue
    mt = ob.data.materials[next(iter(used))]
    ob.data.materials.clear(); ob.data.materials.append(mt)
    ob.data.polygons.foreach_set('material_index', np.zeros(len(ob.data.polygons), np.int32))
    ob.name = mt.name[5:]; ob.data.name = ob.name
bpy.ops.wm.save_as_mainfile(filepath=OUT)
print('SAVED', OUT, round(time.time() - t0, 1), 's')
