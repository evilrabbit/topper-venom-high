# Build seam-traced parts from seam_regions.py output (Blender 5, headless).
#   TMERGE=0.00025 MINR=1500 blender -b shoe-navy.blend --python seam_parts.py -- regions.npz state_parts.json OUT.blend
import bpy, numpy as np, json, sys, os, time
argv = sys.argv[sys.argv.index('--') + 1:]; NPZ, STATE, OUT = argv
TMERGE = float(os.environ.get('TMERGE', '0.0002')); MINR = int(os.environ.get('MINR', '1500'))
TSMALL = float(os.environ.get('TSMALL', '0.00035')); SMALLR = int(os.environ.get('SMALLR', '6000'))
GROUP_BY_NAME = {'laces', 'lining', 'eyelets', 'tongue', 'tongue_logo'}
t0 = time.time()
Z = np.load(NPZ); lab = Z['lab'].copy(); old = Z['old']; fd = Z['fd']; oldnames = [str(n) for n in Z['names']]
objs = [o for o in bpy.data.objects if o.type == 'MESH']
for o in bpy.data.objects: o.select_set(False)
for o in objs: o.select_set(True)
bpy.context.view_layer.objects.active = objs[0]; bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active; me = obj.data
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT'); bpy.ops.mesh.remove_doubles(threshold=1e-6); bpy.ops.object.mode_set(mode='OBJECT')
F = len(me.polygons); assert F == len(lab), (F, len(lab))
assert [m.name[5:] for m in me.materials] == oldnames
lt = np.zeros(F, np.int32); me.polygons.foreach_get('loop_total', lt)
ei = np.zeros(len(me.loops), np.int32); me.loops.foreach_get('edge_index', ei)
fid = np.repeat(np.arange(F), lt); o = np.argsort(ei, kind='stable'); es = ei[o]; fs = fid[o]; same = es[1:] == es[:-1]
A = fs[:-1][same]; B = fs[1:][same]
w = np.maximum(fd[A], fd[B])                        # groove depth along each shared edge
def relabel(l): return np.unique(l, return_inverse=True)[1]
lab = relabel(lab)
# 1) merge neighbours whose common border is not a real groove (weakest first), 2) absorb tiny regions
for rnd in range(40):
    R = lab.max() + 1; la = lab[A]; lb = lab[B]; m = la != lb
    if not m.any(): break
    p = np.minimum(la[m], lb[m]).astype(np.int64) * R + np.maximum(la[m], lb[m])
    up, inv = np.unique(p, return_inverse=True)
    strength = np.bincount(inv, weights=w[m]) / np.bincount(inv); length = np.bincount(inv)
    sz = np.bincount(lab, minlength=R)
    ra, rb = up // R, up % R
    small = (sz[ra] < MINR) | (sz[rb] < MINR)
    # majority old part per region: weak borders only merge regions that are the same part semantically
    mj = np.bincount(lab.astype(np.int64) * len(oldnames) + old, minlength=R * len(oldnames)).reshape(R, len(oldnames)).argmax(1)
    guard = (mj[ra] == mj[rb]) if os.environ.get('GUARD', '0') == '1' else np.ones(len(ra), bool)
    sole_ids = np.array([i for i, n in enumerate(oldnames) if n in ('outsole', 'midsole', 'sole_stripes', 'toe_bumper')])
    insole = np.isin(mj, sole_ids)
    smallish = (np.minimum(sz[ra], sz[rb]) < SMALLR) & (strength < TSMALL) & insole[ra] & insole[rb]   # noisy fragments on the smooth sole wall
    cand = np.nonzero(((strength < TMERGE) & guard) | small | smallish)[0]
    if not len(cand): break
    # weakest border first; each region merges at most once per round (keeps strengths honest)
    cand = cand[np.lexsort((-length[cand], strength[cand] - small[cand] * 1.0))]
    used = np.zeros(R, bool); mp = np.arange(R); n = 0
    for c in cand:
        a_, b_ = ra[c], rb[c]
        if used[a_] or used[b_]: continue
        keep, drop = (a_, b_) if sz[a_] >= sz[b_] else (b_, a_)
        mp[drop] = keep; used[a_] = used[b_] = True; n += 1
    lab = relabel(mp[lab])
    print(f'round {rnd}: merged {n}, regions now {lab.max() + 1}')
R = lab.max() + 1; sz = np.bincount(lab)
# name each region by the old part it overlaps most
maj = np.array([np.bincount(old[lab == r], minlength=len(oldnames)).argmax() for r in range(R)])
names = []; groups = {}
for r in np.argsort(-sz):
    base = oldnames[maj[r]]
    key = base if base in GROUP_BY_NAME else (base, r)
    groups.setdefault(key, []).append(r)
final = np.zeros(F, np.int32); partnames = []; partbase = []
count = {}
for key, rs in sorted(groups.items(), key=lambda kv: -sum(sz[r] for r in kv[1])):
    base = key if isinstance(key, str) else key[0]
    count[base] = count.get(base, 0) + 1
    nm = base if count[base] == 1 else f'{base}.{count[base]}'
    for r in rs: final[lab == r] = len(partnames)
    partnames.append(nm); partbase.append(base)
print('parts', len(partnames))
for nm, k in sorted(zip(partnames, np.bincount(final)), key=lambda x: x[0]): print(f'  {nm:28s} {k:7d}')
# materials: copy the old part's material, colour from the current editor state
state = {p['name']: p for p in json.load(open(STATE))['parts']}
def srgb2lin(c): return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
oldmats = list(me.materials); newmats = []
for m in oldmats: m.name = 'old_' + m.name           # free the names before the copies take them
for nm, base in zip(partnames, partbase):
    m = oldmats[oldnames.index(base)].copy(); m.name = 'shoe_' + nm
    assert m.name == 'shoe_' + nm, m.name
    g = [n for n in m.node_tree.nodes if n.type == 'GROUP'][0]
    if base in state:
        h = state[base]['color'].lstrip('#'); rgb = [srgb2lin(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4)]
        g.inputs['Color'].default_value = (*rgb, 1); g.inputs['Detail'].default_value = state[base]['detail']; m.diffuse_color = (*rgb, 1)
    newmats.append(m)
me.materials.clear()
for m in newmats: me.materials.append(m)
me.polygons.foreach_set('material_index', final); me.update()
for m in oldmats:
    if m.users == 0: bpy.data.materials.remove(m)
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT'); bpy.ops.mesh.separate(type='MATERIAL'); bpy.ops.object.mode_set(mode='OBJECT')
for ob in [x for x in bpy.data.objects if x.type == 'MESH']:
    used = {p.material_index for p in ob.data.polygons}
    mt = ob.data.materials[next(iter(used))]
    ob.data.materials.clear(); ob.data.materials.append(mt)
    ob.data.polygons.foreach_set('material_index', np.zeros(len(ob.data.polygons), np.int32))
    ob.name = mt.name[5:]; ob.data.name = ob.name
bpy.ops.wm.save_as_mainfile(filepath=OUT)
print('SAVED', OUT, round(time.time() - t0, 1), 's')
