# Copyright 2020 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import logging
import pmb.chroot


def format_and_mount_boot(args):
    boot_num = 1
    if args.deviceinfo["sd_embed_firmware"]:
        boot_num = len(args.deviceinfo["sd_embed_firmware"].split(',')) + 1

    mountpoint = "/mnt/install/boot"
    device = "/dev/installp{}".format(boot_num)
    filesystem = args.deviceinfo["boot_filesystem"] or "ext2"
    logging.info("(native) format " + device + " (boot, " + filesystem + "), mount to " +
                 mountpoint)
    if filesystem == "fat16":
        pmb.chroot.root(args, ["mkfs.fat", "-F", "16", "-n", "pmOS_boot", device])
    elif filesystem == "fat32":
        pmb.chroot.root(args, ["mkfs.fat", "-F", "32", "-n", "pmOS_boot", device])
    elif filesystem == "ext2":
        pmb.chroot.root(args, ["mkfs.ext2", "-F", "-q", "-L", "pmOS_boot", device])
    else:
        raise RuntimeError("Filesystem " + filesystem + " is not supported!")
    pmb.chroot.root(args, ["mkdir", "-p", mountpoint])
    pmb.chroot.root(args, ["mount", device, mountpoint])


def format_and_mount_root(args):
    rootfs_num = 2
    if args.deviceinfo["sd_embed_firmware"]:
        rootfs_num = len(args.deviceinfo["sd_embed_firmware"].split(',')) + 2

    mountpoint = "/dev/mapper/pm_crypt"
    device = "/dev/installp{}".format(rootfs_num)
    if args.full_disk_encryption:
        logging.info("(native) format " + device + " (root, luks), mount to " +
                     mountpoint)
        logging.info(
            " *** TYPE IN THE FULL DISK ENCRYPTION PASSWORD (TWICE!) ***")
        pmb.chroot.root(args, ["cryptsetup", "luksFormat", "--use-urandom",
                               "--cipher", args.cipher, "-q", device,
                               "--iter-time", args.iter_time],
                        output="interactive")
        pmb.chroot.root(args, ["cryptsetup", "luksOpen", device,
                               "pm_crypt"], output="interactive")
        if not os.path.exists(args.work + "/chroot_native" + mountpoint):
            raise RuntimeError("Failed to open cryptdevice!")


def format_and_mount_pm_crypt(args):
    # Block device
    if args.full_disk_encryption:
        device = "/dev/mapper/pm_crypt"
    else:
        rootfs_num = 2
        if args.deviceinfo["sd_embed_firmware"]:
            rootfs_num = len(args.deviceinfo["sd_embed_firmware"].split(',')) + 2

        device = "/dev/installp{}".format(rootfs_num)

    # Format
    if not args.rsync:
        logging.info("(native) format " + device)
        # Some downstream kernels don't support metadata_csum (#1364).
        # When changing the options of mkfs.ext4, also change them in the
        # recovery zip code (see 'grep -r mkfs\.ext4')!
        mkfs_ext4_args = ["mkfs.ext4", "-O", "^metadata_csum", "-F",
                          "-q", "-L", "pmOS_root"]

        # When we don't know the file system size before hand like
        # with non-block devices, we need to explicitely set a number of
        # inodes. See #1717 and #1845 for details
        if not args.sdcard:
            mkfs_ext4_args = mkfs_ext4_args + ["-N", "100000"]

        pmb.chroot.root(args, mkfs_ext4_args + [device])

    # Mount
    mountpoint = "/mnt/install"
    logging.info("(native) mount " + device + " to " + mountpoint)
    pmb.chroot.root(args, ["mkdir", "-p", mountpoint])
    pmb.chroot.root(args, ["mount", device, mountpoint])


def format(args):
    format_and_mount_root(args)
    format_and_mount_pm_crypt(args)
    format_and_mount_boot(args)
