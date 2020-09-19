"""
Module for handling Super Mario Galaxy collision files.

See http://wiki.tockdom.com/wiki/KCL_%28File_Format%29 for a description of the
MKW KCL file format.
"""

from math import sqrt,log,ceil
from collections import OrderedDict
from btypes import *
import bcsv

class GeometryOverflowError(Exception): pass

#------------------------------------------------------------------------------

class Vector(Struct):
    x = float32
    y = float32
    z = float32

    __slots__ = ('x','y','z')

    def __init__(self,x=0,y=0,z=0):
        self.x = x
        self.y = y
        self.z = z

    def __pos__(self):
        return self

    def __neg__(self):
        return Vector(-self.x,-self.y,-self.z)

    def __add__(self,other):
        return Vector(self.x + other.x,self.y + other.y,self.z + other.z)

    def __sub__(self,other):
        return Vector(self.x - other.x,self.y - other.y,self.z - other.z)

    def __mul__(self,scalar):
        return Vector(self.x*scalar,self.y*scalar,self.z*scalar)

    def __rmul__(self,scalar):
        return Vector(scalar*self.x,scalar*self.y,scalar*self.z)

    def __truediv__(self,scalar):
        return Vector(self.x/scalar,self.y/scalar,self.z/scalar)

    def norm_square(self):
        return self.x*self.x + self.y*self.y + self.z*self.z

    def norm(self):
        return sqrt(self.norm_square())

    def unit(self):
        return self/self.norm()

def dot(a,b):
    return a.x*b.x + a.y*b.y + a.z*b.z

def cross(a,b):
    return Vector(a.y*b.z - a.z*b.y,a.z*b.x - a.x*b.z,a.x*b.y - a.y*b.x)


class Triangle:

    def __init__(self,u,v,w,group_index):
        self.u = u
        self.v = v
        self.w = w
        self.n = cross(v - u,w - u).unit()
        self.group_index = group_index


class SurfaceType:

    def __init__(self):
        self.camera_id = 0xFF
        self.sound_code = 0
        self.floor_code = 0
        self.wall_code = 0
        self.camera_through = False


class SurfaceTypeList(bcsv.ObjectList):
    camera_id = bcsv.Field(bcsv.UINT32,'camera_id',0,0x000000FF,0)
    sound_code = bcsv.Field(bcsv.UINT32,'Sound_code',0,0x00007F00,8)
    floor_code = bcsv.Field(bcsv.UINT32,'Floor_code',0,0x01F8000,15)
    wall_code = bcsv.Field(bcsv.UINT32,'Wall_code',0,0x01E00000,21)
    camera_through = bcsv.Field(bcsv.UINT32,'Camera_through',0,0x02000000,25)


SOUND_CODES = ['null','Soil','Lawn','Stone','Marble','Wood Thick','Wood Thin',
        'Metal','Snow','Ice','Shallow','Beach','unknown','Carpet','Mud',
        'Honey','Metal Heavy','Marble Snow','Marble Soil','Metal Soil','Cloud',
        'Marble Beach','Marble Sand']

FLOOR_CODES = ['Normal','Death','Slip','No Slip','Damage Normal','Ice',
        'Jump Low','Jump Middle','Jump High','Slider','Damage Fire',
        'Jump Normal','Fire Dance','Sand','Glass','Damage Electric',
        'Pull Back','Sink','Sink Poison','Slide','Water Bottom H',
        'Water Bottom M','Water Bottom L','Shallow','Needle','Sink Death',
        'Snow','Rail Move','Area Move','Press','No Stamp Sand',
        'Sink Death Mud','Brake','Glass Ice','Jump Parasol','unknown','No Dig',
        'Lawn','Cloud','Press And No Slip','Force Dash','Dark Matter','Dust',
        'Snow And No Slip']

WALL_CODES = ['Normal','Not Wall Jump','Not Wall Slip','Not Grap',
        'Ghost Through','Not Side Step','Rebound','Honey','No Action']

###############################################################################
#                               Vertex Welder
###############################################################################

class VertexWelder:

    # Three randomly chosen large primes
    magic_x = 0x8DA6B343
    magic_y = 0xD8163841
    magic_z = 0x61B40079

    def __init__(self,threshold,bucket_count):
        self.threshold = threshold
        self.cell_width = 16*threshold
        self.buckets = [[] for _ in range(bucket_count)]
        self.vertices = []

    def calculate_hash(self,ix,iy,iz):
        return (ix*self.magic_x + iy*self.magic_y + iz*self.magic_z) % len(self.buckets)

    def add(self,vertex):
        min_ix = int((vertex.x - self.threshold)/self.cell_width)
        min_iy = int((vertex.y - self.threshold)/self.cell_width)
        min_iz = int((vertex.z - self.threshold)/self.cell_width)
        max_ix = int((vertex.x + self.threshold)/self.cell_width)
        max_iy = int((vertex.y + self.threshold)/self.cell_width)
        max_iz = int((vertex.z + self.threshold)/self.cell_width)

        for ix in range(min_ix,max_ix + 1):
            for iy in range(min_iy,max_iy + 1):
                for iz in range(min_iz,max_iz + 1):
                    bucket = self.buckets[self.calculate_hash(ix,iy,iz)]
                    for index in bucket:
                        if (abs(vertex.x - self.vertices[index].x) < self.threshold and
                                abs(vertex.y - self.vertices[index].y) < self.threshold and
                                abs(vertex.z - self.vertices[index].z) < self.threshold):
                            return index

        self.vertices.append(vertex)
        ix = int(vertex.x/self.cell_width)
        iy = int(vertex.y/self.cell_width)
        iz = int(vertex.z/self.cell_width)
        bucket = self.buckets[self.calculate_hash(ix,iy,iz)]
        bucket.append(len(self.vertices) - 1)
        return len(self.vertices) - 1

###############################################################################
#                                   Octree
###############################################################################

def tribox_overlap(triangle,center,half_width):
    """Intersection test for triangle and axis-aligned cube.

    Test if the triangle intersects the axis-aligned cube given by center and
    half width. This algorithm is an adapted version of the algorithm presented
    here:
    http://fileadmin.cs.lth.se/cs/Personal/Tomas_Akenine-Moller/code/tribox3.txt
    """

    # The Vector subtraction operation is slow so we avoid using it here

    u_x = triangle.u.x - center.x
    u_y = triangle.u.y - center.y
    u_z = triangle.u.z - center.z
    v_x = triangle.v.x - center.x
    v_y = triangle.v.y - center.y
    v_z = triangle.v.z - center.z
    w_x = triangle.w.x - center.x
    w_y = triangle.w.y - center.y
    w_z = triangle.w.z - center.z

    # Test for separation along the axes normal to the faces of the cube
    if ((u_x < -half_width and v_x < -half_width and w_x < -half_width) or
            (u_x > half_width and v_x > half_width and w_x > half_width) or
            (u_y < -half_width and v_y < -half_width and w_y < -half_width) or
            (u_y > half_width and v_y > half_width and w_y > half_width) or
            (u_z < -half_width and v_z < -half_width and w_z < -half_width) or
            (u_z > half_width and v_z > half_width and w_z > half_width)):
        return False

    # Test for separation along the axis normal to the face of the triangle
    n = triangle.n
    d = n.x*u_x + n.y*u_y + n.z*u_z
    r = half_width*(abs(n.x) + abs(n.y) + abs(n.z))
    if d < -r or d > r:
        return False

    # Test for separation along the axes parallel to the cross products of the
    # edges of the triangle and the edges of the cube

    def edge_axis_test(a1,a2,b1,b2,c1,c2):
        p = a1*b1 + a2*b2
        q = a1*c1 + a2*c2
        r = half_width*(abs(a1) + abs(a2))
        return (p < -r and q < -r) or (p > r and q > r)

    def edge_test(v0_x,v0_y,v0_z,v1_x,v1_y,v1_z,v2_x,v2_y,v2_z):
        e_x = v1_x - v0_x
        e_y = v1_y - v0_y
        e_z = v1_z - v0_z
        return (edge_axis_test(e_z,-e_y,v0_y,v0_z,v2_y,v2_z) or
                edge_axis_test(-e_z,e_x,v0_x,v0_z,v2_x,v2_z) or
                edge_axis_test(e_y,-e_x,v0_x,v0_y,v2_x,v2_y))

    if (edge_test(u_x,u_y,u_z,v_x,v_y,v_z,w_x,w_y,w_z) or
            edge_test(v_x,v_y,v_z,w_x,w_y,w_z,u_x,u_y,u_z) or
            edge_test(w_x,w_y,w_z,u_x,u_y,u_z,v_x,v_y,v_z)):
        return False

    # Triangle and cube intersects
    return True


class Octree:
    """
    Octree(triangles,max_triangles,min_width)
    
    Returns an octree where the cube of each leaf node intersects less than
    max_triangles of the triangles, unless that would make the width of the
    cube less than min_width.
    """

    class Node:

        def __getitem__(self,key):
            if self.is_leaf:
                return self
            else:
                return self.children[key[0] + 2*(key[1] + 2*key[2])]

    def __init__(self,triangles,max_triangles,min_width):
        self.triangles = triangles
        self.max_triangles = max_triangles
        self.min_width = min_width

        min_x = min(min(t.u.x,t.v.x,t.w.x) for t in triangles)
        min_y = min(min(t.u.y,t.v.y,t.w.y) for t in triangles)
        min_z = min(min(t.u.z,t.v.z,t.w.z) for t in triangles)
        max_x = max(max(t.u.x,t.v.x,t.w.x) for t in triangles)
        max_y = max(max(t.u.y,t.v.y,t.w.y) for t in triangles)
        max_z = max(max(t.u.z,t.v.z,t.w.z) for t in triangles)

        # Base point and width of the bounding box
        self.base = Vector(min_x,min_y,min_z)
        self.width_x = 2**int(ceil(log(max(max_x - min_x,min_width),2)))
        self.width_y = 2**int(ceil(log(max(max_y - min_y,min_width),2)))
        self.width_z = 2**int(ceil(log(max(max_z - min_z,min_width),2)))

        # Width of the top level nodes
        self.base_width = min(self.width_x,self.width_y,self.width_z)

        # Number of top level nodes in the x-, y- and z-direction
        self.nx = self.width_x//self.base_width
        self.ny = self.width_y//self.base_width
        self.nz = self.width_z//self.base_width

        self.children = [self.node(self.base + self.base_width*Vector(i,j,k),self.base_width,range(len(triangles)))
                for k in range(self.nz) for j in range(self.ny) for i in range(self.nx)]

        # If the top level branch ratio is greater than 0.875, space is saved
        # if the top level of nodes is removed
        while sum(1 for node in self.children if not node.is_leaf)/(self.nx*self.ny*self.nz) >= 0.875:
            self.children = [self[i//2,j//2,k//2][i % 2,j % 2,k % 2]
                    for k in range(2*self.nz) for j in range(2*self.ny) for i in range(2*self.nx)]
            self.base_width //= 2
            self.nx *= 2
            self.ny *= 2
            self.nz *= 2

    def __getitem__(self,key):
        return self.children[key[0] + self.nx*(key[1] + self.ny*key[2])]

    def node(self,base,width,indices):
        node = Octree.Node()
        half_width = width/2
        center = base + Vector(half_width,half_width,half_width)
        # Use tuple as it is hashable which is needed when packing
        indices = tuple(i for i in indices if tribox_overlap(self.triangles[i],center,half_width))

        if len(indices) > self.max_triangles and half_width >= self.min_width:
            node.children = [self.node(base + half_width*Vector(i,j,k),half_width,indices)
                    for k in range(2) for j in range(2) for i in range(2)]
            node.is_leaf = False
        else:
            node.indices = indices
            node.is_leaf = True

        return node

    @staticmethod
    def pack(stream,octree):
        # Identical index lists are merged to save space. Also, the empty list,
        # which is nothing but a terminating zero, uses the terminating zero of
        # the last non-empty list, thus saving a whopping two bytes. 

        branches = [octree]
        free_list_offset = 0
        list_offsets = OrderedDict()

        i = 0
        while i < len(branches):
            for node in branches[i].children:
                if node.is_leaf:
                    if not node.indices: continue
                    if node.indices in list_offsets: continue
                    list_offsets[node.indices] = free_list_offset
                    free_list_offset += 2*(len(node.indices) + 1)
                else:
                    branches.append(node)

            i += 1

        list_base = 4*sum(len(branch.children) for branch in branches)
        list_offsets[tuple()] = free_list_offset - 2
        branch_base = 0
        free_branch_offset = 4*len(octree.children)

        for branch in branches:
            for node in branch.children:
                if node.is_leaf:
                    uint32.pack(stream,0x80000000 | (list_base + list_offsets[node.indices] - 2 - branch_base))
                else:
                    uint32.pack(stream,free_branch_offset - branch_base)
                    free_branch_offset += 4*len(node.children)

            branch_base += 4*len(branch.children)

        del list_offsets[tuple()]

        for indices in list_offsets.keys():
            for index in indices:
                uint16.pack(stream,index + 1)
            uint16.pack(stream,0)

###############################################################################
#                                  Collision
###############################################################################

class Header(Struct):
    vertex_offset = uint32
    normal_offset = uint32
    face_offset = uint32
    octree_offset = uint32
    unknown0 = float32
    base = Vector
    x_mask = uint32
    y_mask = uint32
    z_mask = uint32
    coordinate_shift = uint32
    y_shift = uint32
    z_shift = uint32

    def __init__(self):
        self.unknown0 = 40


class Face(Struct):
    length = float32
    p_index = uint16
    n_index = uint16
    a_index = uint16
    b_index = uint16
    c_index = uint16
    group_index = uint16


def pack(stream,triangles,max_triangles,min_width):
    """Write KCL file."""

    if len(triangles) >= 0xFFFF - 1:
        raise GeometryOverflowError('too many faces')

    faces = [Face() for _ in triangles]
    vertex_welder = VertexWelder(2**(-1),int(ceil(len(triangles)/64)))
    normal_welder = VertexWelder(2**(-22),int(ceil(4*len(triangles)/64)))

    for face,triangle in zip(faces,triangles):
        a = cross(triangle.u - triangle.w,triangle.n).unit()
        b = cross(triangle.v - triangle.u,triangle.n).unit()
        c = cross(triangle.w - triangle.v,triangle.n).unit()
        face.length = dot(triangle.v - triangle.u,c)
        face.p_index = vertex_welder.add(triangle.u)
        face.n_index = normal_welder.add(triangle.n)
        face.a_index = normal_welder.add(a)
        face.b_index = normal_welder.add(b)
        face.c_index = normal_welder.add(c)
        face.group_index = triangle.group_index

    if len(vertex_welder.vertices) >= 0xFFFF:
        raise GeometryOverflowError('too many vertices')

    if len(normal_welder.vertices) >= 0xFFFF:
        raise GeometryOverflowError('too many normals')

    header = Header()
    stream.write(b'\x00'*Header.sizeof())

    header.vertex_offset = stream.tell()
    for vertex in vertex_welder.vertices:
        Vector.pack(stream,vertex)

    header.normal_offset = stream.tell()
    for normal in normal_welder.vertices:
        Vector.pack(stream,normal)

    header.face_offset = stream.tell() - Face.sizeof()
    for face in faces:
        Face.pack(stream,face)

    header.octree_offset = stream.tell()
    octree = Octree(triangles,max_triangles,min_width)
    Octree.pack(stream,octree)

    header.base = octree.base
    header.x_mask = ~(octree.width_x - 1) & 0xFFFFFFFF
    header.y_mask = ~(octree.width_y - 1) & 0xFFFFFFFF
    header.z_mask = ~(octree.width_z - 1) & 0xFFFFFFFF
    header.coordinate_shift = int(log(octree.base_width,2))
    header.y_shift = int(log(octree.nx,2))
    header.z_shift = header.y_shift + int(log(octree.ny,2))

    stream.seek(0)
    Header.pack(stream,header)

###############################################################################
#                                Wavefront OBJ
###############################################################################

class WavefrontOBJ(list):

    def __init__(self):
        super().__init__()
        self.group_names = []

    @staticmethod
    def unpack(stream):
        vertices = []
        triangles = WavefrontOBJ()

        triangles.group_names.append('default group')
        group_table = {'default group':0}
        group_index = 0

        for line in stream:
            if not line or line.isspace(): continue
            command,*args = line.split()

            if command == 'usemtl':
                group_name = args[0] if args else 'default group'
                if group_name not in group_table:
                    group_table[group_name] = len(group_table)
                    triangles.group_names.append(group_name)
                group_index = group_table[group_name]

            elif command == 'v':
                vertices.append(Vector(float(args[0]),float(args[1]),float(args[2])))

            elif command == 'f':
                u = vertices[int(args[0].split('/')[0]) - 1]
                v = vertices[int(args[1].split('/')[0]) - 1]
                w = vertices[int(args[2].split('/')[0]) - 1]
                if cross(v - u,w - u).norm_square() < 0.001: continue # TODO: find a better solution
                triangles.append(Triangle(u,v,w,group_index))

        return triangles

#______________________________________________________________________________
