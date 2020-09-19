from btypes import *

cstring_sjis = CString('shift-jis')

#------------------------------------------------------------------------------

UINT32 = 0
FLOAT32 = 2
SINT32 = 3
SINT16 = 4
SINT8 = 5
STRING = 6


class Header(Struct):
    entry_count = uint32
    field_count = uint32
    entry_offset = uint32
    entry_size = uint32


class Field(Struct):
    name_hash = uint32
    mask = uint32
    offset = uint16
    shift = uint8
    data_type = uint8

    @property
    def data_size(self):
        if self.data_type == UINT32:
            return 4
        elif self.data_type == FLOAT32:
            return 4
        elif self.data_type == SINT32:
            return 4
        elif self.data_type == SINT16:
            return 2
        elif self.data_type == SINT8:
            return 1
        elif self.data_type == STRING:
            return 4
            

    def __init__(self,data_type,name,offset,mask,shift):
        self.data_type = data_type
        self.offset = offset
        self.mask = mask
        self.shift = shift

        if isinstance(name,int):
            self.name_hash = name
        else:
            self.name = name
            self.name_hash = calculate_name_hash(name)


def calculate_name_hash(name):
    h = 0
    for c in name:
        h = (h*31 + ord(c)) & 0xFFFFFFFF
    return h


def create_name_table(names):
    return {calculate_name_hash(name) : name for name in names}

#------------------------------------------------------------------------------

class ListBase(list):

    @classmethod
    def pack(cls,stream,entries):
        fields = cls.get_fields(entries)

        header = Header()
        header.entry_count = len(entries)
        header.field_count = len(fields)
        header.entry_offset = Header.sizeof() + len(fields)*Field.sizeof()
        header.entry_size = align_length(max(field.offset + field.data_size for field in fields),4)
        Header.pack(stream,header)

        for field in fields:
            Field.pack(stream,field)

        string_table = {}
        string_pool = BytesStream(bytes(),stream.endianess)

        for entry in entries:
            entry_block = BytesStream(bytes(header.entry_size),stream.endianess)

            for field_index,field in enumerate(fields):
                value = cls.get_field_value(entry,field_index)
                entry_block.seek(field.offset)

                if field.data_type == UINT32:
                    value = (value << field.shift) | uint32.unpack(entry_block)
                    entry_block.seek(field.offset)
                    uint32.pack(entry_block,value)
                elif field.data_type == FLOAT32:
                    float32.pack(entry_block,value)
                elif field.data_type == SINT32:
                    sint32.pack(entry_block,value)
                elif field.data_type == SINT16:
                    sint16.pack(entry_block,value)
                elif field.data_type == SINT8:
                    sint8.pack(entry_block,value)
                elif field.data_type == STRING:
                    if value in string_table:
                        uint32.pack(entry_block,string_table[value])
                    else:
                        uint32.pack(entry_block,string_pool.tell())
                        string_table[value] = string_pool.tell()
                        cstring_sjis.pack(string_pool,value)

            stream.write(entry_block.getvalue())

        stream.write(string_pool.getvalue())
        align(stream,0x20,b'\x40')

    @classmethod
    def unpack(cls,stream):
        header = Header.unpack(stream)
        fields = [Field.unpack(stream) for i in range(header.field_count)]
        entries = cls.create_list(header.entry_count,fields)

        stream.seek(header.entry_offset + header.entry_count*header.entry_size)
        string_pool = BytesStream(stream.read(),stream.endianess)

        stream.seek(header.entry_offset)

        for entry in entries:
            entry_block = BytesStream(stream.read(header.entry_size),stream.endianess)

            for field_index,field in enumerate(fields):
                entry_block.seek(field.offset)

                if field.data_type == UINT32:
                    value = (uint32.unpack(entry_block) & field.mask) >> field.shift
                elif field.data_type == FLOAT32:
                    value = float32.unpack(entry_block)
                elif field.data_type == SINT32:
                    value = sint32.unpack(entry_block)
                elif field.data_type == SINT16:
                    value = sint16.unpack(entry_block)
                elif field.data_type == SINT8:
                    value = sint8.unpack(entry_block)
                elif field.data_type == STRING:
                    string_pool.seek(uint32.unpack(entry_block))
                    value = cstring_sjis.unpack(string_pool)
                else:
                    raise FormatError('invalid field data type')
              
                cls.set_field_value(entry,field_index,value)

        return entries

#------------------------------------------------------------------------------

class List(ListBase):

    def __init__(self,fields,entries=tuple()):
        self.bcsv_fields = fields
        super().__init__(entries)

    @staticmethod
    def create_list(entry_count,fields):
        return List(fields,[[None]*len(fields) for i in range(entry_count)])

    @staticmethod
    def get_fields(entries):
        return entries.bcsv_fields

    @staticmethod
    def set_field_value(entry,field_index,value):
        entry[field_index] = value

    @staticmethod
    def get_field_value(entry,field_index):
        return entry[field_index]

    def load_names(self,name_table):
        for field in self.bcsv_fields:
            field.name = name_table.get(field.name_hash,'{:08X}'.format(field.name_hash))

#------------------------------------------------------------------------------

class ObjectListDict(dict):

    def __init__(self):
        super().__init__()
        self.bcsv_fields = []

    def __setitem__(self,key,value):
        if isinstance(value,Field):
            value.attribute_name = key
            self.bcsv_fields.append(value)
        else:
            super().__setitem__(key,value)


class ObjectListMeta(type):

    @classmethod
    def __prepare__(metacls,cls,bases):
        return ObjectListDict()

    def __new__(metacls,cls,bases,classdict):
        objectlist_class = type.__new__(metacls,cls,bases,classdict)
        objectlist_class.bcsv_fields = classdict.bcsv_fields
        return objectlist_class


class ObjectList(ListBase,metaclass=ObjectListMeta):

    class Entry: pass
    
    @classmethod
    def create_list(cls,entry_count,fields):
        if fields != cls.bcsv_fields:
            raise FormatError('invalid field list')
        return cls(cls.Entry() for i in range(entry_count))

    @classmethod
    def get_fields(cls,entries):
        return cls.bcsv_fields

    @classmethod
    def set_field_value(cls,entry,field_index,value):
        setattr(entry,cls.bcsv_fields[field_index].attribute_name,value)

    @classmethod
    def get_field_value(cls,entry,field_index):
        return getattr(entry,cls.bcsv_fields[field_index].attribute_name)

#______________________________________________________________________________
