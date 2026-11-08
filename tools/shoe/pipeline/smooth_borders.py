# Smooth part borders in 3D (no UV seams): subdivide the faces along every border, then a
# majority vote over a ~3mm surface neighbourhood rounds the triangle stair-steps into smooth contours.
#   blender -b shoe-seams.blend --python smooth_borders.py -- OUT.blend
import bpy, bmesh, numpy as np, sys, os, time
from mathutils.kdtree import KDTree
OUT = sys.argv[sys.argv.index('--') + 1]
SUB = int(os.environ.get('SUB', '2')); RAD = float(os.environ.get('RAD', '0.0095')); ITERS = int(os.environ.get('ITERS', '2'))
t0 = time.time()
objs = [o for o in bpy.data.objects if o.type == 'MESH']
for o in bpy.data.objects: o.select_set(False)
for o in objs: o.select_set(True)
bpy.context.view_layer.objects.active = objs[0]; bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active; me = obj.data
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT'); bpy.ops.mesh.remove_doubles(threshold=1e-6); bpy.ops.object.mode_set(mode='OBJECT')
bm = bmesh.new(); bm.from_mesh(me)
def border_faces(bm, rings=1):
    s = {f for e in bm.edges if len(e.link_faces) == 2 and e.link_faces[0].material_index != e.link_faces[1].material_index for f in e.link_faces}
    for _ in range(rings - 1):
        s |= {g for f in list(s) for e in f.edges for g in e.link_faces}
    return s
for it in range(SUB):
    band = border_faces(bm, 2)
    edges = {e for f in band for e in f.edges}
    bmesh.ops.subdivide_edges(bm, edges=list(edges), cuts=1, use_grid_fill=True)
    bm.faces.ensure_lookup_table()
    print(f'subdivide {it}: band {len(band)} faces -> mesh {len(bm.faces)} faces', round(time.time() - t0, 1), 's', flush=True)
bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
bm.faces.ensure_lookup_table()
F = len(bm.faces)
cen = np.array([f.calc_center_median() for f in bm.faces]); area = np.array([f.calc_area() for f in bm.faces])
lab = np.array([f.material_index for f in bm.faces])
kd = KDTree(F)
for i, c in enumerate(cen): kd.insert(c, i)
kd.balance()
for it in range(ITERS):
    band = np.array(sorted(f.index for f in border_faces(bm, 3)))
    new = lab.copy(); changed = 0
    for i in band:
        hits = kd.find_range(cen[i], RAD)
        if len(hits) < 3: continue
        idx = np.fromiter((h[1] for h in hits), int, len(hits))
        w = area[idx] * (1.0 - np.fromiter((h[2] for h in hits), float, len(hits)) / RAD)   # nearer surface counts more
        votes = np.bincount(lab[idx], weights=w)
        m = votes.argmax()
        if m != lab[i]: new[i] = m; changed += 1
    lab = new
    for f, l in zip(bm.faces, lab): f.material_index = int(l)
    print(f'vote {it}: {len(band)} border faces, {changed} changed', round(time.time() - t0, 1), 's', flush=True)
bm.to_mesh(me); bm.free(); me.update()
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT'); bpy.ops.mesh.separate(type='MATERIAL'); bpy.ops.object.mode_set(mode='OBJECT')
for ob in [x for x in bpy.data.objects if x.type == 'MESH']:
    used = {p.material_index for p in ob.data.polygons}; mt = ob.data.materials[next(iter(used))]
    ob.data.materials.clear(); ob.data.materials.append(mt)
    ob.data.polygons.foreach_set('material_index', np.zeros(len(ob.data.polygons), np.int32))
    ob.name = mt.name[5:]; ob.data.name = ob.name
bpy.ops.wm.save_as_mainfile(filepath=OUT); print('SAVED', OUT, F, 'faces', round(time.time() - t0, 1), 's')
