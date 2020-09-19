"""Module for reading and writing data structures."""

import io
import struct as _struct

#------------------------------------------------------------------------------

class BasicType:

    def __init__(self,basic_format):
        self.basic_format = basic_format
        self.size = _struct.calcsize('=' + basic_format)

    def pack(self,stream,value):
        stream.write(_struct.pack(stream.endianess + self.basic_format,value))

    def unpack(self,stream):
        return _struct.unpack(stream.endianess + self.basic_format,stream.read(self.size))[0]

    def sizeof(self):
        return self.size


class FixedPointConverter:

    def __init__(self,integer_type,scale):
        self.integer_type = integer_type
        self.scale = scale

    def pack(self,stream,value):
        self.integer_type.pack(stream,int(value/self.scale))

    def unpack(self,stream):
        return self.integer_type.unpack(stream)*self.scale

    def sizeof(self):
        return self.integer_type.sizeof()


class ByteString:

    def __init__(self,length):
        self.length = length

    def pack(self,stream,string):
        stream.write(string)

    def unpack(self,stream):
        return stream.read(self.length)

    def sizeof(self):
        return self.length


class Array:

    def __init__(self,element_type,length):
        self.element_type = element_type
        self.length = length

    def pack(self,stream,array):
        for value in array:
            self.element_type.pack(stream,value)

    def unpack(self,stream):
        return [self.element_type.unpack(stream) for _ in range(self.length)]

    def sizeof(self):
        return self.length*self.element_type.sizeof()


class CString:

    def __init__(self,encoding):
        self.encoding = encoding
        self.null = '\0'.encode(encoding)

    def pack(self,stream,string):
        stream.write((string + '\0').encode(self.encoding))

    def unpack(self,stream):
        # NOTICE: This might not work for all encodings, but it works for
        # ascii, UTF-8, UTF-16 and Shift JIS.
        string = b''
        while True:
            c = stream.read(len(self.null))
            if c == self.null: break
            string += c
        return string.decode(self.encoding)

    def sizeof(self):
        return None


class PString:

    def __init__(self,encoding):
        self.encoding = encoding

    def pack(self,stream,string):
        string = string.encode(self.encoding)
        uint8.pack(stream,len(string))
        stream.write(string)

    def unpack(self,stream):
        length = uint8.unpack(stream)
        return stream.read(length).decode(self.encoding)

    def sizeof(self):
        return None

#------------------------------------------------------------------------------

NATIVE_ENDIAN = '='
LITTLE_ENDIAN = '<'
BIG_ENDIAN = '>'


bool8 = BasicType('?')
sint8 = BasicType('b')
uint8 = BasicType('B')
sint16 = BasicType('h')
uint16 = BasicType('H')
sint32 = BasicType('l')
uint32 = BasicType('L')
sint64 = BasicType('q')
uint64 = BasicType('Q')
float32 = BasicType('f')
float64 = BasicType('d')
cstring = CString('ascii')
pstring = PString('ascii')


class StreamBase:

    def __init__(self,endianess):
        self.endianess = endianess


class FileStream(StreamBase,io.FileIO):

    def __init__(self,filename,mode='r',endianess=NATIVE_ENDIAN):
        StreamBase.__init__(self,endianess)
        io.FileIO.__init__(self,filename,mode)


class BytesStream(StreamBase,io.BytesIO):

    def __init__(self,initial_bytes=b'',endianess=NATIVE_ENDIAN):
        StreamBase.__init__(self,endianess)
        io.BytesIO.__init__(self,initial_bytes)


class Pointer:

    def __init__(self,stream,value_type,offset):
        self.stream = stream
        self.value_type = value_type
        self.offset = offset

    def __getitem__(self,key):
        self.stream.seek(self.offset + key*self.value_type.sizeof())
        return self.value_type.unpack(self.stream)


def align(stream,boundary,padding='This is padding data to alignment.'):
    if stream.tell() % boundary == 0: return
    n,r = divmod(boundary - (stream.tell() % boundary),len(padding))
    stream.write(n*padding + padding[0:r])


def align_length(length,boundary):
    return ((length + boundary - 1)//boundary)*boundary

#------------------------------------------------------------------------------

class Field:

    def __init__(self,field_type,name):
        self.field_type = field_type
        self.name = name

    def pack(self,stream,struct):
        self.field_type.pack(stream,getattr(struct,self.name))

    def unpack(self,stream,struct):
        setattr(struct,self.name,self.field_type.unpack(stream))

    def sizeof(self):
        return self.field_type.sizeof()

    def equal(self,struct,other):
        return getattr(struct,self.name) == getattr(other,self.name)


class Padding:

    def __init__(self,length,padding=b'\xFF'):
        self.length = length
        self.padding = padding

    def pack(self,stream,struct):
        stream.write(self.padding*self.length)

    def unpack(self,stream,struct):
        stream.read(self.length)

    def sizeof(self):
        return self.length

    def equal(self,struct,other):
        return True


class StructDict(dict):

    def __init__(self):
        super().__init__()
        self.struct_fields = []

    def __setitem__(self,key,value):
        if not key[:2] == key[-2:] == '__' and not hasattr(value,'__get__'):
            self.struct_fields.append(Field(value,key))
        elif key == '__padding__':
            self.struct_fields.append(value)
        else:
            super().__setitem__(key,value)


class StructMeta(type):

    @classmethod
    def __prepare__(metacls,cls,bases):
        return StructDict()

    def __new__(metacls,cls,bases,classdict):
        struct_size = 0
        for field in classdict.struct_fields:
            if field.sizeof() is None:
                struct_size = None
                break
            struct_size += field.sizeof()

        struct_class = type.__new__(metacls,cls,bases,classdict)
        struct_class.struct_fields = classdict.struct_fields
        struct_class.struct_size = struct_size
        return struct_class

    def __init__(self,cls,bases,classdict):
        super().__init__(cls,bases,classdict)


class Struct(metaclass=StructMeta):

    __slots__ = tuple()

    def __eq__(self,other):
        return all(field.equal(self,other) for field in self.struct_fields)

    @classmethod
    def pack(cls,stream,struct):
        for field in cls.struct_fields:
            field.pack(stream,struct)

    @classmethod
    def unpack(cls,stream):
        struct = cls.__new__(cls) #TODO: what if __init__ does something important?
        for field in cls.struct_fields:
            field.unpack(stream,struct)
        return struct

    @classmethod
    def sizeof(cls):
        return cls.struct_size

#______________________________________________________________________________
