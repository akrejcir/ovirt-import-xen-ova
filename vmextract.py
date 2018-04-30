
import argparse
import glob
import json
import lxml.etree as et
import logging
import re
import subprocess
import tarfile
import os


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


def handle_elem(elem, handlers, mapper=None):
    if mapper is None:
        mapper = lambda e: e.tag

    key = mapper(elem)
    if key not in handlers:
        logging.warn("Unknown tag, skipping: %s (%s)", key, elem.tag)
        return

    handlers[key](elem)


def noop_handler(elem):
    pass


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
        self.id = None
        self.name = None
        self.cpu_count = None
        self.cores_pre_socket = 1
        self.memory_bytes = None
        self.disks = []

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'cpu_count': self.cpu_count,
            'cores_pre_socket': self.cores_pre_socket,
            'memory_bytes': self.memory_bytes,
            'disks': self.disks
        }


class OvfReader(object):
    def __init__(self):
        self._vm = VM()
        self._ovf = None

    def read_xen_ovf(self, ovf_root):
        self._ovf = ovf_root

        self._read_ovf_envelope(ovf_root)
        self._check_required_fields()
        return self._vm

    def _read_ovf_envelope(self, elem):
        for e in elem:
            handle_elem(e, {
                prefix_ns("ovf", "References"): noop_handler,
                prefix_ns("ovf", "DiskSection"): noop_handler,
                prefix_ns("ovf", "NetworkSection"): noop_handler,
                prefix_ns("ovf", "StartupSection"): noop_handler,
                prefix_ns("ovf", "VirtualSystem"): self._read_ovf_virtual_system
            })

    def _read_ovf_virtual_system(self, elem):
        def set_name(name_elem):
            self._vm.name = name_elem.text

        self._vm.id = elem.attrib[prefix_ns("ovf", "id")]

        for e in elem:
            handle_elem(e, {
                prefix_ns("ovf", "Info"): noop_handler,
                prefix_ns("ovf", "Name"): set_name,
                prefix_ns("ovf", "OperatingSystemSection"): noop_handler,
                prefix_ns("ovf", "VirtualHardwareSection"): self._read_hardware
            })

    def _read_hardware(self, elem):
        def handle_item(item):
            handle_elem(item, {
                ResourceType.CPU: self._read_hw_cpu,
                ResourceType.MEMORY: self._read_hw_memory,
                ResourceType.ETHERNET: noop_handler, # Network will not be attached
                ResourceType.CD_DRIVE: noop_handler,
                ResourceType.DVD_DRIVE: noop_handler,
                ResourceType.STORAGE_EXTENT: self._read_hw_disk
            }, lambda e: int(e.xpath("rasd:ResourceType/text()", namespaces=e.nsmap)[0]))

        def handle_other_config(elem):
            handle_elem(elem, {
                "HVM_boot_params": noop_handler,
                "HVM_boot_policy": noop_handler,
                "platform": self._read_hw_platform,
                "hardware_platform_version": noop_handler  # Not relevant for oVirt
            }, lambda e: e.attrib["Name"])

        for e in elem:
            handle_elem(e, {
                prefix_ns("ovf", "Info"): noop_handler,
                prefix_ns("ovf", "System"): noop_handler,
                prefix_ns("ovf", "Item"): handle_item,
                prefix_ns("xenovf", "VirtualSystemOtherConfigurationData"): handle_other_config
            })

    def _read_hw_cpu(self, elem):
        if self._vm.cpu_count is not None:
            raise RuntimeError("OVF contains multiple CPU elements.")

        self._vm.cpu_count = int(elem.xpath("rasd:VirtualQuantity/text()", namespaces=elem.nsmap)[0])

    def _read_hw_memory(self, elem):
        if self._vm.memory_bytes is not None:
            raise RuntimeError("OVF contains multiple memory elements.")

        # Check if allocation units are MB
        units = elem.xpath("rasd:AllocationUnits/text()", namespaces=elem.nsmap)[0]
        if units != 'byte * 2^20':
            raise RuntimeError("Memory units are not MB")

        mem_mb = int(elem.xpath("rasd:VirtualQuantity/text()", namespaces=elem.nsmap)[0])
        self._vm.memory_bytes = mem_mb * 1024 * 1024

    def _read_hw_disk(self, elem):
        disk_id = elem.xpath("rasd:InstanceID/text()", namespaces=elem.nsmap)[0]

        # Find disk with this ID
        disk_elem = self._ovf.xpath(
            "/ovf:Envelope/ovf:DiskSection/ovf:Disk[@ovf:diskId='{disk_id}']".format(
                disk_id=disk_id
            ),
            namespaces=elem.nsmap
        )[0]

        file_id = disk_elem.attrib[prefix_ns("ovf", "fileRef")]
        file_elem = self._ovf.xpath(
            "/ovf:Envelope/ovf:References/ovf:File[@ovf:id='{file_id}']".format(
                file_id=file_id
            ),
            namespaces=elem.nsmap
        )[0]

        self._vm.disks.append({
            'id': disk_id,
            'name': str(elem.xpath("rasd:ElementName/text()", namespaces=elem.nsmap)[0]),
            'capacity': int(disk_elem.attrib[prefix_ns("ovf", "capacity")]),
            'bootable': disk_elem.attrib[prefix_ns("xenovf", "isBootable")] in ["true", "True"],
            'file': file_elem.attrib[prefix_ns("ovf", "href")]
        })

    def _read_hw_platform(self, elem):
        info_str = elem.xpath("xenovf:Value/text()", namespaces=elem.nsmap)[0]

        for p in info_str.split(';'):
            if not p:
                continue

            [key, value] = p.split('=', maxsplit=1)
            if key == 'cores-per-socket':
                self._vm.cores_pre_socket = int(value)
                continue

    def _check_required_fields(self):
        if self._vm.id is None:
            raise RuntimeError("VM ID is missing!")

        if self._vm.name is None:
            raise RuntimeError("Name is missing!")

        if self._vm.cpu_count is None:
            raise RuntimeError("CPU count information is missing!")

        if self._vm.memory_bytes is None:
            raise RuntimeError("Memory information is missing!")


def convert_disks(vm, skip_conversion):
    for disk in vm.disks:
        disk_file = disk["file"]
        out_file = disk["id"] + ".qcow2"

        if skip_conversion:
            logging.info("Skipping conversion of disk: %s", disk_file)
            logging.debug("Output assumed to be: %s", out_file)
            disk["qcow_file"] = out_file
            continue

        logging.info("Converting disk: %s", disk_file)
        err = subprocess.call([
            "qemu-img",
            "convert",
            "-f", "vpc",
            "-O", "qcow2",
            disk_file,
            out_file
        ])

        if err != 0:
            raise RuntimeError("Disk conversion failed")

        logging.info("Conversion succeeded. Output: %s", out_file)
        disk["qcow_file"] = out_file


def read_ovf(ovf_file):
    with open(ovf_file, "r") as f:
        contents = f.read()

    version_tag_pattern = r'^\s*<\?xml\s*version="[^"]*"\s*encoding="([^"]*)"\s*\?>'

    # Checking the utf versuion in the header
    match = re.match(version_tag_pattern, contents)
    if match and match.group(1) == 'utf-16':
        # The OVF is probably not stored in UTF-16 format.
        logging.warn('XML contains encoding="utf-16, ignoring"')

    # Strip the encoding tag
    return re.sub(version_tag_pattern, '', contents)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", help="Show debug messages", action="store_true")
    parser.add_argument("-s", "--skip-disk-conversion",
                        help="Do not call qemu-img to convert disks",
                        action="store_true")

    parser.add_argument("filename", help="Xen OVA file or a directory containing OVF file")
    args = parser.parse_args()

    logging.getLogger().setLevel(
        logging.DEBUG if args.verbose else logging.INFO
    )

    path = args.filename
    if os.path.isfile(path):
        ova_dir = os.path.dirname(path)
        ova_filename, ova_ext = os.path.splitext(path)

        if ova_ext not in ['.ova', '.OVA']:
            raise RuntimeError("File is not an OVA")

        with tarfile.open(path) as tar_file:
            logging.info("Extracting OVA archive...")
            tar_file.extractall(path=ova_dir)
            logging.info("Extraction finished.")

        path = ova_dir

    os.chdir(path)

    ovf_files = glob.glob('*.ovf')
    if not ovf_files:
        logging.error("Directory %s does not contain an OVF file.", path)
        return 1

    ovf_contents = read_ovf(ovf_files[0])
    ovf_root = et.fromstring(ovf_contents)

    vm = OvfReader().read_xen_ovf(ovf_root)
    convert_disks(vm, args.skip_disk_conversion)

    with open("vm.json", "w") as f:
        json.dump(vm.to_dict(), f, indent=4)


if __name__ == '__main__':
    main()
