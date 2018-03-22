
import argparse
import lxml.etree as et
import logging
import ovirtsdk4 as sdk


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


class VM(object):
    def __init__(self):
        pass

    def build_from_xen_ovf(self, ovf_root):
        raise NotImplementedError

    def add_vm_to_ovirt(self, conn):
        raise NotImplementedError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", help="URL of the oVirt engine API")
    parser.add_argument("--user", help="oVirt user name")
    parser.add_argument("--password", help="oVirt user password")
    parser.add_argument("ovf_file", help="Xen OVF file")
    args = parser.parse_args()

    ovf_root = et.parse(args.ovf_file).getroot()

    connection = sdk.Connection(
        url=args.engine,
        username=args.user,
        password=args.password,
        insecure=True
    )

    connection.test(raise_exception=True)

    vm = VM()
    vm.build_from_xen_ovf(ovf_root)
    vm.add_vm_to_ovirt(connection)


if __name__ == '__main__':
    main()
