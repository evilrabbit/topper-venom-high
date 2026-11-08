# Merge the seam-traced parts into the designer part library (named, L/R where it matters), one object per part.
#   blender -b shoe-seams-clean.blend --python build_library.py -- OUT.blend
import bpy, sys
OUT = sys.argv[sys.argv.index('--') + 1]
LIB = {
 'upper':            ['side_frame.L', 'side_frame.L.2', 'heel_overlay', 'heel_wedge', 'heel_wedge.2', 'heel_wedge.3', 'heel_wedge.4', 'heel_wedge.5', 'toe_cap.3'],
 'toe_cap':          ['toe_cap', 'toe_cap.2', 'forefoot_panel.R', 'vamp', 'vamp.2', 'vamp.5'],
 'vamp_panel':       ['vamp.3', 'vamp.4'],
 'triangle_1.L':     ['side_triangle_top.L'],    'triangle_1.R': ['side_triangle_top.R'],
 'triangle_2.L':     ['side_triangle_upper.L'],  'triangle_2.R': ['side_triangle_upper.R', 'side_triangle_upper.R.2'],
 'triangle_3.L':     ['side_triangle_lower.L', 'side_triangle_lower.L.2'], 'triangle_3.R': ['side_triangle_lower.R'],
 'triangle_4.L':     ['side_triangle_front.L'],  'triangle_4.R': ['side_triangle_front.R'],
 'collar':           ['collar', 'collar.2'],
 'heel_tab':         ['heel_pull_tab'],
 'tongue':           ['tongue'],
 'tongue_badge':     ['tongue_logo'],
 'laces':            ['laces'],
 'lining':           ['lining'],
 'midsole':          ['midsole', 'midsole.3', 'midsole.4'],
 'heel_plate':       ['midsole.2'],
 'outsole':          ['outsole', 'outsole.2', 'outsole.4', 'outsole.5', 'outsole.6', 'outsole.8', 'outsole.10', 'outsole.11'],
 'heel_ribs':        ['outsole.3', 'outsole.7', 'outsole.9'],
 'toe_bumper':       ['toe_bumper', 'toe_bumper.2'],
 'window_frame':     ['sole_window_front', 'sole_window_mid', 'sole_window_mid.2'],
}
have = {o.name for o in bpy.data.objects if o.type == 'MESH'}
used = {s for v in LIB.values() for s in v}
missing = used - have; unused = have - used
assert not missing, f'missing sources: {missing}'
assert not unused, f'unassigned parts: {unused}'
for name, srcs in LIB.items():
    objs = [bpy.data.objects[s] for s in srcs]
    for o in bpy.data.objects: o.select_set(False)
    for o in objs: o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    if len(objs) > 1: bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    mat = ob.data.materials[0].copy(); mat.name = 'part_' + name
    ob.data.materials.clear(); ob.data.materials.append(mat)
    ob.name = name; ob.data.name = name
for m in list(bpy.data.materials):
    if m.users == 0: bpy.data.materials.remove(m)
parts = sorted((o.name, len(o.data.polygons)) for o in bpy.data.objects if o.type == 'MESH')
print('LIBRARY', len(parts), 'parts')
for n, f in parts: print(f'  {n:16s} {f:7d}')
bpy.ops.wm.save_as_mainfile(filepath=OUT); print('SAVED', OUT)
