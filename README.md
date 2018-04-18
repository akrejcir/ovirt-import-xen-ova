## Conversion scripts from Xen to oVirt

These scripts can be used to convert virtual machines from Xen to oVirt.  

### Scripts

- `vmextract.py` Extracts information from OVA file containing the Xen source VM.
- `upload.py` Uploads the VM to oVirt.

### Example Usage

```bash
vmextract.py --verbose CentOS-7-vm.ova

upload.py --verbose \
    --engine 'https://example.com/ovirt-engine/api' \
    --user 'admin@internal' \
    --password 'pasword' \
    --cluster '12345678-9012-3456-7890-123456789012' \
    --domain '98765432-1098-7654-3210-987654321098' \
    --name 'vm-name' \
    CentOS-7-vm/vm.json
```


