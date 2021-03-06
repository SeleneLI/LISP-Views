'''
Created on 9 jan. 2013

@author: sander
'''
from bitstring import BitStream, ConstBitStream, Bits
from ipaddress import IPv4Address, IPv6Address
from pylisp.packet.ip import protocol_registry
from pylisp.packet.ip.protocol import Protocol
from pylisp.utils import checksum
import numbers


class UDPMessage(Protocol):
    header_type = 17

    def __init__(self, source_port=0, destination_port=0, checksum=0,
                 payload=''):
        # Call the superclass constructor
        super(UDPMessage, self).__init__(payload=payload)

        self.source_port = source_port
        self.destination_port = destination_port
        self.checksum = checksum

    def sanitize(self):
        '''
        Check if the current settings conform to the RFC and fix where possible
        '''
        # Check ports
        if not isinstance(self.source_port, numbers.Integral) \
        or self.source_port < 0 \
        or self.source_port >= 2 ** 16:
            raise ValueError('Invalid source port')

        if not isinstance(self.destination_port, numbers.Integral) \
        or self.destination_port < 0 \
        or self.destination_port >= 2 ** 16:
            raise ValueError('Invalid destination port')

        # We can't calculate the checksum because we don't know enough by
        # ourself to construct the pseudo-header

    def generate_pseudo_header(self, source, destination):
        # Calculate the length of the UDP layer
        udp_length = 8 + len(bytes(self.payload))

        if isinstance(source, IPv4Address) \
        and isinstance(destination, IPv4Address):
            # Generate an IPv4 pseudo-header
            header = BitStream('uint:32=%d, '
                               'uint:32=%d, '
                               'uint:16=17, '
                               'uint:16=%d' % (int(source),
                                               int(destination),
                                               udp_length))

        elif isinstance(source, IPv6Address) \
        and isinstance(destination, IPv6Address):
            # Generate an IPv6 pseudo-header
            header = BitStream('uint:128=%d, '
                               'uint:128=%d, '
                               'uint:32=%d, '
                               'uint:32=17' % (int(source),
                                               int(destination),
                                               udp_length))
        else:
            raise ValueError('Source and destination must belong to the same '
                             'IP version')

        # Return the header bytes
        return header.bytes

    def calculate_checksum(self, source, destination):
        # Calculate the pseudo-header for the checksum calculation
        pseudo_header = self.generate_pseudo_header(source, destination)

        # Remember the current checksum, generate a message and restore the
        # original checksum
        old_checksum = self.checksum
        self.checksum = 0
        message = self.to_bytes()
        self.checksum = old_checksum

        # Calculate the checksum
        my_checksum = checksum.ones_complement(pseudo_header + message)

        # If the computed checksum is zero, it is transmitted as all ones (the
        # equivalent in one's complement arithmetic).  An all zero transmitted
        # checksum value means that the transmitter generated no checksum (for
        # debugging or for higher level protocols that don't care).
        if my_checksum == 0:
            my_checksum = 0xffff

        return my_checksum

    def verify_checksum(self, source, destination):
        # An all zero transmitted checksum value means that the transmitter
        # generated no checksum (for debugging or for higher level protocols
        # that don't care).
        if self.checksum == 0:
            return True

        return self.checksum == self.calculate_checksum(source, destination)

    def get_lisp_message(self, only_data=False, only_control=False):
        # Check the UDP ports
        lisp_data = (self.source_port == 4341
                     or self.destination_port == 4341)
        lisp_control = (self.source_port == 4342
                        or self.destination_port == 4342)

        if lisp_data and lisp_control:
            raise ValueError("Cannot mix LISP data and control ports")

        from pylisp.packet.lisp.control.base import ControlMessage
        from pylisp.packet.lisp.data import DataPacket

        if lisp_data or only_data:
            if not isinstance(self.payload, DataPacket):
                raise ValueError("Payload is not a LISP data packet")
            return self.payload

        elif lisp_control or only_control:
            if not isinstance(self.payload, ControlMessage):
                raise ValueError("Payload is not a LISP control message")
            return self.payload

        else:
            raise ValueError("No LISP content found")

    def get_lisp_data_packet(self):
        return self.get_lisp_message(only_data=True)

    def get_lisp_control_message(self):
        return self.get_lisp_message(only_control=True)

    @classmethod
    def from_bytes(cls, bitstream):
        '''
        Parse the given packet and update properties accordingly
        '''
        packet = cls()

        # Convert to ConstBitStream (if not already provided)
        if not isinstance(bitstream, ConstBitStream):
            if isinstance(bitstream, Bits):
                bitstream = ConstBitStream(auto=bitstream)
            else:
                bitstream = ConstBitStream(bytes=bitstream)

        # Read the source and destination ports
        (packet.source_port,
         packet.destination_port) = bitstream.readlist('2*uint:16')

        # Store the length
        length = bitstream.read('uint:16')
        if length < 8:
            raise ValueError('Invalid UDP length')

        # Read the checksum
        packet.checksum = bitstream.read('uint:16')

        # And the rest is payload
        payload_bytes = length - 8
        packet.payload = bitstream.read('bytes:%d' % payload_bytes)

        # LISP-specific handling
        if packet.source_port == 4341 or packet.destination_port == 4341:
            # Payload is a LISP data packet
            from pylisp.packet.lisp.data import DataPacket
            packet.payload = DataPacket.from_bytes(packet.payload)
        elif packet.source_port == 4342 or packet.destination_port == 4342:
            # Payload is a LISP control message
            from pylisp.packet.lisp.control.base import ControlMessage
            packet.payload = ControlMessage.from_bytes(packet.payload)

        # There should be no remaining bits
        if bitstream.pos != bitstream.len:
            raise ValueError('Bits remaining after processing packet')

        # Verify that the properties make sense
        packet.sanitize()

        return packet

    def to_bytes(self):
        '''
        Create bytes from properties
        '''
        # Verify that the properties make sense
        self.sanitize()

        # Write the source and destination ports
        bitstream = BitStream('uint:16=%d, '
                              'uint:16=%d' % (self.source_port,
                                              self.destination_port))

        # Write the length
        payload_bytes = bytes(self.payload)
        length = len(payload_bytes) + 8
        bitstream += BitStream('uint:16=%d' % length)

        # Write the checksum
        bitstream += BitStream('uint:16=%d' % self.checksum)

        return bitstream.bytes + payload_bytes

# Register this header type
protocol_registry.register_type_class(UDPMessage)
