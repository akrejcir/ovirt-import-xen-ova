
import argparse
import json
import logging
import ovirtsdk4 as sdk
import re


VM_NAME_PATTERN = re.compile("[\w.-]*")


def check_cluster_exists(cluster_id, conn):
    try:
        conn.service("clusters").service(cluster_id).get()
        conn.service("clusters").service("b60a6da0-2dba-11e8-8cdb-001a4c103f15")
    except sdk.NotFoundError:
        raise RuntimeError("Cluster was not found, id: %s" % cluster_id) from None


def add_vm_to_ovirt(vm_def, conn):
    # Check if name is valid
    if not VM_NAME_PATTERN.fullmatch(vm_def['name']):
        raise RuntimeError("Vm name can only contain alpha-numeric characters, '_', '-' or '.'. Vm name: %r" % vm_def['name'])

    # TODO - Check if cluster is name or ID
    vm = sdk.types.Vm(
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


if __name__ == '__main__':
    main()
