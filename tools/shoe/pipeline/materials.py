# Hyper-real part materials for the shoe library (Blender 5, Cycles).
#   blender -b shoe-library.blend --python materials.py -- OUT.blend colorway.json
# One shared node group "ShoeMaterial" with per-part inputs; presets live in PRESETS.
# Detail comes from the scan's colour texture (shading / dirt / stitching) plus procedural micro-grain.
import bpy, json, sys, colorsys
argv = sys.argv[sys.argv.index('--') + 1:]
OUT, CW = argv[0], json.load(open(argv[1]))

PRESETS = {
    #           rough  sheen  sheen_r  spec  bump  grain_scale  grain_kind  sss   coat  fuzz_edge
    'nubuck':   dict(rough=0.96, sheen=0.12, sheen_r=0.9, spec=0.08, bump=0.7,  grain=1600, kind='noise',   sss=0.02, coat=0.0,  fuzz=0.55),
    'leather':  dict(rough=0.48, sheen=0.1, sheen_r=0.4,  spec=0.5,  bump=0.4,  grain=3200, kind='voronoi', sss=0.03, coat=0.05, fuzz=0.0),
    'patent':   dict(rough=0.1,  sheen=0.0, sheen_r=0.3,  spec=0.7,  bump=0.04, grain=800,  kind='noise',   sss=0.0,  coat=0.7,  fuzz=0.0),
    'rubber':   dict(rough=0.62, sheen=0.0, sheen_r=0.3,  spec=0.42, bump=0.3,  grain=2600, kind='noise',   sss=0.0,  coat=0.0,  fuzz=0.0),
    'eva':      dict(rough=0.74, sheen=0.08, sheen_r=0.5, spec=0.33, bump=0.22, grain=4000, kind='noise',   sss=0.06, coat=0.0,  fuzz=0.0),
    'mesh':     dict(rough=0.72, sheen=0.25, sheen_r=0.6, spec=0.3,  bump=0.55, grain=5200, kind='weave',   sss=0.0,  coat=0.0,  fuzz=0.3),
    'nylon':    dict(rough=0.58, sheen=0.22, sheen_r=0.45, spec=0.4, bump=0.35, grain=6000, kind='weave',   sss=0.0,  coat=0.0,  fuzz=0.2),
    'print':    dict(rough=0.5,  sheen=0.0, sheen_r=0.3,  spec=0.4,  bump=0.08, grain=1000, kind='noise',   sss=0.0,  coat=0.0,  fuzz=0.0),
}
DEFAULT_MATERIAL = {
    'upper': 'leather', 'toe_cap': 'leather', 'vamp_panel': 'leather', 'collar': 'nylon', 'heel_tab': 'leather',
    'tongue': 'nylon', 'tongue_badge': 'print', 'laces': 'nylon', 'lining': 'mesh',
    'midsole': 'eva', 'heel_plate': 'eva', 'heel_ribs': 'rubber', 'outsole': 'rubber', 'toe_bumper': 'rubber', 'window_frame': 'eva',
}
for i in (1, 2, 3, 4):
    for s in 'LR': DEFAULT_MATERIAL[f'triangle_{i}.{s}'] = 'leather'

def hex2lin(h):
    h = h.lstrip('#'); c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c)

def build_group():
    ng = bpy.data.node_groups.get('ShoeMaterial')
    if ng: bpy.data.node_groups.remove(ng)
    ng = bpy.data.node_groups.new('ShoeMaterial', 'ShaderNodeTree')
    I = ng.interface
    def inp(name, t, default=None, mn=None, mx=None):
        s = I.new_socket(name, in_out='INPUT', socket_type=t)
        if default is not None: s.default_value = default
        if mn is not None: s.min_value = mn
        if mx is not None: s.max_value = mx
        return s
    inp('Scan Color', 'NodeSocketColor'); inp('Scan Blur', 'NodeSocketColor'); inp('Scan Roughness', 'NodeSocketFloat', 0.5)
    inp('Color', 'NodeSocketColor', (0.8, 0.8, 0.8, 1)); inp('Scan Detail', 'NodeSocketFloat', 0.6, 0, 1)
    inp('Texture Mean', 'NodeSocketFloat', 0.5); inp('Ink Threshold', 'NodeSocketFloat', 0.0, 0, 1); inp('Ink Color', 'NodeSocketColor', (0.004, 0.004, 0.004, 1))
    inp('Roughness', 'NodeSocketFloat', 0.5, 0, 1); inp('Specular', 'NodeSocketFloat', 0.5, 0, 1)
    inp('Sheen', 'NodeSocketFloat', 0.0, 0, 1); inp('Sheen Roughness', 'NodeSocketFloat', 0.4, 0, 1)
    inp('Bump', 'NodeSocketFloat', 0.4, 0, 1); inp('Grain Scale', 'NodeSocketFloat', 1500, 100, 10000)
    inp('Grain Kind', 'NodeSocketFloat', 0, 0, 2)  # 0 noise, 1 voronoi, 2 weave
    inp('Subsurface', 'NodeSocketFloat', 0.0, 0, 1); inp('Coat', 'NodeSocketFloat', 0.0, 0, 1); inp('Edge Fuzz', 'NodeSocketFloat', 0.0, 0, 1)
    inp('Wear', 'NodeSocketFloat', 0.25, 0, 1)
    inp('Light Color', 'NodeSocketColor', (0.9, 0.9, 0.9, 1)); inp('Edge Mode', 'NodeSocketFloat', 0.0, 0, 1)
    inp('Light Roughness', 'NodeSocketFloat', 0.46, 0, 1); inp('Light Sheen', 'NodeSocketFloat', 0.1, 0, 1); inp('Light Specular', 'NodeSocketFloat', 0.5, 0, 1)
    I.new_socket('Shader', in_out='OUTPUT', socket_type='NodeSocketShader')
    N, L = ng.nodes, ng.links
    gi = N.new('NodeGroupInput'); go = N.new('NodeGroupOutput')
    # ---- base colour: part colour modulated by the scan's shading, with ink where the scan prints are
    bw = N.new('ShaderNodeRGBToBW'); L.new(gi.outputs['Scan Color'], bw.inputs[0])
    bwb = N.new('ShaderNodeRGBToBW'); L.new(gi.outputs['Scan Blur'], bwb.inputs[0])
    mx = N.new('ShaderNodeMath'); mx.operation = 'MAXIMUM'; mx.inputs[1].default_value = 0.004; L.new(bwb.outputs[0], mx.inputs[0])
    dv = N.new('ShaderNodeMath'); dv.operation = 'DIVIDE'; L.new(bw.outputs[0], dv.inputs[0]); L.new(mx.outputs[0], dv.inputs[1])
    # ratio to the local average => pure detail (stitches, creases, dirt), independent of the part's absolute tone
    dvp = N.new('ShaderNodeMath'); dvp.operation = 'POWER'; dvp.inputs[1].default_value = 0.9; L.new(dv.outputs[0], dvp.inputs[0])
    cl = N.new('ShaderNodeClamp'); cl.inputs['Min'].default_value = 0.5; cl.inputs['Max'].default_value = 1.4; L.new(dvp.outputs[0], cl.inputs['Value'])
    # brightening cap scales with the colour's own luminance: dark parts get creases/dirt as darkening only
    cbw = N.new('ShaderNodeRGBToBW'); L.new(gi.outputs['Color'], cbw.inputs[0])
    capm = N.new('ShaderNodeMapRange'); L.new(cbw.outputs[0], capm.inputs['Value']); capm.inputs['From Min'].default_value = 0.0; capm.inputs['From Max'].default_value = 0.25
    capm.inputs['To Min'].default_value = 1.03; capm.inputs['To Max'].default_value = 1.35
    cl2 = N.new('ShaderNodeMath'); cl2.operation = 'MINIMUM'; L.new(cl.outputs[0], cl2.inputs[0]); L.new(capm.outputs[0], cl2.inputs[1])
    dsc = N.new('ShaderNodeMapRange'); L.new(cbw.outputs[0], dsc.inputs['Value']); dsc.inputs['From Min'].default_value = 0.0; dsc.inputs['From Max'].default_value = 0.3
    dsc.inputs['To Min'].default_value = 0.35; dsc.inputs['To Max'].default_value = 1.0
    dmul = N.new('ShaderNodeMath'); dmul.operation = 'MULTIPLY'; L.new(gi.outputs['Scan Detail'], dmul.inputs[0]); L.new(dsc.outputs[0], dmul.inputs[1])
    lp = N.new('ShaderNodeMix'); lp.data_type = 'FLOAT'; lp.inputs['A'].default_value = 1.0; L.new(dmul.outputs[0], lp.inputs['Factor']); L.new(cl2.outputs[0], lp.inputs['B'])
    # edge mode: the scan decides. Perceptual lightness of the *blurred* scan (noise-free edge) thresholded with a soft step.
    lb = N.new('ShaderNodeMath'); lb.operation = 'POWER'; lb.inputs[1].default_value = 1 / 2.2; L.new(bwb.outputs[0], lb.inputs[0])
    edge = N.new('ShaderNodeMapRange'); edge.interpolation_type = 'SMOOTHSTEP'; L.new(lb.outputs[0], edge.inputs['Value'])
    edge.inputs['From Min'].default_value = 0.40; edge.inputs['From Max'].default_value = 0.50
    emix = N.new('ShaderNodeMath'); emix.operation = 'MULTIPLY'; L.new(edge.outputs[0], emix.inputs[0]); L.new(gi.outputs['Edge Mode'], emix.inputs[1])
    ccol = N.new('ShaderNodeMix'); ccol.data_type = 'RGBA'; L.new(emix.outputs[0], ccol.inputs['Factor']); L.new(gi.outputs['Color'], ccol.inputs[6]); L.new(gi.outputs['Light Color'], ccol.inputs[7])
    mul = N.new('ShaderNodeMix'); mul.data_type = 'RGBA'; mul.blend_type = 'MULTIPLY'; mul.inputs['Factor'].default_value = 1.0
    L.new(ccol.outputs[2], mul.inputs[6]); L.new(lp.outputs[0], mul.inputs[7])
    lo = N.new('ShaderNodeMath'); lo.operation = 'SUBTRACT'; L.new(gi.outputs['Ink Threshold'], lo.inputs[0]); lo.inputs[1].default_value = 0.08
    mr = N.new('ShaderNodeMapRange'); L.new(bw.outputs[0], mr.inputs['Value']); L.new(lo.outputs[0], mr.inputs['From Min']); L.new(gi.outputs['Ink Threshold'], mr.inputs['From Max'])
    mr.inputs['To Min'].default_value = 1.0; mr.inputs['To Max'].default_value = 0.0
    gt = N.new('ShaderNodeMath'); gt.operation = 'GREATER_THAN'; gt.inputs[1].default_value = 0.0; L.new(gi.outputs['Ink Threshold'], gt.inputs[0])
    mf = N.new('ShaderNodeMath'); mf.operation = 'MULTIPLY'; L.new(mr.outputs[0], mf.inputs[0]); L.new(gt.outputs[0], mf.inputs[1])
    ink = N.new('ShaderNodeMix'); ink.data_type = 'RGBA'; L.new(mf.outputs[0], ink.inputs['Factor']); L.new(mul.outputs[2], ink.inputs[6]); L.new(gi.outputs['Ink Color'], ink.inputs[7])
    # ---- micro grain (object-space so it never shows UV seams)
    tc = N.new('ShaderNodeTexCoord')
    noise = N.new('ShaderNodeTexNoise'); noise.noise_dimensions = '3D'; noise.inputs['Detail'].default_value = 6; noise.inputs['Roughness'].default_value = 0.6
    L.new(tc.outputs['Object'], noise.inputs['Vector']); L.new(gi.outputs['Grain Scale'], noise.inputs['Scale'])
    vor = N.new('ShaderNodeTexVoronoi'); vor.feature = 'F1'; L.new(tc.outputs['Object'], vor.inputs['Vector']); L.new(gi.outputs['Grain Scale'], vor.inputs['Scale'])
    vsm = N.new('ShaderNodeMath'); vsm.operation = 'MULTIPLY'; vsm.inputs[1].default_value = 1.2; L.new(vor.outputs['Distance'], vsm.inputs[0])
    wave_u = N.new('ShaderNodeTexWave'); wave_u.wave_type = 'BANDS'; wave_u.bands_direction = 'X'; L.new(tc.outputs['UV'], wave_u.inputs['Vector']); L.new(gi.outputs['Grain Scale'], wave_u.inputs['Scale'])
    wave_v = N.new('ShaderNodeTexWave'); wave_v.wave_type = 'BANDS'; wave_v.bands_direction = 'Y'; L.new(tc.outputs['UV'], wave_v.inputs['Vector']); L.new(gi.outputs['Grain Scale'], wave_v.inputs['Scale'])
    weave = N.new('ShaderNodeMath'); weave.operation = 'MULTIPLY'; L.new(wave_u.outputs['Fac'], weave.inputs[0]); L.new(wave_v.outputs['Fac'], weave.inputs[1])
    k1 = N.new('ShaderNodeMix'); k1.data_type = 'FLOAT'; L.new(gi.outputs['Grain Kind'], k1.inputs['Factor']); L.new(noise.outputs['Fac'], k1.inputs['A']); L.new(vsm.outputs[0], k1.inputs['B'])
    k2f = N.new('ShaderNodeMath'); k2f.operation = 'SUBTRACT'; L.new(gi.outputs['Grain Kind'], k2f.inputs[0]); k2f.inputs[1].default_value = 1.0
    k2 = N.new('ShaderNodeMix'); k2.data_type = 'FLOAT'; k2.clamp_factor = True; L.new(k2f.outputs[0], k2.inputs['Factor']); L.new(k1.outputs[0], k2.inputs['A']); L.new(weave.outputs[0], k2.inputs['B'])
    grain = k2.outputs[0]
    # large-scale wear: lighter/rougher patches from a low-frequency noise
    wearN = N.new('ShaderNodeTexNoise'); wearN.inputs['Scale'].default_value = 18; wearN.inputs['Detail'].default_value = 3; L.new(tc.outputs['Object'], wearN.inputs['Vector'])
    wearF = N.new('ShaderNodeMapRange'); L.new(wearN.outputs['Fac'], wearF.inputs['Value']); wearF.inputs['From Min'].default_value = 0.45; wearF.inputs['From Max'].default_value = 0.7
    wearA = N.new('ShaderNodeMath'); wearA.operation = 'MULTIPLY'; L.new(wearF.outputs[0], wearA.inputs[0]); L.new(gi.outputs['Wear'], wearA.inputs[1])
    # ---- edge fuzz for nubuck: lighten at grazing angles (the nap catches light)
    # velvet nap: dark face-on, lifting only towards grazing angles (Layer Weight Facing is ~0 face-on, ~1 at the rim)
    lw = N.new('ShaderNodeLayerWeight'); lw.inputs['Blend'].default_value = 0.6
    fzp = N.new('ShaderNodeMath'); fzp.operation = 'POWER'; fzp.inputs[1].default_value = 4.5; L.new(lw.outputs['Facing'], fzp.inputs[0])
    fz2 = N.new('ShaderNodeMath'); fz2.operation = 'MULTIPLY'; L.new(fzp.outputs[0], fz2.inputs[0]); L.new(gi.outputs['Edge Fuzz'], fz2.inputs[1])  # (edge-aware fuzz applied below)
    fz3 = N.new('ShaderNodeMath'); fz3.operation = 'MULTIPLY'; fz3.inputs[1].default_value = 0.45; L.new(fz2.outputs[0], fz3.inputs[0])
    # nap catches light at grazing angles: lift towards a lighter version of the part colour (never neutral grey)
    lift = N.new('ShaderNodeMix'); lift.data_type = 'RGBA'; lift.blend_type = 'MIX'; lift.inputs['Factor'].default_value = 0.22
    L.new(gi.outputs['Color'], lift.inputs[6]); lift.inputs[7].default_value = (1, 1, 1, 1)
    fuzzcol = N.new('ShaderNodeMix'); fuzzcol.data_type = 'RGBA'; fuzzcol.blend_type = 'MIX'; L.new(fz3.outputs[0], fuzzcol.inputs['Factor'])
    L.new(ink.outputs[2], fuzzcol.inputs[6]); L.new(lift.outputs[2], fuzzcol.inputs[7])
    # grain also slightly modulates colour (nap/pebble shading)
    gcol = N.new('ShaderNodeMix'); gcol.data_type = 'RGBA'; gcol.blend_type = 'SOFT_LIGHT'; gcol.inputs['Factor'].default_value = 0.2
    L.new(fuzzcol.outputs[2], gcol.inputs[6])
    gc2 = N.new('ShaderNodeCombineColor'); L.new(grain, gc2.inputs[0]); L.new(grain, gc2.inputs[1]); L.new(grain, gc2.inputs[2]); L.new(gc2.outputs[0], gcol.inputs[7])
    # ---- roughness: preset + scan variation + grain + wear
    sr = N.new('ShaderNodeMapRange'); L.new(gi.outputs['Scan Roughness'], sr.inputs['Value']); sr.inputs['To Min'].default_value = -0.08; sr.inputs['To Max'].default_value = 0.08
    r1 = N.new('ShaderNodeMath'); r1.operation = 'ADD'; L.new(gi.outputs['Roughness'], r1.inputs[0]); L.new(sr.outputs[0], r1.inputs[1])
    gr = N.new('ShaderNodeMapRange'); L.new(grain, gr.inputs['Value']); gr.inputs['To Min'].default_value = -0.06; gr.inputs['To Max'].default_value = 0.06
    r2 = N.new('ShaderNodeMath'); r2.operation = 'ADD'; L.new(r1.outputs[0], r2.inputs[0]); L.new(gr.outputs[0], r2.inputs[1])
    wr = N.new('ShaderNodeMath'); wr.operation = 'MULTIPLY'; wr.inputs[1].default_value = 0.2; L.new(wearA.outputs[0], wr.inputs[0])
    r3 = N.new('ShaderNodeMath'); r3.operation = 'ADD'; L.new(r2.outputs[0], r3.inputs[0]); L.new(wr.outputs[0], r3.inputs[1])
    # edge mode: light side of the edge behaves like smooth leather (upper), dark side keeps the preset
    rleath = N.new('ShaderNodeMix'); rleath.data_type = 'FLOAT'; L.new(emix.outputs[0], rleath.inputs['Factor']); L.new(r3.outputs[0], rleath.inputs['A']); L.new(gi.outputs['Light Roughness'], rleath.inputs['B'])
    rcl = N.new('ShaderNodeClamp'); L.new(rleath.outputs[0], rcl.inputs['Value'])
    # ---- bump from grain (+ scan luminance for stitching / creases)
    bs = N.new('ShaderNodeMath'); bs.operation = 'MULTIPLY'; bs.inputs[1].default_value = 0.0016; L.new(gi.outputs['Bump'], bs.inputs[0])
    bmp = N.new('ShaderNodeBump'); L.new(bs.outputs[0], bmp.inputs['Strength']); bmp.inputs['Distance'].default_value = 0.4; L.new(grain, bmp.inputs['Height'])
    bmp2 = N.new('ShaderNodeBump'); bmp2.inputs['Strength'].default_value = 0.0015; bmp2.inputs['Distance'].default_value = 0.6
    L.new(cl.outputs[0], bmp2.inputs['Height']); L.new(bmp.outputs['Normal'], bmp2.inputs['Normal'])
    # ---- shader
    p = N.new('ShaderNodeBsdfPrincipled')
    L.new(gcol.outputs[2], p.inputs['Base Color']); L.new(rcl.outputs[0], p.inputs['Roughness']); L.new(bmp2.outputs['Normal'], p.inputs['Normal'])
    sheenE = N.new('ShaderNodeMix'); sheenE.data_type = 'FLOAT'; L.new(emix.outputs[0], sheenE.inputs['Factor']); L.new(gi.outputs['Sheen'], sheenE.inputs['A']); L.new(gi.outputs['Light Sheen'], sheenE.inputs['B'])
    fuzzE = N.new('ShaderNodeMix'); fuzzE.data_type = 'FLOAT'; L.new(emix.outputs[0], fuzzE.inputs['Factor']); L.new(gi.outputs['Edge Fuzz'], fuzzE.inputs['A']); fuzzE.inputs['B'].default_value = 0.0
    specE = N.new('ShaderNodeMix'); specE.data_type = 'FLOAT'; L.new(emix.outputs[0], specE.inputs['Factor']); L.new(gi.outputs['Specular'], specE.inputs['A']); L.new(gi.outputs['Light Specular'], specE.inputs['B'])
    L.new(specE.outputs[0], p.inputs['Specular IOR Level']); L.new(sheenE.outputs[0], p.inputs['Sheen Weight']); L.new(gi.outputs['Sheen Roughness'], p.inputs['Sheen Roughness'])
    L.new(lift.outputs[2], p.inputs['Sheen Tint'])
    L.new(gi.outputs['Subsurface'], p.inputs['Subsurface Weight']); p.inputs['Subsurface Scale'].default_value = 0.004
    L.new(gi.outputs['Coat'], p.inputs['Coat Weight']); p.inputs['Coat Roughness'].default_value = 0.08
    L.new(p.outputs[0], go.inputs['Shader'])
    return ng

import numpy as np
_scan = None
def scan_lum():
    global _scan
    if _scan is None:
        img = bpy.data.images['Image_0']; W, H = img.size
        px = np.array(img.pixels[:], np.float32).reshape(H, W, 4)[..., :3]
        _scan = (px @ np.array([0.2126, 0.7152, 0.0722], np.float32), W, H)
    return _scan
def part_mean(ob):
    # mean scan luminance over this part's own texels (face-centre UV samples)
    L, W, H = scan_lum(); me = ob.data
    n = len(me.loops); uv = np.zeros(n * 2, np.float32); me.uv_layers.active.data.foreach_get('uv', uv); uv = uv.reshape(-1, 2)
    xs = np.clip((uv[:, 0] % 1) * (W - 1), 0, W - 1).astype(int); ys = np.clip((uv[:, 1] % 1) * (H - 1), 0, H - 1).astype(int)
    v = L[ys, xs]
    # two-cluster split (dark vs light texels); normalise by the cluster that dominates the visible surface.
    # Faces are triangles of very different size, so weight by face area to avoid tiny dense islands winning.
    me.polygons.foreach_get  # (areas via polygon data)
    areas = np.zeros(len(me.polygons), np.float32); me.polygons.foreach_get('area', areas)
    lt = np.zeros(len(me.polygons), np.int32); me.polygons.foreach_get('loop_total', lt)
    w = np.repeat(areas / np.maximum(lt, 1), lt)
    thr = 0.3
    dark = v < thr; light = ~dark
    wd, wl = w[dark].sum(), w[light].sum()
    if wl >= wd * 0.6:                       # mostly (or substantially) light: normalise to the light cluster
        return float(np.average(v[light], weights=w[light])) if wl > 0 else 0.5
    return float(np.average(v[dark], weights=w[dark])) if wd > 0 else 0.1

def apply(ob, ng, color_hex, preset, detail, ink, force, edge_pair=None):
    m = ob.data.materials[0]; nt = m.node_tree; N = nt.nodes
    tex = next(n for n in N if n.type == 'TEX_IMAGE' and n.label == 'BASE COLOR')
    rtex = next(n for n in N if n.type == 'TEX_IMAGE' and n.label == 'METALLIC ROUGHNESS')
    out = next(n for n in N if n.type == 'OUTPUT_MATERIAL')
    for n in [n for n in N if n.type in ('GROUP', 'BSDF_PRINCIPLED', 'SEPARATE_COLOR')]: N.remove(n)
    g = N.new('ShaderNodeGroup'); g.node_tree = ng; g.label = 'SHOE MATERIAL'; g.location = (-200, 0)
    sep = N.new('ShaderNodeSeparateColor'); nt.links.new(rtex.outputs['Color'], sep.inputs[0]); nt.links.new(sep.outputs['Green'], g.inputs['Scan Roughness'])
    nt.links.new(tex.outputs['Color'], g.inputs['Scan Color'])
    btex = N.new('ShaderNodeTexImage'); btex.image = bpy.data.images['Image_0_blur']; btex.label = 'BASE COLOR BLUR'; btex.location = (tex.location.x, tex.location.y - 300)
    nt.links.new(btex.outputs['Color'], g.inputs['Scan Blur'])

    P = PRESETS[preset]
    g.inputs['Color'].default_value = (*hex2lin(color_hex), 1); g.inputs['Scan Detail'].default_value = 0.0 if force else detail
    g.inputs['Ink Threshold'].default_value = ink
    g.inputs['Roughness'].default_value = P['rough']; g.inputs['Specular'].default_value = P['spec']
    g.inputs['Sheen'].default_value = P['sheen']; g.inputs['Sheen Roughness'].default_value = P['sheen_r']
    g.inputs['Bump'].default_value = P['bump']; g.inputs['Grain Scale'].default_value = P['grain']
    g.inputs['Grain Kind'].default_value = {'noise': 0, 'voronoi': 1, 'weave': 2}[P['kind']]
    g.inputs['Subsurface'].default_value = P['sss']; g.inputs['Coat'].default_value = P['coat']; g.inputs['Edge Fuzz'].default_value = P['fuzz']
    if edge_pair:                                   # (dark colour, light colour) decided by the scan's own edge
        g.inputs['Color'].default_value = (*hex2lin(edge_pair[0]), 1); g.inputs['Light Color'].default_value = (*hex2lin(edge_pair[1]), 1); g.inputs['Edge Mode'].default_value = 1.0
        g.inputs['Light Roughness'].default_value = _up['rough']; g.inputs['Light Sheen'].default_value = _up['sheen']; g.inputs['Light Specular'].default_value = _up['spec']
    nt.links.new(g.outputs['Shader'], out.inputs['Surface'])
    m['preset'] = preset; m['color'] = color_hex
    m.diffuse_color = (*hex2lin(color_hex), 1)

def make_blur(radius=4):
    if 'Image_0_blur' in bpy.data.images: return
    img = bpy.data.images['Image_0']; W, H = img.size
    a = np.array(img.pixels[:], np.float32).reshape(H, W, 4)
    def box(x, r):
        for ax in (0, 1):
            c = np.cumsum(np.pad(x, [(r + 1, r) if i == ax else (0, 0) for i in range(x.ndim)], mode='edge'), axis=ax)
            x = (np.take(c, range(2 * r + 1, c.shape[ax]), axis=ax) - np.take(c, range(0, c.shape[ax] - 2 * r - 1), axis=ax)) / (2 * r + 1)
        return x
    b = box(box(a, radius), max(1, radius // 2))
    out = bpy.data.images.new('Image_0_blur', W, H, alpha=True, float_buffer=False)
    out.colorspace_settings.name = img.colorspace_settings.name
    out.pixels[:] = np.clip(b, 0, 1).ravel(); out.pack()
make_blur()
ng = build_group()
# the upper and the dark panels share stair-stepped mesh borders; let the scan's edge place the colour change
EDGE_PARTS = {'upper', 'toe_cap'} | {f'triangle_{i}.{s}' for i in (1, 2, 3, 4) for s in 'LR'}
upper_col = CW['parts'].get('upper', {}).get('color', '#f1f1f3'); panel_col = CW['parts'].get('triangle_1.L', {}).get('color', '#141416')
def _lum(h): r, g, b = hex2lin(h); return 0.2126 * r + 0.7152 * g + 0.0722 * b
if abs(_lum(upper_col) - _lum(panel_col)) < 0.05: EDGE_PARTS = set()     # same-tone colorway (e.g. blackout): no scan-edge switching
# in edge mode the light side takes the *upper's* preset values, not fixed leather numbers
_up = PRESETS[CW['parts'].get('upper', {}).get('material', 'leather')]
for ob in [o for o in bpy.data.objects if o.type == 'MESH']:
    spec = CW['parts'].get(ob.name, {})
    pair = (panel_col, upper_col) if (ob.name in EDGE_PARTS and not spec.get('force')) else None
    apply(ob, ng, spec.get('color', '#cccccc'), spec.get('material', DEFAULT_MATERIAL.get(ob.name, 'leather')),
          spec.get('detail', 0.6), spec.get('ink', 0.0), spec.get('force', False), pair)
    print(f"  {ob.name:16s} {spec.get('material', DEFAULT_MATERIAL.get(ob.name, 'leather')):8s} {spec.get('color', '#cccccc')}")
bpy.ops.wm.save_as_mainfile(filepath=OUT); print('SAVED', OUT)
