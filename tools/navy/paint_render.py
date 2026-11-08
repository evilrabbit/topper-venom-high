# Blender (headless): paint the Navy colorway texture from the scan + baked maps, then render a preview
# matching the reference photo angle.   blender -b shoe.blend --python paint_render.py -- params.json tag
import bpy, json, sys, os, math
import numpy as np

D = '/tmp/topper-blender'
argv = sys.argv[sys.argv.index('--') + 1:]
P = json.load(open(argv[0]))
TAG = argv[1] if len(argv) > 1 else 'v'

def load(path):
    img = bpy.data.images.load(path, check_existing=True)
    a = np.array(img.pixels[:], dtype=np.float32).reshape(img.size[1], img.size[0], img.channels)
    return a

obj = [o for o in bpy.data.objects if o.type == 'MESH'][0]
mat = obj.active_material
nt = mat.node_tree
bsdf = [n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'][0]
base_img = bsdf.inputs['Base Color'].links[0].from_node.image
W, H = base_img.size
base = np.array(base_img.pixels[:], dtype=np.float32).reshape(H, W, base_img.channels)[..., :3]
pos = load(f'{D}/pos.exr')[..., :3]
nrm = load(f'{D}/nrm.exr')[..., :3] * 2 - 1
mask = load(P['mask'])[..., :3]

def boxblur(a, r):
    # mean over a (2r+1)^2 window via an integral image
    pad = np.pad(a, r + 1, mode='edge')
    c = pad.cumsum(0).cumsum(1)
    k = 2 * r + 1
    s = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return (s / (k * k))[:a.shape[0], :a.shape[1]]
def grow(a, r):
    # separable square max filter
    out = a.copy()
    for d in range(1, r + 1):
        out = np.maximum(out, np.maximum(np.roll(a, d, 0), np.roll(a, -d, 0)))
    a2 = out.copy()
    for d in range(1, r + 1):
        out = np.maximum(out, np.maximum(np.roll(a2, d, 1), np.roll(a2, -d, 1)))
    return out
def shrink(a, r):
    return 1 - grow(1 - a, r)

def ss(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t)
def hexc(h):
    h = h.lstrip('#'); return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)], dtype=np.float32)

# glTF-normalized coordinates (same convention as the site shader): x width (-x outer), y up, z heel(0)->toe(1)
fx, fy, fz = pos[..., 0], pos[..., 2], 1 - pos[..., 1]
nz_up = nrm[..., 2]                       # Blender Z up
L = base @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
sat = base.max(-1) - base.min(-1)
t = ss(0.12, 0.8, L)                       # 0 = black suede/rubber in the scan, 1 = white leather

detail = (1 - t) * ss(0.03, 0.34, L) + t * ss(0.55, 0.97, L)
WHITE, NAVY, INK = hexc(P['white']), hexc(P['navy']), hexc(P['ink'])
# local shading only: creases/stitching relative to the neighbourhood, not the scan's black-vs-white tone
Lb = boxblur(L, P['detail_r'])
contrast = np.clip((L - Lb) / np.maximum(Lb, P['detail_floor']), -0.6, 0.25)
k = P['detail_k_dark'] + (P['detail_k'] - P['detail_k_dark']) * t     # scuffed black suede: less detail
white = WHITE * np.clip(1 + k * contrast, 0.6, 1.0)[..., None] * P['wbase']
navy = NAVY * (P['nmin'] + (P['nmax'] - P['nmin']) * ss(0.05, 0.6, L))[..., None]
col = white.copy()

def put(c, w):
    global col
    col = col * (1 - w[..., None]) + c * w[..., None]

outer = 1 - ss(0.2, 0.26, fx)
def box(z0, z1, y0, y1, e=0.004):
    return ss(z0 - e, z0, fz) * (1 - ss(z1, z1 + e, fz)) * ss(y0 - e, y0, fy) * (1 - ss(y1, y1 + e, fy))

# outsole rubber band: height varies heel -> mid -> toe
bh, bm, bt = P['band_heel'], P['band_mid'], P['band_toe']
zh, zt = P['band_heel_z'], P['band_toe_z']
band_top = np.where(fz < 0.5, bm + (bh - bm) * (1 - ss(0, zh, fz)), bm + (bt - bm) * ss(zt, 1.0, fz))
band = 1 - ss(band_top - 0.002, band_top + 0.002, fy)
band = np.maximum(band, ss(-0.4, -0.7, nz_up) * (fy < 0.12))     # underside / tread
stripe_keep = P['band_stripes']
put(navy * 1 + 0, band * (1 - stripe_keep * t))
# panels (close small gaps in the painted mask)
pm = np.clip(mask[..., 0], 0, 1)
pm = np.maximum(pm, shrink(grow(pm, P['panel_close']), P['panel_close']))
# 3D fill: dark texels within a few mm of a panel on the shoe surface (crosses UV island seams)
v = P['vox']
G = v[0]
idx = np.clip((np.stack([fx, fy, fz], -1) * (G - 1)).round().astype(np.int32), 0, G - 1)
occ = np.zeros((G, G, G), bool)
sel = (shrink((pm > 0.5).astype(np.float32), v[3]) > 0.5) & (pos.sum(-1) > 0)   # solid panel only, no strays
occ[idx[sel, 0], idx[sel, 1], idx[sel, 2]] = True
for _ in range(v[1]):
    o = occ.copy()
    for ax in range(3):
        o |= np.roll(occ, 1, ax) | np.roll(occ, -1, ax)
    occ = o
near3d = occ[idx[..., 0], idx[..., 1], idx[..., 2]] & (pos.sum(-1) > 0)
pm = np.maximum(pm, near3d * (L < v[2]) * ss(v[4] - 0.01, v[4], fy) * (1 - ss(v[5], v[5] + 0.01, fy)))
pm = ss(0.35, 0.6, pm)          # no half-navy edges
put(navy, pm)
# small navy piece at the bottom of the lacing (outer side), black in the scan
lp = P['lace_piece']
if lp: put(navy, box(lp[0], lp[1], lp[2], lp[3]) * ss(lp[4] - 0.01, lp[4], fx) * (1 - ss(lp[5], lp[5] + 0.01, fx)) * (1 - t) * (nz_up > -0.2))
# printed heel wordmark + tongue logo keep black ink
ink_w = np.maximum(outer * box(*P['heel_text']), box(*P['tongue_logo']) * (1 - ss(*P['tongue_x'], np.abs(fx - 0.5))) * ss(0.15, 0.3, -nrm[..., 1]))
# printed strokes sit on white: keep ink only where the neighbourhood is mostly white leather
# strokes are thin: anything dark that survives an opening of radius ink_r is lining/edge, not print
dark = (L < 0.42).astype(np.float32)
dark_big = grow(shrink(dark, P['ink_r']), P['ink_r'] + 2)
put(INK, ink_w * (1 - ss(0.3, 0.55, L)) * (1 - dark_big))
# remaining black in the logo boxes (lining, tongue edges) becomes white

# arrows in the midsole window
put(navy, outer * box(*P['arrows']) * (1 - ss(0.3, 0.55, L)))
# saturated details (red ball) stay as scanned
keep = ss(0.12, 0.3, sat)
col = col * (1 - keep[..., None]) + base * keep[..., None]

out = np.concatenate([np.clip(col, 0, 1), np.ones((H, W, 1), np.float32)], -1)
img = bpy.data.images.new('navy_paint', W, H, alpha=False)
img.pixels[:] = out.ravel()
img.filepath_raw = f'{D}/navy_{TAG}.png'; img.file_format = 'PNG'; img.save()

# ---------- preview render ----------
tex = bsdf.inputs['Base Color'].links[0].from_node
tex.image = img
for k in ('Metallic', 'Roughness'):
    for l in list(bsdf.inputs[k].links): nt.links.remove(l)
bsdf.inputs['Metallic'].default_value = 0
bsdf.inputs['Roughness'].default_value = 0.55

sc = bpy.context.scene
sc.render.engine = 'CYCLES'; sc.cycles.samples = 48; sc.cycles.use_denoising = True
sc.render.resolution_x, sc.render.resolution_y = 1152, 864
sc.view_settings.view_transform = 'Standard'
world = bpy.data.worlds.new('w'); sc.world = world; world.use_nodes = True
world.node_tree.nodes['Background'].inputs[0].default_value = (0.38, 0.38, 0.38, 1)
world.node_tree.nodes['Background'].inputs[1].default_value = 1.0

def light(name, loc, energy, size):
    d = bpy.data.lights.new(name, 'AREA'); d.energy = energy; d.size = size
    o = bpy.data.objects.new(name, d); sc.collection.objects.link(o); o.location = loc
    c = o.constraints.new('TRACK_TO'); c.target = obj; c.track_axis = 'TRACK_NEGATIVE_Z'
light('key', (-2.0, -1.5, 2.2), P['key'], 2.5)
light('fill', (-1.5, 2.0, 0.8), P['fill'], 3)

cam_d = bpy.data.cameras.new('cam'); cam_d.lens = 70
cam = bpy.data.objects.new('cam', cam_d); sc.collection.objects.link(cam); sc.camera = cam
for name, loc in P['views'].items():
    cam.location = loc
    c = cam.constraints.get('t') or cam.constraints.new('TRACK_TO'); c.name = 't'; c.target = obj; c.track_axis = 'TRACK_NEGATIVE_Z'; c.up_axis = 'UP_Y'
    sc.render.filepath = f'{D}/render_{TAG}_{name}.png'
    bpy.ops.render.render(write_still=True)
print('DONE', TAG)
