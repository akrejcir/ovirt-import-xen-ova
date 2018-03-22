
import argparse
import lxml.etree as et
import logging


XML_NAMESPACES = {
    "ovf": "http://schemas.dmtf.org/ovf/envelope/1",
    "ovirt": "http://www.ovirt.org/ovf",
    "rasd": "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData",
    "vssd": "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "xenovf": "http://schemas.citrix.com/ovf/envelope/1"
}


# Hardware section
# ---- common ----
# - disk
# - cd / dvd
# - network adapters
# - cpus
# - memory
# ---- Ovirt ----
# - USB controller
# - graphical controller
# - graphical framebuffer
# - channels:
#   - unix
#   - spicevnc
# - controller ide
# - controller virtio-serial
# - balloon
# - controller virtio-scsi


def prefix_ns(ns, val):
    return "{%s}%s" % (XML_NAMESPACES[ns], val)


class ResourceType(object):
    OTHER = 0

    CPU = 3
    MEMORY = 4

    ETHERNET = 10
    NET_OTHER = 11

    FLOPPY_DRIVE = 14
    CD_DRIVE = 15
    DVD_DRIVE = 16
    DISK_DRIVE = 17

    STORAGE_EXTENT = 19


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("xen_ovf", help="Xen OVF file to convert")
    args = parser.parse_args()

    ovf_root = et.parse(args.xen_ovf).getroot()


if __name__ == '__main__':
    main()
