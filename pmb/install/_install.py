# Copyright 2020 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import os
import re
import glob
import shlex

import pmb.chroot
import pmb.chroot.apk
import pmb.chroot.other
import pmb.chroot.initfs
import pmb.config
import pmb.config.pmaports
import pmb.helpers.devices
import pmb.helpers.run
import pmb.install.blockdevice
import pmb.install.file
import pmb.install.recovery
import pmb.install


def mount_device_rootfs(args, suffix_rootfs, suffix_mount="native"):
    """
    Mount the device rootfs.
    :param suffix_rootfs: the chroot suffix, where the rootfs that will be
                          installed on the device has been created (e.g.
                          "rootfs_qemu-amd64")
    :param suffix_mount: the chroot suffix, where the device rootfs will be
                         mounted (e.g. "native")
    """
    mountpoint = f"/mnt/{suffix_rootfs}"
    pmb.helpers.mount.bind(args, f"{args.work}/chroot_{suffix_rootfs}",
                           f"{args.work}/chroot_{suffix_mount}{mountpoint}")
    return mountpoint


def get_subpartitions_size(args, suffix):
    """
    Calculate the size of the boot and root subpartition.

    :param suffix: the chroot suffix, e.g. "rootfs_qemu-amd64"
    :returns: (boot, root) the size of the boot and root
              partition as integer in MiB
    """
    boot = int(args.boot_size)

    # Estimate root partition size, then add some free space. The size
    # calculation is not as trivial as one may think, and depending on the
    # file system etc it seems to be just impossible to get it right.
    chroot = f"{args.work}/chroot_{suffix}"
    root = pmb.helpers.other.folder_size(args, chroot) / 1024 / 1024
    root *= 1.20
    root += 50
    return (boot, root)


def get_nonfree_packages(args, device):
    """
    Get the non-free packages based on user's choice in "pmbootstrap init" and
    based on whether there are non-free packages in the APKBUILD or not.

    :returns: list of non-free packages to be installed. Example:
              ["device-nokia-n900-nonfree-firmware"]
    """
    # Read subpackages
    apkbuild = pmb.parse.apkbuild(args, pmb.helpers.devices.find_path(args, device, 'APKBUILD'))
    subpackages = apkbuild["subpackages"]

    # Check for firmware and userland
    ret = []
    prefix = "device-" + device + "-nonfree-"
    if args.nonfree_firmware and prefix + "firmware" in subpackages:
        ret += [prefix + "firmware"]
    if args.nonfree_userland and prefix + "userland" in subpackages:
        ret += [prefix + "userland"]
    return ret


def get_kernel_package(args, device):
    """
    Get the device's kernel subpackage based on the user's choice in
    "pmbootstrap init".

    :param device: code name, e.g. "sony-amami"
    :returns: [] or the package in a list, e.g.
              ["device-sony-amami-kernel-mainline"]
    """
    # Empty list: single kernel devices / "none" selected
    kernels = pmb.parse._apkbuild.kernels(args, device)
    if not kernels or args.kernel == "none":
        return []

    # Sanity check
    if args.kernel not in kernels:
        raise RuntimeError("Selected kernel (" + args.kernel + ") is not"
                           " configured for device " + device + ". Please"
                           " run 'pmbootstrap init' to select a valid kernel.")

    # Selected kernel subpackage
    return ["device-" + device + "-kernel-" + args.kernel]


def get_recommends_packages(args):
    """ Get all packages listed in _pmb_recommends of the UI and UI-extras
        package, unless running with pmbootstrap install --no-recommends.

        :returns: list of pkgnames, e.g. ["chatty", "gnome-contacts"] """
    ret = []
    if not args.install_recommends or args.ui == "none":
        return ret

    # UI package
    meta = f"postmarketos-ui-{args.ui}"
    apkbuild = pmb.helpers.pmaports.get(args, meta)
    recommends = apkbuild["_pmb_recommends"]
    if recommends:
        logging.debug(f"{meta}: install _pmb_recommends:"
                      f" {', '.join(recommends)}")
        ret += recommends

    # UI-extras subpackage
    meta_extras = f"{meta}-extras"
    if args.ui_extras and meta_extras in apkbuild["subpackages"]:
        recommends = apkbuild["subpackages"][meta_extras]["_pmb_recommends"]
        if recommends:
            logging.debug(f"{meta_extras}: install _pmb_recommends:"
                          f" {', '.join(recommends)}")
            ret += recommends

    return ret


def copy_files_from_chroot(args, suffix):
    """
    Copy all files from the rootfs chroot to /mnt/install, except
    for the home folder (because /home will contain some empty
    mountpoint folders).

    :param suffix: the chroot suffix, e.g. "rootfs_qemu-amd64"
    """
    # Mount the device rootfs
    logging.info(f"(native) copy {suffix} to /mnt/install/")
    mountpoint = mount_device_rootfs(args, suffix)
    mountpoint_outside = args.work + "/chroot_native" + mountpoint

    # Remove empty qemu-user binary stub (where the binary was bind-mounted)
    arch_qemu = pmb.parse.arch.alpine_to_qemu(args.deviceinfo["arch"])
    qemu_binary = mountpoint_outside + "/usr/bin/qemu-" + arch_qemu + "-static"
    if os.path.exists(qemu_binary):
        pmb.helpers.run.root(args, ["rm", qemu_binary])

    # Get all folders inside the device rootfs (except for home)
    folders = []
    for path in glob.glob(mountpoint_outside + "/*"):
        if path.endswith("/home"):
            continue
        folders += [os.path.basename(path)]

    # Update or copy all files
    if args.rsync:
        pmb.chroot.apk.install(args, ["rsync"])
        rsync_flags = "-a"
        if args.verbose:
            rsync_flags += "vP"
        pmb.chroot.root(args, ["rsync", rsync_flags, "--delete"] + folders + ["/mnt/install/"],
                        working_dir=mountpoint)
        pmb.chroot.root(args, ["rm", "-rf", "/mnt/install/home"])
    else:
        pmb.chroot.root(args, ["cp", "-a"] + folders + ["/mnt/install/"],
                        working_dir=mountpoint)


def create_home_from_skel(args):
    """
    Create /home/{user} from /etc/skel
    """
    rootfs = args.work + "/chroot_native/mnt/install"
    homedir = rootfs + "/home/" + args.user
    pmb.helpers.run.root(args, ["mkdir", rootfs + "/home"])
    pmb.helpers.run.root(args, ["cp", "-a", rootfs + "/etc/skel", homedir])
    pmb.helpers.run.root(args, ["chown", "-R", "10000", homedir])


def configure_apk(args):
    """
    Copy over all official keys, and the keys used to compile local packages
    (unless --no-local-pkgs is set). Then disable the /mnt/pmbootstrap-packages
    repository.
    """
    # Official keys
    pattern = f"{pmb.config.apk_keys_path}/*.pub"

    # Official keys + local keys
    if args.install_local_pkgs:
        pattern = f"{args.work}/config_apk_keys/*.pub"

    # Copy over keys
    rootfs = args.work + "/chroot_native/mnt/install"
    for key in glob.glob(pattern):
        pmb.helpers.run.root(args, ["cp", key, rootfs + "/etc/apk/keys/"])

    # Disable pmbootstrap repository
    pmb.helpers.run.root(args, ["sed", "-i", r"/\/mnt\/pmbootstrap-packages/d",
                                rootfs + "/etc/apk/repositories"])
    pmb.helpers.run.user(args, ["cat", rootfs + "/etc/apk/repositories"])


def set_user(args):
    """
    Create user with UID 10000 if it doesn't exist.
    Usually the ID for the first user created is 1000, but higher ID is
    chosen here to avoid conflict with Android UIDs/GIDs.

    """
    suffix = "rootfs_" + args.device
    if not pmb.chroot.user_exists(args, args.user, suffix):
        pmb.chroot.root(args, ["adduser", "-D", "-u", "10000", args.user],
                        suffix)
        for group in pmb.config.install_user_groups:
            pmb.chroot.root(args, ["addgroup", "-S", group], suffix,
                            check=False)
            pmb.chroot.root(args, ["addgroup", args.user, group], suffix)


def setup_login(args):
    """
    Loop until the password for user has been set successfully, and disable root
    login.
    """
    suffix = "rootfs_" + args.device
    if not args.on_device_installer:
        # User password
        logging.info(" *** SET LOGIN PASSWORD FOR: '" + args.user + "' ***")
        while True:
            try:
                pmb.chroot.root(args, ["passwd", args.user], suffix,
                                output="interactive")
                break
            except RuntimeError:
                logging.info("WARNING: Failed to set the password. Try it"
                             " one more time.")
                pass

    # Disable root login
    pmb.chroot.root(args, ["passwd", "-l", "root"], suffix)


def copy_ssh_keys(args):
    """
    If requested, copy user's SSH public keys to the device if they exist
    """
    if not args.ssh_keys:
        return
    keys = []
    for key in glob.glob(os.path.expanduser("~/.ssh/id_*.pub")):
        with open(key, "r") as infile:
            keys += infile.readlines()

    if not len(keys):
        logging.info("NOTE: Public SSH keys not found. Since no SSH keys " +
                     "were copied, you will need to use SSH password authentication!")
        return

    authorized_keys = args.work + "/chroot_native/tmp/authorized_keys"
    outfile = open(authorized_keys, "w")
    for key in keys:
        outfile.write("%s" % key)
    outfile.close()

    target = args.work + "/chroot_native/mnt/install/home/" + args.user + "/.ssh"
    pmb.helpers.run.root(args, ["mkdir", target])
    pmb.helpers.run.root(args, ["chmod", "700", target])
    pmb.helpers.run.root(args, ["cp", authorized_keys, target + "/authorized_keys"])
    pmb.helpers.run.root(args, ["rm", authorized_keys])
    pmb.helpers.run.root(args, ["chown", "-R", "10000:10000", target])


def setup_keymap(args):
    """
    Set the keymap with the setup-keymap utility if the device requires it
    """
    suffix = "rootfs_" + args.device
    info = pmb.parse.deviceinfo(args, device=args.device)
    if "keymaps" not in info or info["keymaps"].strip() == "":
        logging.info("NOTE: No valid keymap specified for device")
        return
    options = info["keymaps"].split(' ')
    if (args.keymap != "" and
            args.keymap is not None and
            args.keymap in options):
        layout, variant = args.keymap.split("/")
        pmb.chroot.root(args, ["setup-keymap", layout, variant], suffix,
                        output="interactive")

        # Check xorg config
        config = None
        if os.path.exists(f"{args.work}/chroot_{suffix}/etc/X11/xorg.conf.d"):
            config = pmb.chroot.root(args, ["grep", "-rl", "XkbLayout",
                                            "/etc/X11/xorg.conf.d/"],
                                     suffix, check=False, output_return=True)
        if config:
            # Nokia n900 (RX-51) randomly merges some keymaps so we
            # have to specify a composite keymap for a few countries. See:
            # https://gitlab.freedesktop.org/xkeyboard-config/xkeyboard-config/-/blob/master/symbols/nokia_vndr/rx-51
            if variant == "rx51_fi" or variant == "rx51_se":
                layout = "fise"
            if variant == "rx51_da" or variant == "rx51_no":
                layout = "dano"
            if variant == "rx51_pt" or variant == "rx51_es":
                layout = "ptes"
            # Multiple files can contain the keyboard layout, take last
            config = config.splitlines()[-1]
            old_text = "Option *\\\"XkbLayout\\\" *\\\".*\\\""
            new_text = "Option \\\"XkbLayout\\\" \\\"" + layout + "\\\""
            pmb.chroot.root(args, ["sed", "-i", "s/" + old_text + "/" + new_text + "/", config],
                            suffix)
    else:
        logging.info("NOTE: No valid keymap specified for device")


def setup_hostname(args):
    """
    Set the hostname and update localhost address in /etc/hosts
    """
    # Default to device name
    hostname = args.hostname
    if not hostname:
        hostname = args.device

    if not pmb.helpers.other.validate_hostname(hostname):
        raise RuntimeError("Hostname '" + hostname + "' is not valid, please"
                           " run 'pmbootstrap init' to configure it.")

    suffix = "rootfs_" + args.device
    # Generate /etc/hostname
    pmb.chroot.root(args, ["sh", "-c", "echo " + shlex.quote(hostname) +
                           " > /etc/hostname"], suffix)
    # Update /etc/hosts
    regex = (r"s/^127\.0\.0\.1.*/127.0.0.1\t" + re.escape(hostname) +
             " localhost.localdomain localhost/")
    pmb.chroot.root(args, ["sed", "-i", "-e", regex, "/etc/hosts"], suffix)


def embed_firmware(args, suffix):
    """
    This method will embed firmware, located at /usr/share, that are specified
    by the "sd_embed_firmware" deviceinfo parameter into the SD card image
    (e.g. u-boot). Binaries that would overwrite the first partition are not
    accepted, and if multiple binaries are specified then they will be checked
    for collisions with each other.

    :param suffix: of the chroot, which holds the firmware files (either the
                   f"rootfs_{args.device}", or f"installer_{args.device}")
    """
    if not args.deviceinfo["sd_embed_firmware"]:
        return

    step = 1024
    if args.deviceinfo["sd_embed_firmware_step_size"]:
        try:
            step = int(args.deviceinfo["sd_embed_firmware_step_size"])
        except ValueError:
            raise RuntimeError("Value for "
                               "deviceinfo_sd_embed_firmware_step_size "
                               "is not valid: {}".format(step))

    device_rootfs = mount_device_rootfs(args, suffix)
    binaries = args.deviceinfo["sd_embed_firmware"].split(",")

    # Perform three checks prior to writing binaries to disk: 1) that binaries
    # exist, 2) that binaries do not extend into the first partition, 3) that
    # binaries do not overlap each other
    binary_ranges = {}
    binary_list = []
    for binary_offset in binaries:
        binary, offset = binary_offset.split(':')
        try:
            offset = int(offset)
        except ValueError:
            raise RuntimeError("Value for firmware binary offset is "
                               "not valid: {}".format(offset))
        binary_path = os.path.join(args.work, f"chroot_{suffix}", "usr/share",
                                   binary)
        if not os.path.exists(binary_path):
            raise RuntimeError("The following firmware binary does not "
                               f"exist in the {suffix} chroot: "
                               f"/usr/share/{binary}")
        # Insure that embedding the firmware will not overrun the
        # first partition
        boot_part_start = args.deviceinfo["boot_part_start"] or "2048"
        max_size = (int(boot_part_start) * 512) - (offset * step)
        binary_size = os.path.getsize(binary_path)
        if binary_size > max_size:
            raise RuntimeError("The firmware is too big to embed in the "
                               "disk image {}B > {}B".format(binary_size,
                                                             max_size))
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
        binary_list.append((binary, offset))

    # Write binaries to disk
    for binary, offset in binary_list:
        binary_file = os.path.join("/usr/share", binary)
        logging.info("Embed firmware {} in the SD card image at offset {} with"
                     " step size {}".format(binary, offset, step))
        filename = os.path.join(device_rootfs, binary_file.lstrip("/"))
        pmb.chroot.root(args, ["dd", "if=" + filename, "of=/dev/install",
                               "bs=" + str(step), "seek=" + str(offset)])


def sanity_check_sdcard(args):
    device = args.sdcard
    device_name = os.path.basename(device)
    if not os.path.exists(device):
        raise RuntimeError("{} doesn't exist, is the sdcard plugged?".format(device))
    if os.path.isdir('/sys/class/block/{}'.format(device_name)):
        with open('/sys/class/block/{}/ro'.format(device_name), 'r') as handle:
            ro = handle.read()
        if ro == '1\n':
            raise RuntimeError("{} is read-only, is the sdcard locked?".format(device))


def sanity_check_sdcard_size(args):
    device = args.sdcard
    devpath = os.path.realpath(device)
    sysfs = '/sys/class/block/{}/size'.format(devpath.replace('/dev/', ''))
    if not os.path.isfile(sysfs):
        # This is a best-effort sanity check, continue if it's not checkable
        return

    with open(sysfs) as handle:
        raw = handle.read()

    # Size is in 512-byte blocks
    size = int(raw.strip())
    human = "{:.2f} GiB".format(size / 2 / 1024 / 1024)

    # Warn if the size is larger than 100GiB
    if size > (100 * 2 * 1024 * 1024):
        if not pmb.helpers.cli.confirm(args, f"WARNING: The target disk ({devpath}) is"
                                             " larger than a usual SD card (>100GiB)."
                                             " Are you sure you want to overwrite"
                                             f" this {human} disk?", no_assumptions=True):
            raise RuntimeError("Aborted.")


def sanity_check_ondev_version(args):
    arch = args.deviceinfo["arch"]
    package = pmb.helpers.package.get(args, "postmarketos-ondev", arch)
    ver_pkg = package["version"].split("-r")[0]
    ver_min = pmb.config.ondev_min_version
    if pmb.parse.version.compare(ver_pkg, ver_min) == -1:
        raise RuntimeError("This version of pmbootstrap requires"
                           f" postmarketos-ondev version {ver_min} or"
                           " higher. The postmarketos-ondev found in pmaports"
                           f" / in the binary packages has version {ver_pkg}.")


def install_system_image(args, size_reserve, suffix, root_label="pmOS_root",
                         step=3, steps=5, split=False, sdcard=None):
    """
    :param size_reserve: empty partition between root and boot in MiB (pma#463)
    :param suffix: the chroot suffix, where the rootfs that will be installed
                   on the device has been created (e.g. "rootfs_qemu-amd64")
    :param root_label: label of the root partition (e.g. "pmOS_root")
    :param step: next installation step
    :param steps: total installation steps
    :param split: create separate images for boot and root partitions
    :param sdcard: path to sdcard device (e.g. /dev/mmcblk0) or None
    """
    # Partition and fill image/sdcard
    logging.info(f"*** ({step}/{steps}) PREPARE INSTALL BLOCKDEVICE ***")
    pmb.chroot.shutdown(args, True)
    (size_boot, size_root) = get_subpartitions_size(args, suffix)
    if not args.rsync:
        pmb.install.blockdevice.create(args, size_boot, size_root,
                                       size_reserve, split, sdcard)
        if not split:
            pmb.install.partition(args, size_boot, size_reserve)
    if not split:
        root_id = 3 if size_reserve else 2
        pmb.install.partitions_mount(args, root_id, sdcard)

    pmb.install.format(args, size_reserve, root_label, sdcard)

    # Just copy all the files
    logging.info(f"*** ({step + 1}/{steps}) FILL INSTALL BLOCKDEVICE ***")
    copy_files_from_chroot(args, suffix)
    create_home_from_skel(args)
    configure_apk(args)
    copy_ssh_keys(args)
    embed_firmware(args, suffix)
    pmb.chroot.shutdown(args, True)

    # Convert rootfs to sparse using img2simg
    sparse = args.sparse
    if sparse is None:
        sparse = args.deviceinfo["flash_sparse"] == "true"

    if sparse and not split and not sdcard:
        logging.info("(native) make sparse rootfs")
        pmb.chroot.apk.install(args, ["android-tools"])
        sys_image = args.device + ".img"
        sys_image_sparse = args.device + "-sparse.img"
        pmb.chroot.user(args, ["img2simg", sys_image, sys_image_sparse],
                        working_dir="/home/pmos/rootfs/")
        pmb.chroot.user(args, ["mv", "-f", sys_image_sparse, sys_image],
                        working_dir="/home/pmos/rootfs/")


def print_flash_info(args, step=5, steps=5):
    """ Print flashing information, based on the deviceinfo data and the
        pmbootstrap arguments.

        :param step: installation step number """
    logging.info(f"*** ({step}/{steps}) FLASHING TO DEVICE ***")
    logging.info("Run the following to flash your installation to the"
                 " target device:")

    # System flash information
    method = args.deviceinfo["flash_method"]
    flasher = pmb.config.flashers.get(method, {})
    flasher_actions = flasher.get("actions", {})
    requires_split = flasher.get("split", False)

    if "flash_rootfs" in flasher_actions and not args.sdcard and \
            bool(args.split) == requires_split:
        logging.info("* pmbootstrap flasher flash_rootfs")
        logging.info("  Flashes the generated rootfs image to your device:")
        if args.split:
            logging.info(f"  {args.work}/chroot_native/home/pmos/rootfs/"
                         f"{args.device}-rootfs.img")
        else:
            logging.info(f"  {args.work}/chroot_native/home/pmos/rootfs/"
                         f"{args.device}.img")
            logging.info("  (NOTE: This file has a partition table, which"
                         " contains /boot and / subpartitions. That way we"
                         " don't need to change the partition layout on your"
                         " device.)")

    # if current flasher supports vbmeta and partition is explicitly specified
    # in deviceinfo
    if "flash_vbmeta" in flasher_actions and \
            (args.deviceinfo["flash_fastboot_partition_vbmeta"] or
             args.deviceinfo["flash_heimdall_partition_vbmeta"]):
        logging.info("* pmbootstrap flasher flash_vbmeta")
        logging.info("  Flashes vbmeta image with verification disabled flag.")

    # Most flash methods operate independently of the boot partition.
    # (e.g. an Android boot image is generated). In that case, "flash_kernel"
    # works even when partitions are split or installing for sdcard.
    # This is not possible if the flash method requires split partitions.
    if "flash_kernel" in flasher_actions and \
            (not requires_split or args.split):
        logging.info("* pmbootstrap flasher flash_kernel")
        logging.info("  Flashes the kernel + initramfs to your device:")
        if requires_split:
            logging.info(f"  {args.work}/chroot_native/home/pmos/rootfs/"
                         f"{args.device}-boot.img")
        else:
            logging.info(f"  {args.work}/chroot_rootfs_{args.device}/boot")

    if "boot" in flasher_actions:
        logging.info("  (NOTE: " + method + " also supports booting"
                     " the kernel/initramfs directly without flashing."
                     " Use 'pmbootstrap flasher boot' to do that.)")

    # Export information
    logging.info("* If the above steps do not work, you can also create"
                 " symlinks to the generated files with 'pmbootstrap export'"
                 " and flash outside of pmbootstrap.")


def install_recovery_zip(args):
    logging.info("*** (3/4) CREATING RECOVERY-FLASHABLE ZIP ***")
    suffix = "buildroot_" + args.deviceinfo["arch"]
    mount_device_rootfs(args, f"rootfs_{args.device}", suffix)
    pmb.install.recovery.create_zip(args, suffix)

    # Flash information
    logging.info("*** (4/4) FLASHING TO DEVICE ***")
    logging.info("Flashing with the recovery zip is explained here:")
    logging.info("<https://postmarketos.org/recoveryzip>")


def install_on_device_installer(args, step, steps):
    # Generate the rootfs image
    if args.ondev_rootfs:
        suffix_rootfs = f"rootfs_{args.device}"
        install_system_image(args, 0, suffix_rootfs, step=step, steps=steps,
                             split=True)
        step += 2

    # Prepare the installer chroot
    logging.info(f"*** ({step}/{steps}) CREATE ON-DEVICE INSTALLER ROOTFS ***")
    step += 1
    packages = ([f"device-{args.device}",
                 "postmarketos-ondev"] +
                get_kernel_package(args, args.device) +
                get_nonfree_packages(args, args.device))
    suffix_installer = f"installer_{args.device}"
    pmb.chroot.apk.install(args, packages, suffix_installer)

    # Move rootfs image into installer chroot
    if args.ondev_rootfs:
        img = f"{args.device}-root.img"
        img_path_src = f"{args.work}/chroot_native/home/pmos/rootfs/{img}"
        img_path_dest = f"{args.work}/chroot_{suffix_installer}/var/lib/" \
            "rootfs.img"
        logging.info(f"({suffix_installer}) add {img} as /var/lib/rootfs.img")
        pmb.install.losetup.umount(args, img_path_src)
        pmb.helpers.run.root(args, ["mv", img_path_src, img_path_dest])

    # Run ondev-prepare, so it may generate nice configs from the channel
    # properties (e.g. to display the version number), or transform the image
    # file into another format. This can all be done without pmbootstrap
    # changes in the postmarketos-ondev package.
    logging.info(f"({suffix_installer}) ondev-prepare")
    channel = pmb.config.pmaports.read_config(args)["channel"]
    channel_cfg = pmb.config.pmaports.read_config_channel(args)
    env = {"ONDEV_CHANNEL": channel,
           "ONDEV_CHANNEL_BRANCH_APORTS": channel_cfg["branch_aports"],
           "ONDEV_CHANNEL_BRANCH_PMAPORTS": channel_cfg["branch_pmaports"],
           "ONDEV_CHANNEL_DESCRIPTION": channel_cfg["description"],
           "ONDEV_CHANNEL_MIRRORDIR_ALPINE": channel_cfg["mirrordir_alpine"],
           "ONDEV_CIPHER": args.cipher,
           "ONDEV_PMBOOTSTRAP_VERSION": pmb.config.version,
           "ONDEV_UI": args.ui}
    pmb.chroot.root(args, ["ondev-prepare"], suffix_installer, env=env)

    # Copy files specified with 'pmbootstrap install --ondev --cp'
    if args.ondev_cp:
        for host_src, chroot_dest in args.ondev_cp:
            host_dest = f"{args.work}/chroot_{suffix_installer}/{chroot_dest}"
            logging.info(f"({suffix_installer}) add {host_src} as"
                         f" {chroot_dest}")
            pmb.helpers.run.root(args, ["cp", host_src, host_dest])

    # Remove $DEVICE-boot.img (we will generate a new one if --split was
    # specified, otherwise the separate boot image is not needed)
    if args.ondev_rootfs:
        img_boot = f"{args.device}-boot.img"
        logging.info(f"(native) rm {img_boot}")
        pmb.chroot.root(args, ["rm", f"/home/pmos/rootfs/{img_boot}"])

    # Generate installer image
    size_reserve = round(os.path.getsize(img_path_dest) / 1024 / 1024) + 200
    install_system_image(args, size_reserve, suffix_installer, "pmOS_install",
                         step, steps, args.split, args.sdcard)


def create_device_rootfs(args, step, steps):
    # List all packages to be installed (including the ones specified by --add)
    # and upgrade the installed packages/apkindexes
    logging.info(f'*** ({step}/{steps}) CREATE DEVICE ROOTFS ("{args.device}")'
                 ' ***')

    # Create user before installing packages, so post-install scripts of
    # pmaports can figure out the username (legacy reasons: pmaports#820)
    set_user(args)

    # Fill install_packages
    install_packages = (pmb.config.install_device_packages +
                        ["device-" + args.device] +
                        get_kernel_package(args, args.device) +
                        get_nonfree_packages(args, args.device) +
                        get_recommends_packages(args))
    if not args.install_base:
        install_packages = [p for p in install_packages if p != "postmarketos-base"]
    if args.ui.lower() != "none":
        install_packages += ["postmarketos-ui-" + args.ui]
        if args.ui_extras:
            install_packages += ["postmarketos-ui-" + args.ui + "-extras"]
    if args.extra_packages.lower() != "none":
        install_packages += args.extra_packages.split(",")
    if args.add:
        install_packages += args.add.split(",")

    pmb.helpers.repo.update(args, args.deviceinfo["arch"])

    # Explicitly call build on the install packages, to re-build them or any
    # dependency, in case the version increased
    if args.build_pkgs_on_install:
        for pkgname in install_packages:
            pmb.build.package(args, pkgname, args.deviceinfo["arch"])

    # Install all packages to device rootfs chroot (and rebuild the initramfs,
    # because that doesn't always happen automatically yet, e.g. when the user
    # installed a hook without pmbootstrap - see #69 for more info)
    suffix = "rootfs_" + args.device
    pmb.chroot.apk.install(args, install_packages, suffix)
    pmb.install.file.write_os_release(args, suffix)
    for flavor in pmb.chroot.other.kernel_flavors_installed(args, suffix):
        pmb.chroot.initfs.build(args, flavor, suffix)

    # Set the user password
    setup_login(args)

    # Set the keymap if the device requires it
    setup_keymap(args)

    # Set timezone
    pmb.chroot.root(args, ["setup-timezone", "-z", args.timezone], suffix)

    # Set the hostname as the device name
    setup_hostname(args)


def install(args):
    # Sanity checks
    if not args.android_recovery_zip and args.sdcard:
        sanity_check_sdcard(args)
        sanity_check_sdcard_size(args)
    if args.on_device_installer:
        sanity_check_ondev_version(args)

    # Number of steps for the different installation methods.
    if args.no_image:
        steps = 2
    elif args.android_recovery_zip:
        steps = 4
    elif args.on_device_installer:
        steps = 8 if args.ondev_rootfs else 5
    else:
        steps = 5

    # Install required programs in native chroot
    step = 1
    logging.info(f"*** ({step}/{steps}) PREPARE NATIVE CHROOT ***")
    pmb.chroot.apk.install(args, pmb.config.install_native_packages,
                           build=False)
    step += 1

    if args.ondev_rootfs:
        create_device_rootfs(args, step, steps)
        step += 1

    if args.no_image:
        return
    elif args.android_recovery_zip:
        return install_recovery_zip(args)

    if args.on_device_installer:
        # Runs install_system_image twice
        install_on_device_installer(args, step, steps)
    else:
        install_system_image(args, 0, f"rootfs_{args.device}", step=step,
                             steps=steps, split=args.split, sdcard=args.sdcard)
    print_flash_info(args, steps, steps)
