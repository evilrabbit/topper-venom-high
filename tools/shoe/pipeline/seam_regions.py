# Geometry-only panel segmentation: watershed on fine-scale groove depth, so region borders are the scan's seams.
#   IT=8 SEED=0.0 MINSEED=600 blender -b shoe-navy.blend --python seam_regions.py -- OUT.npz
import bpy, numpy as np, heapq, sys, os, time
argv = sys.argv[sys.argv.index('--') + 1:]; OUT = argv[0]
IT = int(os.environ.get('IT', '8')); SEED = float(os.environ.get('SEED', '0.0')); MINSEED = int(os.environ.get('MINSEED', '600'))
t0 = time.time()
objs = [o for o in bpy.data.objects if o.type == 'MESH']
for o in bpy.data.objects: o.select_set(False)
for o in objs: o.select_set(True)
bpy.context.view_layer.objects.active = objs[0]; bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active; me = obj.data
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT'); bpy.ops.mesh.remove_doubles(threshold=1e-6); bpy.ops.object.mode_set(mode='OBJECT')
F = len(me.polygons); V = len(me.vertices)
old = np.zeros(F, np.int32); me.polygons.foreach_get('material_index', old)
ls = np.zeros(F, np.int32); me.polygons.foreach_get('loop_start', ls); lt = np.zeros(F, np.int32); me.polygons.foreach_get('loop_total', lt)
ei = np.zeros(len(me.loops), np.int32); me.loops.foreach_get('edge_index', ei)
fid = np.repeat(np.arange(F), lt); o = np.argsort(ei, kind='stable'); es = ei[o]; fs = fid[o]; same = es[1:] == es[:-1]
A = fs[:-1][same]; B = fs[1:][same]
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
print('fd pct', np.percentile(fd, [10, 30, 50, 70, 90, 97]).round(6).tolist())
seed = fd < SEED
m = seed[A] & seed[B]; a = A[m]; b = B[m]; par = np.arange(F)
while True:
    pa = par[a]; pb = par[b]; lo = np.minimum(pa, pb)
    np.minimum.at(par, pa, lo); np.minimum.at(par, pb, lo)
    for _ in range(4): par = par[par]
    if (par[a] == par[b]).all(): break
r = np.where(seed, par, -1)
u, inv = np.unique(r[r >= 0], return_inverse=True); lab = np.full(F, -1); lab[r >= 0] = inv
sz = np.bincount(inv); lab[(lab >= 0) & (sz[np.maximum(lab, 0)] < MINSEED)] = -1
u, inv = np.unique(lab[lab >= 0], return_inverse=True); l2 = np.full(F, -1); l2[lab >= 0] = inv; lab = l2
print('seeds', int(lab.max() + 1))
order = np.argsort(np.concatenate([A, B])); src = np.concatenate([A, B])[order]; dst = np.concatenate([B, A])[order]
st = np.searchsorted(src, np.arange(F + 1)).tolist(); dl = dst.tolist(); L = lab.tolist(); fdl = fd.tolist()
h = []
for f in np.nonzero(lab >= 0)[0].tolist():
    for j in range(st[f], st[f + 1]):
        g = dl[j]
        if L[g] < 0: h.append((fdl[g], g, L[f]))
heapq.heapify(h)
while h:
    v, f, l = heapq.heappop(h)
    if L[f] >= 0: continue
    L[f] = l
    for j in range(st[f], st[f + 1]):
        g = dl[j]
        if L[g] < 0: heapq.heappush(h, (fdl[g], g, l))
lab = np.array(L); lab[lab < 0] = 0
sz = np.bincount(lab)
print('regions', len(sz), 'sizes top', sorted(sz.tolist(), reverse=True)[:12], round(time.time() - t0, 1), 's')
np.savez(OUT, lab=lab, old=old, fd=fd, names=np.array([mt.name[5:] for mt in me.materials]))
# viz: random colour per region as a face colour attribute, then save a blend for rendering
rng = np.random.default_rng(3); pal = rng.uniform(0.25, 0.95, (len(sz), 3))
col = np.concatenate([pal[lab], np.ones((F, 1))], 1).astype(np.float32)
ca = me.color_attributes.new('seg', 'FLOAT_COLOR', 'CORNER'); ca.data.foreach_set('color', np.repeat(col, lt, axis=0).ravel()); me.color_attributes.active_color = ca
bpy.ops.wm.save_as_mainfile(filepath=OUT.replace('.npz', '.blend'))
