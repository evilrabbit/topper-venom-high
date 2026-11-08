# Feather part borders: bake, per vertex, a smooth 0..1 mask that is 0.5 exactly on the (stair-stepped)
# part border and reaches 0/1 ~1mm either side; plus the neighbour part's colour. Materials then blend
# their colour with the neighbour's across that band -> smooth anti-aliased borders without remeshing.
#   blender -b shoe-original.blend --python border_feather.py -- OUT.blend
import bpy, numpy as np, sys, os
from mathutils.kdtree import KDTree
OUT = sys.argv[sys.argv.index('--') + 1]; FEATHER = float(os.environ.get('FEATHER', '0.0012'))   # metres (shoe ~0.31 long)
objs = [o for o in bpy.data.objects if o.type == 'MESH']
# gather all border vertices (vertices shared by faces of two different parts) via a joined copy
import bmesh
allv = []; alllab = []; base = 0; part_index = {o.name: i for i, o in enumerate(objs)}
for o in objs:
    me = o.data; V = len(me.vertices)
    co = np.zeros(V * 3); me.vertices.foreach_get('co', co); allv.append(co.reshape(V, 3)); alllab.append(np.full(V, part_index[o.name]))
P = np.concatenate(allv); LAB = np.concatenate(alllab)
# border = a vertex position that appears in two parts (parts were separated along shared edges, so borders are duplicated verts)
key = np.round(P / 1e-6).astype(np.int64)
_, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
shared = cnt[inv] > 1
# per shared position: the set of part labels
from collections import defaultdict
labs_at = defaultdict(set)
for i in np.nonzero(shared)[0]: labs_at[inv[i]].add(int(LAB[i]))
bpos = np.array([P[i] for i in np.nonzero(shared)[0]])
blab = [labs_at[inv[i]] for i in np.nonzero(shared)[0]]
kd = KDTree(len(bpos))
for i, p in enumerate(bpos): kd.insert(p, i)
kd.balance()
print('border vertices', len(bpos))
colors = {}
for o in objs:
    m = o.data.materials[0]; g = [n for n in m.node_tree.nodes if n.type == 'GROUP'][0]
    colors[part_index[o.name]] = tuple(g.inputs['Color'].default_value)[:3]
for o in objs:
    me = o.data; V = len(me.vertices); me_i = part_index[o.name]
    co = np.zeros(V * 3); me.vertices.foreach_get('co', co); co = co.reshape(V, 3)
    mask = np.ones(V, np.float32); ncol = np.tile(np.array(colors[me_i], np.float32), (V, 1))
    for vi in range(V):
        hits = kd.find_range(co[vi], FEATHER * 2.2)
        if not hits: continue
        # nearest border vertex that borders a *different* part
        best = None
        for _, bi, d in sorted(hits, key=lambda h: h[2]):
            others = blab[bi] - {me_i}
            if others: best = (d, next(iter(others))); break
        if best is None: continue
        d, other = best
        # signed: inside own part the distance is positive; mask 0.5 at the border, 1 at >= FEATHER inside
        t = np.clip(0.5 + 0.5 * d / FEATHER, 0.5, 1.0)
        mask[vi] = t; ncol[vi] = colors[other]
    # border verts themselves (shared) sit exactly on the line => 0.5
    attr = me.attributes.get('border_mask') or me.attributes.new('border_mask', 'FLOAT', 'POINT'); attr.data.foreach_set('value', mask)
    cattr = me.attributes.get('neighbour_color') or me.attributes.new('neighbour_color', 'FLOAT_COLOR', 'POINT')
    cattr.data.foreach_set('color', np.concatenate([ncol, np.ones((V, 1), np.float32)], 1).ravel())
    print(f'  {o.name:16s} feathered {int((mask < 1).sum()):6d} / {V}')
bpy.ops.wm.save_as_mainfile(filepath=OUT); print('SAVED', OUT)
