from __future__ import annotations

import sys

import bmesh
import bpy
from mathutils import Matrix, Vector


def parse_args() -> tuple[str, str, int, float]:
    if "--" not in sys.argv:
        raise RuntimeError("expected blender args after --")
    raw = sys.argv[sys.argv.index("--") + 1 :]
    if len(raw) != 4:
        raise RuntimeError(
            "usage: blender -b --python clean_asset.py -- <input_glb> <output_glb> "
            "<target_tris> <remove_doubles_dist>"
        )
    input_glb, output_glb, target_tris, remove_doubles_dist = raw
    return input_glb, output_glb, int(target_tris), float(remove_doubles_dist)


def main() -> int:
    input_glb, output_glb, target_tris, remove_doubles_dist = parse_args()
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=input_glb)
    mesh_objs = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not mesh_objs:
        raise RuntimeError("no MESH objects were imported from GLB")

    failed_meshes: list[str] = []
    remeshed = False
    for obj in mesh_objs:
        try:
            processed, used_remesh = process_mesh(obj, target_tris, remove_doubles_dist)
            remeshed = remeshed or used_remesh
            if not processed:
                print(f"EMPTY_MESH: {obj.name}")
        except Exception as exc:  # noqa: BLE001
            failed_meshes.append(obj.name)
            print(f"FAILED_MESH: {obj.name}: {exc}")

    if remeshed:
        print("REMESHED:true")

    bpy.ops.export_scene.gltf(
        filepath=output_glb,
        export_format="GLB",
        export_yup=True,
        export_apply=True,
    )
    return 1 if failed_meshes else 0


def process_mesh(obj: bpy.types.Object, target_tris: int, remove_doubles_dist: float) -> tuple[bool, bool]:
    with bpy.context.temp_override(
        object=obj,
        active_object=obj,
        selected_objects=[obj],
        selected_editable_objects=[obj],
    ):
        bpy.ops.object.make_single_user(object=True, obdata=True)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

    if obj.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    used_remesh = cleanup_mesh_geometry(obj, remove_doubles_dist)
    move_origin_to_bottom_center(obj)
    decimated = apply_decimate_modifier(obj, target_tris)
    return decimated, used_remesh


def cleanup_mesh_geometry(obj: bpy.types.Object, remove_doubles_dist: float) -> bool:
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.normal_update()
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=remove_doubles_dist)
    non_manifold_edges = [edge for edge in bm.edges if not edge.is_manifold]
    bm.to_mesh(mesh)
    bm.free()

    if not non_manifold_edges:
        mesh.update()
        return False

    modifier = obj.modifiers.new(name="VoxelRemeshFallback", type="REMESH")
    modifier.mode = "VOXEL"
    modifier.voxel_size = estimate_voxel_size(obj)
    modifier.adaptivity = 0.0
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    eval_mesh = eval_obj.to_mesh()
    try:
        if len(eval_mesh.vertices) == 0:
            raise RuntimeError("voxel remesh produced empty mesh")
        new_mesh = bpy.data.meshes.new(f"{obj.name}_remeshed")
        new_mesh.from_mesh(eval_mesh)
    finally:
        eval_obj.to_mesh_clear()
    old_mesh = obj.data
    obj.modifiers.clear()
    obj.data = new_mesh
    bpy.data.meshes.remove(old_mesh)
    obj.data.update()
    return True


def estimate_voxel_size(obj: bpy.types.Object) -> float:
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    min_corner = Vector(
        (min(v.x for v in corners), min(v.y for v in corners), min(v.z for v in corners))
    )
    max_corner = Vector(
        (max(v.x for v in corners), max(v.y for v in corners), max(v.z for v in corners))
    )
    diag = (max_corner - min_corner).length
    return max(diag / 256.0, 0.001)


def move_origin_to_bottom_center(obj: bpy.types.Object) -> None:
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    min_x = min(v.x for v in corners)
    max_x = max(v.x for v in corners)
    min_y = min(v.y for v in corners)
    max_y = max(v.y for v in corners)
    min_z = min(v.z for v in corners)
    origin_world = Vector(((min_x + max_x) / 2.0, (min_y + max_y) / 2.0, min_z))
    local_origin = obj.matrix_world.inverted() @ origin_world
    obj.data.transform(Matrix.Translation(-local_origin))
    obj.matrix_world.translation = origin_world
    obj.data.update()


def apply_decimate_modifier(obj: bpy.types.Object, target_tris: int) -> bool:
    current_tris = triangle_count(obj.data)
    if current_tris <= 0:
        return False
    if current_tris <= target_tris:
        return True

    ratio = max(min(target_tris / current_tris, 1.0), 0.01)
    modifier = obj.modifiers.new(name="Decimate", type="DECIMATE")
    modifier.ratio = ratio
    modifier.use_collapse_triangulate = True
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    eval_mesh = eval_obj.to_mesh()
    try:
        if len(eval_mesh.vertices) == 0:
            return False
        new_mesh = bpy.data.meshes.new(f"{obj.name}_decimated")
        new_mesh.from_mesh(eval_mesh)
    finally:
        eval_obj.to_mesh_clear()
    old_mesh = obj.data
    obj.modifiers.clear()
    obj.data = new_mesh
    bpy.data.meshes.remove(old_mesh)
    obj.data.update()
    return True


def triangle_count(mesh: bpy.types.Mesh) -> int:
    tris = 0
    for poly in mesh.polygons:
        tris += max(len(poly.vertices) - 2, 0)
    return tris


if __name__ == "__main__":
    sys.exit(main())
