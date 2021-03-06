
import argparse
import json
import http.client
import logging
import ovirtsdk4 as sdk
import os
import string
import ssl
import random
import re
import time
import six.moves.urllib.parse as url_parse
import uuid


NAME_PATTERN_FULL_STR = re.compile("[\w.-]*\Z")


def is_string_uuid(val):
    try:
        uuid.UUID(val)
        return True
    except ValueError:
        return False


def check_cluster_exists(cluster_id, conn):
    try:
        conn.service("clusters").service(cluster_id).get()
    except sdk.NotFoundError:
        raise RuntimeError("Cluster was not found, id: %s" % cluster_id)


def check_domain_exists(domain_id, conn):
    try:
        conn.service("storagedomains").service(domain_id).get()
    except sdk.NotFoundError:
        raise RuntimeError("Storage domain was not found, id: %s" % domain_id)


def get_cluster_id_by_name(cluster_name, conn):
    search_str = 'name=%s' % cluster_name
    clusters = conn.service("clusters").list(search=search_str, max=1)
    if not clusters:
        raise RuntimeError("Cluster was not found, name: %s" % cluster_name)

    return clusters[0].id


def get_domain_id_by_name(domain_name, conn):
    search_str = 'name=%s' % domain_name
    domains = conn.service("storagedomains").list(search=search_str, max=1)
    if not domains:
        raise RuntimeError("Storage domain was not found, name: %s" % domain_name)

    return domains[0].id


def add_vm_to_ovirt(vm_def, conn):
    # Check if name is valid
    if not NAME_PATTERN_FULL_STR.match(vm_def['name']):
        raise RuntimeError("Vm name can only contain alpha-numeric characters, '_', '-' or '.'. Vm name: %r" % vm_def['name'])

    vm = sdk.types.Vm(
        id=vm_def['id'],
        name=vm_def['name'],
        cluster=sdk.types.Cluster(
            id=vm_def['cluster']
        ),
        template=sdk.types.Template(
          id="00000000-0000-0000-0000-000000000000"
        ),
        cpu=sdk.types.Cpu(
            topology=sdk.types.CpuTopology(
                sockets=vm_def['cpu_count'] // vm_def['cores_pre_socket'],
                cores=vm_def['cores_pre_socket'],
                threads=1
            ),
        ),
        memory=vm_def['memory_bytes']
    )

    vms_service = conn.service('vms')

    logging.info("Adding VM ...")
    vms_service.add(vm)
    logging.info("VM added")


def wait_for_disk_unlocked(disk_service):
    while True:
        disk = disk_service.get()
        if disk.status == sdk.types.DiskStatus.OK:
            break

        if disk.status == sdk.types.DiskStatus.LOCKED:
            logging.debug("Waiting for disk %r to be unlocked.", disk.alias)
            time.sleep(5)
            continue

        raise RuntimeError("Disk %r in illegal status: %s" % (disk.alias, disk.status))


def add_disks_to_ovirt(vm, conn):
    disks_service = conn.service('disks')

    new_disks = []
    for disk_def in vm['disks']:
        if disks_service.list(query={"search": "id=%s" % disk_def["id"]}):
            raise RuntimeError("Disk with id %r already exists. Disk name: %r" % (disk_def['id'], disk_def['name']))

        if not NAME_PATTERN_FULL_STR.match(disk_def['name']):
            logging.warn("Disk name is not compatible with oVirt: %r", disk_def['name'])

            # Generate random name and check if it is free
            while True:
                random_str = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(6))
                new_name = "xen-disk-" + random_str
                logging.debug("Checking if disk name %r exists", new_name)
                if not disks_service.list(query={"search": "alias=%s" % new_name}):
                    break

            disk_def['name'] = new_name
            logging.warn("Using generated name: %r", disk_def['name'])

        disk_def["qcow_size"] = os.path.getsize(disk_def['qcow_file'])

        disk = sdk.types.Disk(
            id=disk_def['id'],
            alias=disk_def['name'],
            format=sdk.types.DiskFormat.COW,
            provisioned_size=disk_def['capacity'],
            initial_size=disk_def['qcow_size'],
            bootable=disk_def['bootable'],
            storage_domains=[
                sdk.types.StorageDomain(
                    id=vm['storage_domain']
                )
            ]
        )

        logging.info("Adding disk: %s", disk_def)
        new_disks.append(disks_service.add(disk))
        logging.info("Disk added")

    for disk in new_disks:
        disk_service = disks_service.service(disk.id)
        wait_for_disk_unlocked(disk_service)


def attach_disks_to_vm(vm_def, conn):
    attachments_service = conn.service('vms/%s/diskattachments' % vm_def['id'])

    for disk in vm_def['disks']:
        logging.info("Attaching disk %r to VM", disk['name'])
        attachments_service.add(sdk.types.DiskAttachment(
            active=True,
            bootable=disk['bootable'],
            interface=sdk.types.DiskInterface.IDE,
            disk=sdk.types.Disk(
                id=disk['id']
            )
        ))
        logging.debug("Disk attached")


class DiskUploader(object):
    CHUNK_SIZE = 32 * 1024 * 1024

    def __init__(self, disk, transfers_service):
        self.disk = disk
        self.transfers_service = transfers_service

    def upload(self):
        logging.debug("Creating image transfer for disk %r", self.disk['name'])
        transfer = self.transfers_service.add(
            sdk.types.ImageTransfer(
                disk=sdk.types.Disk(
                    id=self.disk['id']
                ),
                direction=sdk.types.ImageTransferDirection.UPLOAD
            )
        )

        transfer_service = self.transfers_service.service(transfer.id)
        try:
            self._wait_for_transfer_ready(transfer_service)
            self._transfer_disk(transfer, transfer_service)
        finally:
            transfer_service.finalize()
            logging.info("Transfer finished")

    def _wait_for_transfer_ready(self, transfer_service):
        while True:
            transfer = transfer_service.get()
            if transfer.phase == sdk.types.ImageTransferPhase.TRANSFERRING:
                return

            if transfer.phase in [
                sdk.types.ImageTransferPhase.INITIALIZING,
                sdk.types.ImageTransferPhase.RESUMING
            ]:
                logging.debug("Waiting for image transfer to be ready...")
                time.sleep(1)
                continue

            # TODO - cleanup on error
            raise RuntimeError("Image transfer in invalid phase: %s" % transfer.phase)

    def _transfer_disk(self, transfer, transfer_service):
        logging.debug("Creating proxy connection")
        url = url_parse.urlparse(transfer.proxy_url)
        proxy_connection = http.client.HTTPSConnection(
            url.hostname,
            url.port,
            context=ssl._create_unverified_context()
        )
        proxy_connection.connect()

        logging.info("Transferring disk...")

        transfer_headers = {
            'Authorization': transfer.signed_ticket
        }

        file_size = self.disk['qcow_size']
        logging.debug("File size: %s", file_size)
        with open(self.disk['qcow_file'], "rb") as file:
            start_pos = 0
            for data in iter(lambda: file.read(self.CHUNK_SIZE), b""):
                # Refresh ticket
                transfer_service.extend()

                end_pos = start_pos + len(data) - 1
                transfer_headers['Content-Range'] = "bytes {0}-{1}/{2}".format(start_pos, end_pos, file_size)
                start_pos += len(data)

                proxy_connection.request(
                    'PUT',
                    url.path,
                    data,
                    headers=transfer_headers
                )
                logging.info("Progress: {:.2%}".format((end_pos+1) / float(file_size)))

                response = proxy_connection.getresponse()
                if response.status >= 400:
                    logging.error("HTTP response status: %s", response.status)
                    logging.error("HTTP response reason: %s", response.reason)
                    response_data = response.read(response.length)
                    logging.error("HTTP response data: %r", response_data.decode("UTF-8"))
                    raise RuntimeError("Error uploading disk")


def upload_disks(vm, conn):
    image_transfers_service = conn.service('imagetransfers')
    disks_service = conn.service('disks')

    for disk in vm['disks']:
        uploader = DiskUploader(disk, image_transfers_service)
        uploader.upload()

    for disk in vm['disks']:
        wait_for_disk_unlocked(disks_service.service(disk['id']))

    logging.info("Finished uploading disks")


def main():
    parser = argparse.ArgumentParser(
        description="Creates the VM in oVirt and uploads the disk images using HTTP."
    )
    parser.add_argument("vm", help="path to the vm.json file created by vmextract.py script")
    parser.add_argument("-v", "--verbose", help="show debug messages", action="store_true")
    parser.add_argument("--name", help="name of the VM. Useful in case the original name is not supported in oVirt.")

    required_args = parser.add_argument_group("required arguments")
    required_args.add_argument("--engine", help="URL of the oVirt engine API", required=True)
    required_args.add_argument("--user", help="oVirt user name", required=True)
    required_args.add_argument("--password", help="oVirt user password", required=True)
    required_args.add_argument("--cluster", help="name or ID of the cluster, where the VM will be created.", required=True)
    required_args.add_argument("--domain", help="name or ID of the storage domain, where the VM's disks be created", required=True)

    args = parser.parse_args()

    logging.getLogger().setLevel(
        logging.DEBUG if args.verbose else logging.INFO
    )

    with open(args.vm, "r") as f:
        vm = json.load(f)

    os.chdir(os.path.dirname(args.vm))

    if args.name:
        vm['name'] = args.name

    connection = sdk.Connection(
        url=args.engine,
        username=args.user,
        password=args.password,
        insecure=True
    )

    connection.test(raise_exception=True)

    vm['cluster'] = args.cluster if is_string_uuid(args.cluster) else get_cluster_id_by_name(args.cluster, connection)
    vm['storage_domain'] = args.domain if is_string_uuid(args.domain) else get_domain_id_by_name(args.domain, connection)

    check_cluster_exists(vm['cluster'], connection)
    check_domain_exists(vm['storage_domain'], connection)
    add_vm_to_ovirt(vm, connection)
    add_disks_to_ovirt(vm, connection)
    upload_disks(vm, connection)
    attach_disks_to_vm(vm, connection)


if __name__ == '__main__':
    main()
