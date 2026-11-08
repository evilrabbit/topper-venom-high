# Smooth shading for the scan: auto-smooth normals (keeps real creases sharp) + a light normal smoothing
# so glossy materials do not reveal the scan's per-face shading.   blender -b in.blend --python smooth_normals.py -- OUT.blend
import bpy, sys
OUT = sys.argv[sys.argv.index('--') + 1]
for o in [o for o in bpy.data.objects if o.type == 'MESH']:
    bpy.context.view_layer.objects.active = o
    for ob in bpy.data.objects: ob.select_set(False)
    o.select_set(True)
    bpy.ops.object.shade_smooth()
    # Blender 4.1+/5: smooth-by-angle is a modifier; keep sharp edges above 40°
    bpy.ops.object.shade_smooth_by_angle(angle=0.698)
    # Corrective smooth with a few iterations evens the normals without moving the silhouette
    m = o.modifiers.new('normals', 'CORRECTIVE_SMOOTH'); m.iterations = 4; m.factor = 0.6; m.use_only_smooth = True; m.use_pin_boundary = True
print('smoothed', len([o for o in bpy.data.objects if o.type == 'MESH']))
bpy.ops.wm.save_as_mainfile(filepath=OUT); print('SAVED', OUT)
