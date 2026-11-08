# Remove saw-teeth from part borders: a face whose neighbours mostly belong to one other part joins it.
#   blender -b shoe-seams.blend --python smooth_labels.py -- OUT.blend
import bpy, numpy as np, sys, os
OUT = sys.argv[sys.argv.index('--') + 1]; ITERS = int(os.environ.get('ITERS', '6'))
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
# neighbour table (triangles: up to 3 edge neighbours)
src = np.concatenate([A, B]); dst = np.concatenate([B, A]); order = np.argsort(src, kind='stable'); src = src[order]; dst = dst[order]
start = np.searchsorted(src, np.arange(F + 1)); cnt = np.diff(start)
NB = np.full((F, 3), -1, np.int64)
for k in range(3):
    has = cnt > k; NB[has, k] = dst[start[:-1][has] + k]
total = 0
for it in range(ITERS):
    nl = np.where(NB >= 0, lab[np.maximum(NB, 0)], -1)
    # a label shared by >= 2 of the neighbours and different from mine
    flip = np.full(F, -1)
    for a, b in ((0, 1), (0, 2), (1, 2)):
        m = (nl[:, a] >= 0) & (nl[:, a] == nl[:, b]) & (nl[:, a] != lab)
        flip[m] = nl[m, a]
    ch = flip >= 0; lab[ch] = flip[ch]; total += int(ch.sum())
    print(f'iter {it}: flipped {int(ch.sum())}')
    if not ch.any(): break
print('total flipped', total)
me.polygons.foreach_set('material_index', lab); me.update()
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT'); bpy.ops.mesh.separate(type='MATERIAL'); bpy.ops.object.mode_set(mode='OBJECT')
for ob in [x for x in bpy.data.objects if x.type == 'MESH']:
    used = {p.material_index for p in ob.data.polygons}; mt = ob.data.materials[next(iter(used))]
    ob.data.materials.clear(); ob.data.materials.append(mt)
    ob.data.polygons.foreach_set('material_index', np.zeros(len(ob.data.polygons), np.int32))
    ob.name = mt.name[5:]; ob.data.name = ob.name
bpy.ops.wm.save_as_mainfile(filepath=OUT); print('SAVED', OUT)
