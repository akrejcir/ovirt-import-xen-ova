
import argparse
import json
import logging
import ovirtsdk4 as sdk
import string
import random
import re
import time


NAME_PATTERN = re.compile("[\w.-]*")


def check_cluster_exists(cluster_id, conn):
    try:
        conn.service("clusters").service(cluster_id).get()
        conn.service("clusters").service("b60a6da0-2dba-11e8-8cdb-001a4c103f15")
    except sdk.NotFoundError:
        raise RuntimeError("Cluster was not found, id: %s" % cluster_id) from None


def add_vm_to_ovirt(vm_def, conn):
    # Check if name is valid
    if not NAME_PATTERN.fullmatch(vm_def['name']):
        raise RuntimeError("Vm name can only contain alpha-numeric characters, '_', '-' or '.'. Vm name: %r" % vm_def['name'])

    # TODO - Check if cluster is name or ID
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


def add_disks_to_ovirt(vm, conn):
    disks_service = conn.service('disks')

    new_disks = []
    for disk_def in vm['disks']:
        if disks_service.list(query={"search": "id=%s" % disk_def["id"]}):
            raise RuntimeError("Disk with id %r already exists. Disk name: %r" % (disk_def['id'], disk_def['name']))

        if not NAME_PATTERN.fullmatch(disk_def['name']):
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

        # TODO - use storage domain name as well as ID
        disk = sdk.types.Disk(
            id=disk_def['id'],
            alias=disk_def['name'],
            format=sdk.types.DiskFormat.COW,
            provisioned_size=disk_def['capacity'],
            bootable=disk_def['bootable'],
            storage_domains=[
                sdk.types.StorageDomain(
                    id=vm['storage_domain']
                )
            ]
        )

        logging.info("Adding disk: %r", disk_def['name'])
        new_disks.append(disks_service.add(disk))
        logging.info("Disk added")

    # Wait until all disks are in ok state
    for disk in new_disks:
        while True:
            disk_status = disks_service.service(disk.id).get().status
            if disk_status == sdk.types.DiskStatus.ILLEGAL:
                raise RuntimeError("Disk %r in illegal state!" % disk.alias)

            if disk_status == sdk.types.DiskStatus.OK:
                break

            logging.debug("Waiting for disk %r to be unlocked.", disk.alias)
            time.sleep(5)


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", help="Show debug messages", action="store_true")
    parser.add_argument("--engine", help="URL of the oVirt engine API", required=True)
    parser.add_argument("--user", help="oVirt user name", required=True)
    parser.add_argument("--password", help="oVirt user password", required=True)
    parser.add_argument("--cluster", help="Name or ID of the cluster, where the VM will be created.", required=True)
    parser.add_argument("--domain", help="Name or ID of the storage domain, where the VM's disks be created")
    parser.add_argument("--name", help="Name of the VM")

    parser.add_argument("vm", help="The vm json file")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    with open(args.vm, "r") as f:
        vm = json.load(f)

    vm['cluster'] = args.cluster
    vm['storage_domain'] = args.domain
    if args.name:
        vm['name'] = args.name

    connection = sdk.Connection(
        url=args.engine,
        username=args.user,
        password=args.password,
        insecure=True
    )

    connection.test(raise_exception=True)

    check_cluster_exists(vm['cluster'], connection)
    add_vm_to_ovirt(vm, connection)
    add_disks_to_ovirt(vm, connection)
    attach_disks_to_vm(vm, connection)


if __name__ == '__main__':
    main()
