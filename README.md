## Conversion scripts from Xen to oVirt

These scripts can be used to convert virtual machines from Xen to oVirt.  

### Extracting VM from Xen OVA

The script `vmextract.py` extracts information from the Xen OVA file containing the Xen source VM.

The following information is extracted from the OVA and stored to a `vm.json` file:
- Number of CPUs and the number of cores per socket
- Memory size
- For each disk:
  - Image file
  - Capacity
  - Bootable flag

Then each disk iamge is converted from VHD format to qcow2 format by running `qemu-img convert` utility.

##### Example
```bash
python vmextract.py --verbose CentOS-7-vm.ova
```

### Uploading VM to oVirt

The script `upload.py` uploads the VM to oVirt using the python SDK.

The script does theses steps:
- Creates the VM
- Creates disks
- Transfers the disk images to oVirt using the HTTP image transfer mechanism
- Assigns the disks to the VM

Network is not attached automatically to the new VM.

##### Example
```bash
python upload.py --verbose \
    --engine 'https://example.com/ovirt-engine/api' \
    --user 'admin@internal' \
    --password 'pasword' \
    --cluster '12345678-9012-3456-7890-123456789012' \
    --domain '98765432-1098-7654-3210-987654321098' \
    --name 'vm-name' \
    CentOS-7-vm/vm.json
```
