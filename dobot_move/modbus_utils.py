import struct


def float_to_regs(value):
    packed = struct.pack('>f', value)
    high = struct.unpack('>H', packed[0:2])[0]
    low = struct.unpack('>H', packed[2:4])[0]
    return high, low


def regs_to_float(high, low):
    packed = struct.pack('>HH', high, low)
    return struct.unpack('>f', packed)[0]
