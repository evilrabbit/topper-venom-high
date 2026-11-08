# Blender (headless): import the scan, bake object-space position + normal into its UV atlas.
import bpy, sys, os
OUT = '/tmp/topper-blender'
RES = 2048

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath='/tmp/shoe-blender.glb')
obj = [o for o in bpy.context.scene.objects if o.type == 'MESH'][0]
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
# apply transforms so object space == glTF source space (Blender converts Y-up -> Z-up on import)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

import mathutils
bb = [mathutils.Vector(c) for c in obj.bound_box]
mn = mathutils.Vector((min(v.x for v in bb), min(v.y for v in bb), min(v.z for v in bb)))
mx = mathutils.Vector((max(v.x for v in bb), max(v.y for v in bb), max(v.z for v in bb)))
print('BBOX', tuple(mn), tuple(mx))

scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 1
scene.render.bake.margin = 8

mat = obj.active_material
nt = mat.node_tree
nodes, links = nt.nodes, nt.links
out = [n for n in nodes if n.type == 'OUTPUT_MATERIAL'][0]
orig_surface = out.inputs['Surface'].links[0].from_socket if out.inputs['Surface'].links else None

def bake(name, build):
    img = bpy.data.images.new(name, RES, RES, alpha=False, float_buffer=True)
    img.colorspace_settings.name = 'Non-Color'
    tex = nodes.new('ShaderNodeTexImage'); tex.image = img
    for n in nodes: n.select = False
    tex.select = True; nodes.active = tex
    emit = nodes.new('ShaderNodeEmission')
    build(emit)
    links.new(emit.outputs[0], out.inputs['Surface'])
    bpy.ops.object.bake(type='EMIT')
    img.filepath_raw = os.path.join(OUT, name + '.exr')
    img.file_format = 'OPEN_EXR'
    img.save()
    nodes.remove(tex); nodes.remove(emit)

def pos(emit):
    geo = nodes.new('ShaderNodeNewGeometry')
    # normalized 0..1 inside the bbox
    sub = nodes.new('ShaderNodeVectorMath'); sub.operation = 'SUBTRACT'; sub.inputs[1].default_value = mn
    div = nodes.new('ShaderNodeVectorMath'); div.operation = 'DIVIDE'; div.inputs[1].default_value = mx - mn
    tc = nodes.new('ShaderNodeTexCoord')
    links.new(tc.outputs['Object'], sub.inputs[0])
    links.new(sub.outputs[0], div.inputs[0])
    links.new(div.outputs[0], emit.inputs['Color'])

def nrm(emit):
    tc = nodes.new('ShaderNodeTexCoord')
    # object-space normal via Geometry normal transformed to object space
    geo = nodes.new('ShaderNodeNewGeometry')
    vt = nodes.new('ShaderNodeVectorTransform'); vt.vector_type = 'NORMAL'
    vt.convert_from = 'WORLD'; vt.convert_to = 'OBJECT'
    links.new(geo.outputs['Normal'], vt.inputs[0])
    m = nodes.new('ShaderNodeVectorMath'); m.operation = 'MULTIPLY_ADD'
    m.inputs[1].default_value = (0.5, 0.5, 0.5); m.inputs[2].default_value = (0.5, 0.5, 0.5)
    links.new(vt.outputs[0], m.inputs[0])
    links.new(m.outputs[0], emit.inputs['Color'])

bake('pos', pos)
bake('nrm', nrm)
if orig_surface: links.new(orig_surface, out.inputs['Surface'])
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 'shoe.blend'))
print('BAKED')
