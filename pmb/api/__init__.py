import sys

import pmb.parse
import pmb.helpers.logging
import pmb.helpers.devices
from pmb.api.structs import DeviceInfo

_args = None

if _args is None:
    sys.argv = ["pmbootstrap.py", "chroot"]
    _args = pmb.parse.arguments()
    _args.log = _args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(_args)


def list_deviceinfos():
    """ Get a list of all devices with the information contained in the deviceinfo

    :returns: list of DeviceInfo objects for all known devices
    :rtype: List[DeviceInfo]
    """
    raw = pmb.helpers.devices.list_deviceinfos(_args)
    result = []
    for device in raw:
        dev = raw[device]
        row = DeviceInfo()
        row.code = device
        row.name = dev["name"]
        row.manufacturer = dev["manufacturer"]
        row.date = dev["date"]
        row.keyboard = dev["keyboard"]
        row.keymaps = dev["keymaps"].split()
        row.nonfree = dev["nonfree"]
        row.dtb = dev["dtb"]
        row.modules_initramfs = dev["modules_initramfs"].split() if "modules_initramfs" in dev else []
        row.external_storage = dev["external_storage"] if "external_storage" in dev else False
        row.flash_method = dev["flash_method"] if "flash_method" in dev else "none"
        row.arch = dev["arch"]
        row.dev_touchscreen = dev["dev_touchscreen"]
        row.dev_touchscreen_calibration = dev["dev_touchscreen_calibration"]
        row.dev_keyboard = dev["dev_keyboard"]
        row.swap_size_recommended = dev["swap_size_recommended"] if "swap_size_recommended" in dev else None
        row.disable_dhcpd = dev["disable_dhcpd"] if "disable_dhcpd" in dev else False
        row.flash_offset_kernel = dev["flash_offset_kernel"] if "flash_offset_kernel" in dev else None
        row.flash_offset_ramdisk = dev["flash_offset_ramdisk"] if "flash_offset_ramdisk" in dev else None
        row.flash_offset_second = dev["flash_offset_second"] if "flash_offset_second" in dev else None
        row.flash_offset_tags = dev["flash_offset_tags"] if "flash_offset_tags" in dev else None
        row.flash_offset_base = dev["flash_offset_base"] if "flash_offset_base" in dev else None
        row.flash_pagesize = dev["flash_pagesize"] if "flash_pagesize" in dev else None
        row.flash_sparse = dev["flash_sparse"] if "flash_sparse" in dev else False
        row.flash_fastboot_vendor_id = dev["flash_fastboot_vendor_id"] if "flash_fastboot_vendor_id" in dev else None
        row.flash_fastboot_max_size = dev["flash_fastboot_max_size"] if "flash_fastboot_max_size" in dev else None
        row.kernel_cmdline = dev["kernel_cmdline"] if "kernel_cmdline" in dev else None
        row.bootimg_blobpack = dev["bootimg_blobpack"] if "bootimg_blobpack" in dev else False
        row.bootimg_qcdt = dev["bootimg_qcdt"] if "bootimg_qcdt" in dev else False
        row.generate_bootimg = dev["generate_bootimg"] if "generate_bootimg" in dev else False
        row.generate_legacy_uboot_initfs = dev[
            "generate_legacy_uboot_initfs"] if "generate_legacy_uboot_initfs" in dev else False
        row.heimdall_partition_kernel = dev[
            "heimdall_partition_kernel"] if "heimdall_partition_kernel" in dev else "KERNEL"
        row.heimdall_partition_initfs = dev[
            "heimdall_partition_initfs"] if "heimdall_partition_initfs" in dev else "RECOVERY"
        row.heimdall_partition_system = dev[
            "heimdall_partition_system"] if "heimdall_partition_system" in dev else "SYSTEM"
        row.weston_pixman_type = dev["weston_pixman_type"] if "weston_pixman_type" in dev else None
        row.screen_width = dev["screen_width"] if "screen_width" in dev else None
        row.screen_height = dev["screen_height"] if "screen_height" in dev else None
        result.append(row)
    return list(sorted(result, key=lambda k: k.code))
