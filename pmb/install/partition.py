# Copyright 2020 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import math
import os
import time
import pmb.chroot
import pmb.config
import pmb.install.losetup


def partitions_mount(args):
    """
    Mount blockdevices of partitions inside native chroot
    """
    prefix = args.sdcard
    if not args.sdcard:
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

    partitions = 2
    if args.deviceinfo["sd_embed_firmware"]:
        partitions += len(args.deviceinfo["sd_embed_firmware"].split(','))

    for i in range(1, partitions + 1):
        source = prefix + partition_prefix + str(i)
        target = args.work + "/chroot_native/dev/installp" + str(i)
        pmb.helpers.mount.bind_file(args, source, target)


def partition(args, size_boot):
    """
    Partition /dev/install and create /dev/install{p1,p2,...}

    size_boot: size of the boot partition in bytes.
    """

    sector_size = 512

    # Convert to MB and print info
    size_boot = math.ceil(size_boot / sector_size)
    start_boot = 2048

    filesystem = args.deviceinfo["boot_filesystem"] or "ext2"

    bootpart_num = 1

    # Actual partitioning with 'parted'. Using check=False, because parted
    # sometimes "fails to inform the kernel". In case it really failed with
    # partitioning, the follow-up mounting/formatting will not work, so it
    # will stop there (see #463).
    boot_part_start = args.deviceinfo["boot_part_start"] or "2048"

    commands = [
        ["mktable", "msdos"],
    ]

    table = []

    # Create a partition that contains a bootloader (like u-boot) when needed
    # instead of writing u-boot to the raw disk
    if args.deviceinfo["sd_embed_firmware"]:

        step = 1024
        if args.deviceinfo["sd_embed_firmware_step_size"]:
            try:
                step = int(args.deviceinfo["sd_embed_firmware_step_size"])
            except ValueError:
                raise RuntimeError("Value for "
                                   "deviceinfo_sd_embed_firmware_step_size "
                                   "is not valid: {}".format(step))

        # Partitions have to be sector aligned in mbr
        multiplier = int(step / sector_size)

        binaries = args.deviceinfo["sd_embed_firmware"].split(",")

        if len(binaries) > 2:
            raise RuntimeError("No more than 2 firmware embeds allowed due too partition count limits")

        # Perform three checks prior to writing binaries to disk: 1) that binaries
        # exist, 2) that binaries do not overlap each other
        binary_ranges = {}
        binary_list = []
        for binary_offset in binaries:
            binary, offset = binary_offset.split(':')
            try:
                offset = int(offset)
            except ValueError:
                raise RuntimeError("Value for firmware binary offset is "
                                   "not valid: {}".format(offset))
            binary_path = os.path.join(args.work, "chroot_rootfs_" +
                                       args.device, "usr/share", binary)
            if not os.path.exists(binary_path):
                raise RuntimeError("The following firmware binary does not "
                                   "exist in the device rootfs: "
                                   "{}".format("/usr/share/" + binary))

            binary_size = os.path.getsize(binary_path)

            # Insure that the firmware does not conflict with any other firmware
            # that will be embedded
            binary_start = offset * step
            binary_end = binary_start + binary_size
            for start, end in binary_ranges.items():
                if ((binary_start >= start and binary_start <= end) or
                        (binary_end >= start and binary_end <= end)):
                    raise RuntimeError("The firmware overlaps with at least one "
                                       "other firmware image: {}".format(binary))
            binary_ranges[binary_start] = binary_end
            binary_list.append((offset, binary_size))

            binary_end_sector = math.ceil(binary_end / sector_size)

        binary_n = 1
        for offset, size in binary_list:
            start_sector = offset * multiplier

            if binary_n == len(binaries):
                # Add 10% extra space in the partition if this is the last file
                size = int(size * 1.1)
                end_sector = start_sector + (math.ceil(size / sector_size))
                # Make sure next partition is perfectly aligned
                end_sector += 2048 - ( end_sector % 2048) - 1
                if end_sector + 1 > start_boot:
                    start_boot = end_sector + 1
            else:
                # Make the partition as large as the gap between files
                end_sector = binaries[binary_n][0] - 1

            start = "{}s".format(start_sector)
            end = "{}s".format(end_sector)
            commands.extend([
                ["mkpart", "primary", "fat16", start, end]
            ])
            table.append(['firmware {}'.format(binary_n), start, end])
            binary_n += 1

        bootpart_num = len(binaries) + 1

    end_boot = "{}s".format(start_boot + size_boot)
    start_rootfs = start_boot + size_boot + 1
    start_rootfs += 2048 - ( start_rootfs % 2048 )
    start_rootfs = "{}s".format(start_rootfs)
    start_boot = "{}s".format(start_boot)

    commands.extend([
        ["mkpart", "primary", filesystem, start_boot, end_boot],
        ["mkpart", "primary", start_rootfs, "100%"],
        ["set", str(bootpart_num), "boot", "on"]
    ])
    table.append(['boot partition', start_boot, end_boot])
    table.append(['rootfs', start_rootfs, '100% '])

    logging.info('Calculated disk contents (offsets in 512 byte sectors):')
    logging.info('| Description    | Start      | End        |')
    logging.info('| -------------- | ---------- | ---------- |')
    logging.info('| MBR            | 0          | 1          |')
    for row in table:
        logging.info('| {0: <14} | {1: <10} | {2: <10} |'.format(row[0], row[1][:-1], row[2][:-1]))

    for command in commands:
        pmb.chroot.root(args, ["parted", "-s", "/dev/install"] +
                        command, check=False)
