import bpy
from mathutils import Vector
sc=bpy.context.scene; sc.render.engine='BLENDER_WORKBENCH'
sh=sc.display.shading; sh.light='STUDIO'; sh.color_type='OBJECT'
for o in bpy.data.objects:
    if o.type=='MESH': o.color=(1,0,0,1) if o.name=='outsole' else ((0,0.3,1,1) if o.name=='midsole' else (0.9,0.9,0.9,1))
sc.render.resolution_x=1152; sc.render.resolution_y=864; sc.render.film_transparent=False
cam=bpy.data.objects.new('cam',bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera=cam
for k,v in {'side':(-2.6,0,0.25),'other':(2.6,0,0.25)}.items():
    cam.location=v; cam.rotation_euler=(Vector((0,0,-0.03))-Vector(v)).to_track_quat('-Z','Y').to_euler()
    sc.render.filepath=f'/tmp/shoe-parts/flat_{k}.png'; bpy.ops.render.render(write_still=True)
