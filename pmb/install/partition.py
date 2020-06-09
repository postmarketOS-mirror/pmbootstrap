# Copyright 2020 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import os
import time
import pmb.chroot
import pmb.config
import pmb.install.losetup


def partitions_mount(args, root_id, sdcard):
    """
    Mount blockdevices of partitions inside native chroot
    :param root_id: root partition id (3 with --reserve-space, otherwise 2)
    :param sdcard: path to sdcard device (e.g. /dev/mmcblk0) or None
    """
    prefix = sdcard
    if not sdcard:
        img_path = "/home/pmos/rootfs/" + args.device + ".img"
        prefix = pmb.install.losetup.device_by_back_file(args, img_path)

    partition_prefix = None
    tries = 20
    for i in range(tries):
        for symbol in ["p", ""]:
            if os.path.exists(prefix + symbol + "1"):
                partition_prefix = symbol
        if partition_prefix is not None:
            break
        logging.debug("NOTE: (" + str(i + 1) + "/" + str(tries) + ") failed to find"
                      " the install partition. Retrying...")
        time.sleep(0.1)

    if partition_prefix is None:
        raise RuntimeError("Unable to find the partition prefix,"
                           " expected the first partition of " +
                           prefix + " to be located at " + prefix +
                           "1 or " + prefix + "p1!")

    for i in [1, root_id]:
        source = prefix + partition_prefix + str(i)
        target = args.work + "/chroot_native/dev/installp" + str(i)
        pmb.helpers.mount.bind_file(args, source, target)


def partition(args, size_boot, size_reserve):
    """
    Partition /dev/install and create /dev/install{p1,p2,p3}:
    * /dev/installp1: boot
    * /dev/installp2: root (or reserved space)
    * /dev/installp3: (root, if reserved space > 0)

    :param size_boot: size of the boot partition in MB
    :param size_reserve: empty partition between root and boot in MB (pma#463)
    """
    # Convert to MB and print info
    mb_boot = f"{round(size_boot)}M"
    mb_reserved = f"{round(size_reserve)}M"
    mb_root_start = f"{round(size_boot) + round(size_reserve)}M"
    logging.info(f"(native) partition /dev/install (boot: {mb_boot},"
                 f" reserved: {mb_reserved}, root: the rest)")

    filesystem = args.deviceinfo["boot_filesystem"] or "ext2"

    # Actual partitioning with 'parted'. Using check=False, because parted
    # sometimes "fails to inform the kernel". In case it really failed with
    # partitioning, the follow-up mounting/formatting will not work, so it
    # will stop there (see #463).
    boot_part_start = args.deviceinfo["boot_part_start"] or "2048"

    commands = [
        ["mktable", "msdos"],
        ["mkpart", "primary", filesystem, boot_part_start + 's', mb_boot],
    ]

    if size_reserve:
        commands += [["mkpart", "primary", mb_boot, mb_reserved]]

    commands += [
        ["mkpart", "primary", mb_root_start, "100%"],
        ["set", "1", "boot", "on"]
    ]

    for command in commands:
        pmb.chroot.root(args, ["parted", "-s", "/dev/install"] +
                        command, check=False)
