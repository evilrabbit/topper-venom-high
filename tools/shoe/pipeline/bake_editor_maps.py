# Bake UV-space helper maps for tools/editor from shoe-navy.blend (Blender 5, headless).
import bpy, numpy as np, json, os
OUT = '/Users/evilrabbit/topper-venom/tools/editor/maps'
RES = int(os.environ.get('RES', '2048'))
objs = [o for o in bpy.data.objects if o.type == 'MESH']
mats = []
for o in objs:
    m = o.active_material
    if m not in mats: mats.append(m)
info = []
for i, m in enumerate(mats):
    g = [n for n in m.node_tree.nodes if n.type == 'GROUP'][0]
    lin = list(g.inputs['Color'].default_value)[:3]
    srgb = [((1.055 * c ** (1 / 2.4) - 0.055) if c > 0.0031308 else 12.92 * c) for c in lin]
    info.append(dict(name=m.name[5:], color='#%02x%02x%02x' % tuple(round(max(0, min(1, c)) * 255) for c in srgb),
                     detail=g.inputs['Detail'].default_value, ink=g.inputs['Ink Threshold'].default_value,
                     mean=g.inputs['Texture Mean'].default_value))
for o in bpy.data.objects: o.select_set(False)
for o in objs: o.select_set(True)
bpy.context.view_layer.objects.active = objs[0]
bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT'); bpy.ops.mesh.remove_doubles(threshold=1e-6); bpy.ops.object.mode_set(mode='OBJECT')
_me = obj.data; _F = len(_me.polygons)
_lab = np.zeros(_F, np.int32); _me.polygons.foreach_get('material_index', _lab)
_lt = np.zeros(_F, np.int32); _me.polygons.foreach_get('loop_total', _lt)
_ei = np.zeros(len(_me.loops), np.int32); _me.loops.foreach_get('edge_index', _ei)
_fid = np.repeat(np.arange(_F), _lt); _o = np.argsort(_ei, kind='stable'); _es = _ei[_o]; _fs = _fid[_o]; _same = _es[1:] == _es[:-1]
_A = _fs[:-1][_same]; _B = _fs[1:][_same]
# border VERTICES (touch faces of 2+ parts): interpolated across faces this gives a thin line along the border edges
_lv = np.zeros(len(_me.loops), np.int64); _me.loops.foreach_get('vertex_index', _lv)
_ll = np.repeat(_lab, _lt); _V = len(_me.vertices)
_mn = np.full(_V, 1 << 30); _mx = np.full(_V, -1); np.minimum.at(_mn, _lv, _ll); np.maximum.at(_mx, _lv, _ll)
_vb = (_mn != _mx).astype(np.float32)
_ca = _me.color_attributes.new('part_edge', 'FLOAT_COLOR', 'POINT')
_ca.data.foreach_set('color', np.stack([_vb, _vb, _vb, np.ones(_V, np.float32)], 1).ravel())
print('border vertices', int(_vb.sum()))
# bbox + scale
co = np.zeros(len(obj.data.vertices) * 3); obj.data.vertices.foreach_get('co', co); co = co.reshape(-1, 3)
bmin = co.min(0); bsize = co.max(0) - bmin
sc = bpy.context.scene; sc.render.engine = 'CYCLES'; sc.cycles.device = 'CPU'; sc.cycles.samples = 1
sc.render.bake.margin = 0
def bake(build):
    img = bpy.data.images.new('b', RES, RES, alpha=False, float_buffer=True); img.colorspace_settings.name = 'Non-Color'
    tmp = []
    for i, m in enumerate(mats):
        nt = m.node_tree; N = nt.nodes
        out = [n for n in N if n.type == 'OUTPUT_MATERIAL'][0]
        em = N.new('ShaderNodeEmission'); tmp.append((nt, em))
        sock = build(i, m, nt, N); nt.links.new(sock, em.inputs['Color']); nt.links.new(em.outputs[0], out.inputs['Surface'])
        tx = N.new('ShaderNodeTexImage'); tx.image = img; tmp.append((nt, tx))
        for n in N: n.select = False
        tx.select = True; N.active = tx
    bpy.ops.object.bake(type='EMIT')
    a = np.array(img.pixels[:], np.float32).reshape(RES, RES, 4)[::-1, :, :3].copy()   # top row first (glTF v)
    for nt, n in tmp: nt.nodes.remove(n)
    bpy.data.images.remove(img)
    return a
def const(v):
    def f(i, m, nt, N):
        r = N.new('ShaderNodeRGB'); r.outputs[0].default_value = (v(i), 0, 0, 1); return r.outputs[0]
    return f
def tex_socket(m):
    g = [n for n in m.node_tree.nodes if n.type == 'GROUP'][0]
    return g.inputs['Texture'].links[0].from_socket, g
def shade(i, m, nt, N):
    ts, g = tex_socket(m)
    bw = N.new('ShaderNodeRGBToBW'); nt.links.new(ts, bw.inputs[0])
    dv = N.new('ShaderNodeMath'); dv.operation = 'DIVIDE'; nt.links.new(bw.outputs[0], dv.inputs[0]); dv.inputs[1].default_value = max(g.inputs['Texture Mean'].default_value, 0.004)
    cl = N.new('ShaderNodeClamp'); cl.inputs['Min'].default_value = 0.35; cl.inputs['Max'].default_value = 1.6; nt.links.new(dv.outputs[0], cl.inputs['Value'])
    thr = g.inputs['Ink Threshold'].default_value
    mr = N.new('ShaderNodeMapRange'); nt.links.new(dv.outputs[0], mr.inputs['Value'])
    mr.inputs['From Min'].default_value = thr - 0.08; mr.inputs['From Max'].default_value = max(thr, 1e-4)
    mr.inputs['To Min'].default_value = 1.0 if thr > 0 else 0.0; mr.inputs['To Max'].default_value = 0.0
    cmb = N.new('ShaderNodeCombineColor'); nt.links.new(cl.outputs[0], cmb.inputs[0]); nt.links.new(mr.outputs[0], cmb.inputs[1])
    return cmb.outputs[0]
def geo(kind):
    def f(i, m, nt, N):
        gn = N.new('ShaderNodeNewGeometry'); return gn.outputs[kind]
    return f
ID = bake(const(lambda i: (i + 1) / 255.0))[..., 0]
ids = np.rint(ID * 255).astype(np.int32)         # 0 = empty texel, k = part k-1
SH = bake(shade); POS = bake(geo('Position')); NRM = bake(geo('Normal'))
def edgeattr(i, m, nt, N):
    a = N.new('ShaderNodeVertexColor'); a.layer_name = 'part_edge'; return a.outputs['Color']
EDGE = bake(edgeattr)[..., 0]
INK_FROM = os.environ.get('INK_FROM')
if INK_FROM:                                   # keep the print/ink mask from earlier maps (same UV layout)
    im_ = bpy.data.images.load(INK_FROM); im_.colorspace_settings.name = 'Non-Color'
    if tuple(im_.size) != (RES, RES): im_.scale(RES, RES)           # earlier maps may be a different resolution
    SH[..., 1] = np.array(im_.pixels[:], np.float32).reshape(RES, RES, im_.channels)[::-1, :, 1]
    print('ink taken from', INK_FROM)
filled = ids > 0
print('coverage', round(float(filled.mean()), 4))
# pad 16 px so bilinear/mip sampling at seams never reads empty texels
def pad(arrs, filled, iters=16):
    arrs = [a.copy() for a in arrs]; f = filled.copy()
    for _ in range(iters):
        grow = np.zeros_like(f); src = [np.zeros_like(a) for a in arrs]
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nf = np.roll(f, (dy, dx), (0, 1)); g2 = (~f) & nf & (~grow)
            for s, a in zip(src, arrs): s[g2] = np.roll(a, (dy, dx), (0, 1))[g2]
            grow |= g2
        for s, a in zip(src, arrs): a[grow] = s[grow]
        f |= grow
    return arrs, f
(ids_p, SH, POS, NRM, EDGE), fp = pad([ids, SH, POS, NRM, EDGE], filled, iters=16 * RES // 2048)
def save(name, rgb):
    img = bpy.data.images.new(name, RES, RES, alpha=True, float_buffer=False); img.colorspace_settings.name = 'Non-Color'
    a = np.concatenate([np.clip(rgb, 0, 1), np.ones((RES, RES, 1), np.float32)], 2)[::-1]
    img.pixels[:] = a.ravel(); img.filepath_raw = os.path.join(OUT, name + '.png'); img.file_format = 'PNG'; img.save()
z = np.zeros((RES, RES), np.float32)
save('id', np.stack([ids_p / 255.0, fp.astype(np.float32), np.clip(EDGE, 0, 1)], -1))   # R = part+1, G = covered, B = 3D part border
save('shade', np.stack([SH[..., 0] / 1.6, SH[..., 1], z], -1))                  # R = shade/1.6, G = ink
pn = np.clip((POS - bmin) / bsize, 0, 1); q = np.rint(pn * 65535).astype(np.int32)
save('posHi', (q >> 8) / 255.0); save('posLo', (q & 255) / 255.0)
save('normal', np.clip(NRM * 0.5 + 0.5, 0, 1))
# paint layer seed: the painted red basketball from the original site texture
old = bpy.data.images.load('/Users/evilrabbit/topper-venom/tools/shoe/navy-color.orig.webp'); old.colorspace_settings.name = 'Non-Color'
if tuple(old.size) != (RES, RES): old.scale(RES, RES)
o = np.array(old.pixels[:], np.float32).reshape(RES, RES, old.channels)[::-1, :, :3]
sat = o.max(2) - o.min(2); red = (sat > 0.18) & (o[..., 0] > o[..., 2] + 30 / 255)
img = bpy.data.images.new('paint_seed', RES, RES, alpha=True, float_buffer=False); img.colorspace_settings.name = 'Non-Color'
pa = np.concatenate([o * red[..., None], red[..., None].astype(np.float32)], 2)[::-1]
img.pixels[:] = pa.ravel(); img.alpha_mode = 'STRAIGHT'; img.filepath_raw = os.path.join(OUT, 'paint-seed.png'); img.file_format = 'PNG'; img.save()
length = float(bsize.max())
json.dump(dict(parts=info, bboxMin=bmin.tolist(), bboxSize=bsize.tolist(), mmPerUnit=310.0 / length, res=RES),
          open(os.path.join(OUT, 'parts.json'), 'w'), indent=1)
print('MAPS OK', len(info), 'parts; red px', int(red.sum()))
