"""Connected, dimensioned prototype mounting parts for Mianguang PCB V0.2.

All construction coordinates are mm; helpers supplied by build_enclosure_v02.py
convert to Blender metres. This module does not save, export or change scenes.
"""
import math
import bpy
from mathutils import Vector


def build_mount(api):
    rr, box, cyl = (api[k] for k in ('rr', 'box', 'cyl'))
    boolean, bevel = api['boolean'], api['bevel']
    white, rubber, metal = (api[k] for k in ('white', 'rubber', 'metal'))
    bodycol, standcol, wallcol = (api[k] for k in ('bodycol', 'standcol', 'wallcol'))
    parts = api['parts']
    pivot = Vector((0., 34., 90.))

    def union(obj, other):
        boolean(obj, other, 'UNION')

    def hex_prism(name, af, depth, loc, coll, axis='Y', material=None):
        bpy.ops.mesh.primitive_cylinder_add(vertices=6, radius=af / math.sqrt(3) / 1000,
                                          depth=depth / 1000, location=Vector(loc) / 1000)
        obj = bpy.context.object
        obj.name = 'SR02_' + name
        if axis == 'Y':
            obj.rotation_euler[0] = math.pi / 2
        elif axis == 'X':
            obj.rotation_euler[1] = math.pi / 2
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        for c in list(obj.users_collection):
            c.objects.unlink(obj)
        coll.objects.link(obj)
        if material:
            obj.data.materials.append(material)
        return obj

    def rib(name, yz, halfwidth, coll):
        vertices = [(x / 1000, y / 1000, z / 1000)
                    for x in (-halfwidth, halfwidth) for y, z in yz]
        mesh = bpy.data.meshes.new('SR02_' + name + '_mesh')
        mesh.from_pydata(vertices, [], [(2, 1, 0), (3, 4, 5),
                                       (0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5)])
        mesh.update()
        obj = bpy.data.objects.new('SR02_' + name, mesh)
        coll.objects.link(obj)
        return obj

    def rotate_about_pivot(obj, angle):
        a = math.radians(angle)
        p = obj.location * 1000 - pivot
        obj.location = (pivot + Vector((p.x, p.y * math.cos(a) - p.z * math.sin(a),
                                       p.y * math.sin(a) + p.z * math.cos(a)))) / 1000
        obj.rotation_euler[0] = a
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

    # Moving yoke. M3 screws enter from inside the enclosure; nuts slide in
    # from the outside edges so no screwdriver must pass through a pivot ear.
    dock = rr('07_Common_Dock_Yoke', 44, 30, 4, 5, (0, 24, 90), white,
              bodycol, edge=0)
    for x in (-18, 18):
        union(dock, box('Dock_Ear_Web', (6, 8.4, 16), (x, 30, 90),
                        None, bodycol, edge=0))
        union(dock, cyl('Dock_Ear_Round', 8, 6, (x, 34, 90), None,
                        bodycol, axis='X', edge=0))
    for x in (-16, 16):
        union(dock, box('M3_Nut_Boss', (10, 4.2, 10), (x, 26.9, 90),
                        None, bodycol, edge=0))
        boolean(dock, hex_prism('M3_Nut_Pocket', 5.7, 2.7, (x, 26.15, 90), bodycol))
        # Side slot is exactly the nut's across-flats height; open to side edge.
        side = 1 if x > 0 else -1
        boolean(dock, box('M3_Side_Nut_Entry', (14, 2.7, 5.7),
                          (side * 23, 26.15, 90), None, bodycol, edge=0))
        boolean(dock, cyl('M3_Clearance_Blind', 1.7, 8.8, (x, 25.1, 90),
                          None, bodycol, edge=0))
        nut = hex_prism('M3_Dock_Captive_Nut', 5.5, 2.4, (x, 26.15, 90),
                        bodycol, material=metal)
        boolean(nut, cyl('M3_Nut_Thread_Envelope', 1.5, 4, (x, 26.15, 90),
                         None, bodycol, edge=0))
        nut['hardware'] = 'M3 hex nut, AF5.5 x 2.4; threads shown as a clearance envelope'
    # An outboard tab mates with both sets of angular travel stops.
    union(dock, box('Moving_Stop_Tab', (6.4, 10.5, 3), (23.8, 45.25, 90),
                    None, bodycol, edge=0))
    boolean(dock, cyl('Dock_M4_Axle', 2.2, 60, (0, 34, 90), None,
                      bodycol, axis='X', edge=0))
    # Keep stop faces and bearing bores exact; no final bevel changes the
    # intended contact angles or reduces the nut-entry clearance.
    dock['mount_holes_mm'] = 'M3 clearance 3.4 at X +/-16, Z90; blind end Y29.5'
    dock['nut_pocket_mm'] = 'AF5.7, thickness2.7, centreY26.15; sideways insertion'
    dock['pivot_mm'] = [0., 34., 90.]
    dock['retention'] = 'M3x10 from shell inside; M4x50 axle plus M4 locknut'
    dock['part_role'] = 'printable'
    dock['fit_note'] = 'M3 side-loading nut pockets and M4 pivot holes; print-fit and pullout load remain untested'
    parts.append(dock)

    def centre_lug(obj, coll, label):
        # Full-radius central hub clears the rotating backplate by 0.3mm.
        # Reduced end shoulders clear the inward edges of the M3 nut bosses
        # (minimum swept radius 5mm at X11..14); do not use an unrelieved
        # 28mm-wide, R8 cylinder here.
        union(obj, cyl(label + '_Centre_Hub', 7.7, 20, (0, 34, 90), None,
                       coll, axis='X', edge=0))
        for x in (-11.9, 11.9):
            union(obj, cyl(label + '_Relieved_Shoulder', 4.5, 4.2, (x, 34, 90),
                           None, coll, axis='X', edge=0))

    def travel_stops(obj, coll, limit, label):
        # Positive stop: its lower face becomes coplanar with the moving
        # tab's +Z face at the chosen angle. It remains outside the yoke ear.
        stop = box(label + '_Upper_Stop', (5.6, 9, 4), (24.3, 46.5, 93.5),
                   None, coll, edge=0)
        rotate_about_pivot(stop, limit)
        # Taller/rear bridges are outside the tab's swept radius (16.57mm).
        bridge_z = 102 if limit <= 30 else 105
        front_y = 47 if limit <= 30 else 43.5
        union(obj, box(label + '_Stop_Rear_Bridge', (28, 8, 8),
                       (14, 55, bridge_z), None, coll, edge=0))
        union(obj, box(label + '_Stop_Rear_Post', (16, 8, bridge_z - 94 + 4),
                       (0, 55, (94 + bridge_z + 4) / 2), None, coll, edge=0))
        union(obj, box(label + '_Stop_Side_Link', (5.6, 53 - front_y, 4),
                       (24.3, (53 + front_y) / 2, bridge_z + 1),
                       None, coll, edge=0))
        union(obj, stop)
        # Neutral (0deg) lower stop is also connected from the rear.
        union(obj, box(label + '_Zero_Stop_Bridge', (28, 8, 5), (14, 55, 85),
                       None, coll, edge=0))
        union(obj, box(label + '_Zero_Stop_Link', (5.6, 11, 4), (24.3, 48, 86.5),
                       None, coll, edge=0))
        union(obj, box(label + '_Zero_Stop_Contact', (5.6, 9, 4), (24.3, 46.5, 86.5),
                       None, coll, edge=0))
        obj['angular_range_deg'] = [0, limit]
        obj['stop_note'] = 'Geometric hard stops; verify tolerance and locking torque on a printed sample'

    # Desktop support is one connected print. The rearward upright clears the
    # enclosure sweep. At 30deg the front/bottom corner is at Z10.97 versus
    # the base top Z7, leaving 3.97mm nominal (front Y=-23.6, bottom Z32).
    desk = rr('08_Desk_Stand_Base', 100, 120, 5, 20, (0, 22, 4.5),
              white, standcol, edge=0)
    desk.rotation_euler[0] = math.pi / 2
    bpy.ops.object.select_all(action='DESELECT')
    desk.select_set(True)
    bpy.context.view_layer.objects.active = desk
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    union(desk, box('Desk_Rear_Upright', (24, 8, 85), (0, 78, 48.5),
                    None, standcol, edge=0))
    union(desk, rib('Desk_Foot_Gusset', [(51, 6), (80, 6), (80, 35)], 10, standcol))
    union(desk, box('Desk_Top_Arm', (16, 48, 14), (0, 58, 90),
                    None, standcol, edge=0))
    centre_lug(desk, standcol, 'Desk')
    travel_stops(desk, standcol, 30, 'Desk')
    boolean(desk, cyl('Desk_M4_Axle', 2.2, 60, (0, 34, 90), None,
                      standcol, axis='X', edge=0))
    # Foot pockets receive 1mm of each 3mm adhesive silicone disc.
    for x in (-33, 33):
        for y in (-13, 57):
            boolean(desk, cyl('Foot_Recess', 6.1, 1.1, (x, y, 2.45), None,
                              standcol, axis='Z', edge=0))
            foot = cyl('Desk_Silicone_Foot', 6, 3, (x, y, 1.5), rubber,
                       standcol, axis='Z', edge=.1)
            foot['hardware'] = 'Four adhesive silicone discs, diameter12 x 3mm'
    desk['base_mm'] = [100., 120., 5.]
    desk['base_centre_mm'] = [0., 22., 4.5]
    desk['stand_note'] = 'Single connected print; 5mm base. Tip resistance and creep not yet measured.'
    desk['part_role'] = 'printable'
    desk['fit_note'] = '0 to 30deg hard stops; rear upright clears body sweep; verify foot fit, holding torque and stability'
    parts.append(desk)

    # Wall support is likewise connected; wall plane is Y95. Two keyholes
    # carry weight and a third lower screw prevents accidental lifting.
    wall = rr('09_Wall_Bracket_Plate', 68, 88, 5, 10, (0, 92.5, 90),
              white, wallcol, edge=0)
    union(wall, box('Wall_Arm', (16, 58, 14), (0, 63, 90), None, wallcol, edge=0))
    union(wall, box('Wall_Rear_Reinforcement', (34, 12, 26), (0, 86, 90),
                    None, wallcol, edge=0))
    union(wall, rib('Wall_Lower_Gusset', [(68, 84), (92, 84), (92, 72)], 12, wallcol))
    union(wall, rib('Wall_Upper_Gusset', [(68, 96), (92, 96), (92, 108)], 12, wallcol))
    centre_lug(wall, wallcol, 'Wall')
    travel_stops(wall, wallcol, 45, 'Wall')
    boolean(wall, cyl('Wall_M4_Axle', 2.2, 60, (0, 34, 90), None,
                      wallcol, axis='X', edge=0))
    for entry_z in (62, 118):
        boolean(wall, cyl('Keyhole_Entry', 4.25, 12, (0, 92.5, entry_z),
                          None, wallcol, edge=0))
        boolean(wall, box('Keyhole_Neck', (4.5, 12, 8), (0, 92.5, entry_z + 4),
                          None, wallcol, edge=0))
        boolean(wall, cyl('Keyhole_Seat', 2.25, 12, (0, 92.5, entry_z + 8),
                          None, wallcol, edge=0))
    boolean(wall, cyl('Wall_Anti_Lift_Screw', 2.25, 12, (0, 92.5, 52),
                      None, wallcol, edge=0))
    boolean(wall, cyl('Wall_Lock_Head_Recess', 4.25, 2.2, (0, 91, 52),
                      None, wallcol, edge=0))
    wall['wall_plane_y_mm'] = 95.
    wall['keyhole_seat_centres_mm'] = [[0., 95., 70.], [0., 95., 126.]]
    wall['wall_mount_pitch_mm'] = 56.
    wall['wall_lock_hole_mm'] = [0., 95., 52.]
    wall['installation'] = 'Two M4 pan-head anchor screws, then lower M4 anti-lift screw. Anchors chosen for wall substrate.'
    wall['part_role'] = 'printable'
    wall['fit_note'] = '0 to 45deg hard stops; keyholes plus anti-lift screw; verify actual anchor heads and wall strength'
    parts.append(wall)

    hardware = {}
    for label, coll in (('Desk', standcol), ('Wall', wallcol)):
        members = []
        for x in (-14.5, 14.5):
            washer = cyl(label + '_Friction_Washer', 4.5, 1, (x, 34, 90), rubber,
                         coll, axis='X', edge=0)
            boolean(washer, cyl('Washer_Bore', 2.2, 3, (x, 34, 90), None,
                                coll, axis='X', edge=0))
            members.append(washer)
            washer['hardware'] = 'Fibre/polymer friction washer OD9 x ID4.4 x 1mm; verify holding torque'
        bolt = cyl(label + '_M4x50_Axle_Shank', 2, 50, (4, 34, 90), metal,
                   coll, axis='X', edge=0)
        members.append(bolt)
        head = cyl(label + '_M4_Axle_Head', 3.5, 4, (-23, 34, 90), metal,
                   coll, axis='X', edge=.15)
        boolean(head, hex_prism('M4_Head_Hex', 3.1, 2.5, (-24.2, 34, 90), coll, axis='X'))
        members.append(head)
        washer = cyl(label + '_M4_Outer_Washer', 4.5, .8, (21.4, 34, 90), metal,
                     coll, axis='X', edge=0)
        boolean(washer, cyl('Outer_Washer_Bore', 2.2, 3, (21.4, 34, 90), None,
                            coll, axis='X', edge=0))
        members.append(washer)
        nut = hex_prism(label + '_M4_Locknut_Envelope', 7, 5, (24.3, 34, 90),
                        coll, axis='X', material=metal)
        boolean(nut, cyl('M4_Nut_Bore', 2, 7, (24.3, 34, 90), None,
                         coll, axis='X', edge=0))
        nut['hardware'] = 'M4 prevailing-torque nut, AF7 x 5mm envelope; verify purchased SKU'
        members.append(nut)
        hardware[label.lower()] = members

    return {
        'dock': dock, 'desk': desk, 'wall': wall, 'hardware': hardware,
        'pivot_mm': tuple(pivot), 'desk_angle_range_deg': (0, 30),
        'wall_angle_range_deg': (0, 45),
        'dock_mount_centres_mm': [(-16., 22., 90.), (16., 22., 90.)],
        'wall_plane_y_mm': 95.,
    }
