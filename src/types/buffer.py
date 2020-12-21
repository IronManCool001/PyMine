from __future__ import annotations
import struct
import json
import uuid
import zlib


class Buffer:
    """
    Base class for a buffer, contains methods
    for handling most basic types and for
    converting from/to a Buffer object itself.
    """

    def __init__(self, buf: bytes = None) -> None:
        self.buf = b'' if buf is None else buf
        self.pos = 0

    def write(self, data: bytes) -> None:
        """Writes data to the buffer."""

        self.buf += data

    def read(self, length: int = None) -> bytes:
        """
        Reads n bytes from the buffer, if the length is None
        then all remaining data from the buffer is sent.
        """

        try:
            if length is None:
                length = len(self.buf)
                return self.buf[self.pos:]
            else:
                return self.buf[self.pos:self.pos+length]
        finally:
            self.pos += length

    def reset(self) -> None:
        """Resets the position in the buffer."""

        self.pos = 0

    def unpack(self, f: str) -> object:
        unpacked = struct.unpack('>'+f, self.read(struct.calcsize(f)))

        if len(unpacked) == 1:
            return unpacked[0]

        return unpacked

    @classmethod
    def pack(self, f: str, *data: object) -> bytes:
        return struct.pack('>'+f, *data)

    @classmethod
    def pack_array(cls, f: str, array: list) -> bytes:
        """Packs an array/list into bytes."""

        return struct.pack(f'>{f*len(array)}', *array)

    def unpack_array(self, f: str, length: int) -> list:
        """Unpacks an array/list from the buffer."""

        data = self.read(struct.calcsize(f'>{f}') * length)
        return list(struct.unpack(f'>{f*length}', data))

    @classmethod
    def pack_bool(cls, boolean) -> bytes:
        """Packs a boolean into bytes."""

        return struct.pack(f'>?', boolean)

    def unpack_bool(self) -> bool:
        """Unpacks a boolean from the buffer."""

        return self.unpack('>?')

    @classmethod
    def pack_varint(cls, num: int, max_bits: int = 32) -> bytes:
        """Packs a varint (Varying Integer) into bytes."""

        num_min, num_max = (-1 << (max_bits - 1)), (+1 << (max_bits - 1))

        if not (num_min <= num < num_max):
            raise ValueError(f'num doesn\'t fit in given range: {num_min} <= {num} < {num_max}')

        if num < 0:
            num += 1 + 1 << 32

        out = b''

        for i in range(10):
            b = num & 0x7F
            num >>= 7

            out += struct.pack('>B', (b | (0x80 if num > 0 else 0)))

            if num == 0:
                break

        return out

    def unpack_varint(self, max_bits: int = 32) -> int:
        """Unpacks a varint from the buffer."""

        num = 0

        for i in range(10):
            b = self.unpack('>B')
            num |= (b & 0x7F) << (7 * i)

            if not b & 0x80:
                break

        if num & (1 << 31):
            num -= 1 << 32

        num_min, num_max = (-1 << (max_bits - 1)), (+1 << (max_bits - 1))

        if not (num_min <= num < num_max):
            raise ValueError(f'num doesn\'t fit in given range: {num_min} <= {num} < {num_max}')

        return num

    @classmethod
    def from_bytes(cls, data: bytes, comp_thresh: int = -1) -> Buffer:
        """
        Creates a Buffer object from bytes, handles compression
        and length prefixing
        """

        buf = cls(data)
        buf = cls(buf.read(buf.unpack_varint()))  # Handle length prefixing

        # Handle if the data was compressed
        if comp_thresh >= 0:
            uncomp_len = buf.unpack_varint()  # Handle decompressed length prefixing

            if uncomp_len > 0:
                # Create new Buffer from decompressed data
                buf = cls(zlib.decompress(buf.read()))

        return buf

    def to_bytes(self, comp_thresh: int = -1) -> bytes:
        """
        Packs the final Buffer into bytes, readies the data to be sent,
        handles compression and length prefixing.
        """

        if comp_thresh >= 0:
            if len(self.buf) >= comp_thresh:
                data = self.pack_varint(len(self.buf)) + \
                    zlib.compress(self.buf)
            else:
                data = self.pack_varint(0) + self.buf
        else:
            data = self.buf

        return self.pack_varint(len(data), max_bits=32) + data

    @classmethod
    def pack_string(cls, text: str) -> bytes:
        """Packs a string into bytes."""

        text = text.encode('utf-8')
        return cls.pack_varint(len(text), max_bits=16) + text

    def unpack_string(self) -> str:
        """Unpacks a string from the buffer."""

        length = self.unpack_varint(max_bits=16)
        return self.read(length).decode('utf-8')

    @classmethod
    def pack_json(cls, obj: object) -> bytes:
        """Packs json serializable data into bytes."""

        return cls.pack_string(json.dumps(obj))

    def unpack_json(self) -> object:
        """Unpacks serialized json data from the buffer."""

        return json.loads(self.unpack_string())

    @classmethod
    def pack_uuid(cls, uuid: uuid.UUID) -> bytes:
        """Packs a UUID into bytes."""

        return uuid.to_bytes()

    def unpack_uuid(self):
        """Unpacks a UUID from the buffer."""

        return uuid.UUID(bytes=self.read(16))

    @classmethod
    def pack_msg(cls, msg: Message) -> bytes:
        """Packs a Minecraft chat message into bytes."""

        return msg.to_bytes()

    def unpack_msg(self) -> Message:
        """Unpacks a Minecraft chat message from the buffer."""

        return Message.from_buf(self)

    @classmethod
    def pack_pos(cls, x, y, z) -> bytes:
        """Packs a Minecraft position (x, y, z) into bytes."""

        def to_twos_complement(num, bits):
            return num + (1 << bits) if num < 0 else num

        return struct.pack('>Q', sum((
            to_twos_complement(x, 26) << 38,
            to_twos_complement(y, 12) << 26,
            to_twos_complement(z, 26)
        )))

    def unpack_pos(self) -> tuple:
        """Unpacks a Minecraft position (x, y, z) from the buffer."""

        def from_twos_complement(num, bits):
            if num & (1 << (bits - 1)) != 0:
                num -= (1 << bits)

            return num

        data = self.unpack('>Q')

        x = from_twos_complement(data >> 38, 26)
        y = from_twos_complement(data >> 26 & 0xFFF, 12)
        z = from_twos_complement(data & 0x3FFFFFF, 26)

        return x, y, z

    @classmethod
    def pack_slot(cls):
        """Packs an inventory/container slot into bytes."""

        pass

    def unpack_slot(self):
        """Unpacks an inventory/container slot from the buffer."""

        pass

    @classmethod
    def pack_direction(cls, direction: str) -> bytes:
        """Packs a direction into bytes."""

        return cls.pack_varint(DIRECTIONS.index(direction))

    def unpack_direction(self) -> str:
        """Unpacks a direction from the buffer."""

        return DIRECTIONS[self.unpack_varint()]

    @classmethod
    def pack_rotation(cls, x: float, y: float, z: float) -> bytes:
        """Packs a rotation (of an entity) into bytes."""

        return cls.pack('fff', x, y, z)

    def unpack_rotation(self):
        """Unpacks a rotation (of an entity) from the buffer."""

        return self.unpack('fff')