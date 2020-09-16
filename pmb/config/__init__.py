# Copyright 2020 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import multiprocessing
import os

#
# Exported functions
#
from pmb.config.load import load
from pmb.config.save import save
from pmb.config.merge_with_args import merge_with_args


#
# Exported variables (internal configuration)
#
version = "1.22.2"
pmb_src = os.path.normpath(os.path.realpath(__file__) + "/../../..")
apk_keys_path = pmb_src + "/pmb/data/keys"

# Update this frequently to prevent a MITM attack with an outdated version
# (which may contain a vulnerable apk/libressl, and allows an attacker to
# exploit the system!)
apk_tools_static_min_version = "2.10.5-r0"

# postmarketOS aports compatibility (checked against "version" in pmaports.cfg)
pmaports_min_version = "7"

# Version of the work folder (as asked during 'pmbootstrap init'). Increase
# this number, whenever migration is required and provide the migration code,
# see migrate_work_folder()).
work_version = 5

# Minimum required version of postmarketos-ondev (pmbootstrap install --ondev)
ondev_min_version = "0.2.0"

# Programs that pmbootstrap expects to be available from the host system. Keep
# in sync with README.md, and try to keep the list as small as possible. The
# idea is to run almost everything in Alpine chroots.
required_programs = ["git", "openssl", "ps", "sudo"]

# Keys saved in the config file (mostly what we ask in 'pmbootstrap init')
config_keys = ["aports",
               "ccache_size",
               "device",
               "extra_packages",
               "hostname",
               "build_pkgs_on_install",
               "is_default_channel",
               "jobs",
               "kernel",
               "keymap",
               "nonfree_firmware",
               "nonfree_userland",
               "ssh_keys",
               "timezone",
               "ui",
               "ui_extras",
               "user",
               "work",
               "boot_size"]

# Config file/commandline default values
# $WORK gets replaced with the actual value for args.work (which may be
# overridden on the commandline)
defaults = {
    "aports": "$WORK/cache_git/pmaports",
    "ccache_size": "5G",
    "is_default_channel": True,
    "cipher": "aes-xts-plain64",
    "config": (os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser("~/.config")) + "/pmbootstrap.cfg",
    "device": "qemu-amd64",
    "extra_packages": "none",
    "fork_alpine": False,
    "hostname": "",
    "build_pkgs_on_install": True,
    # A higher value is typically desired, but this can lead to VERY long open
    # times on slower devices due to host systems being MUCH faster than the
    # target device (see issue #429).
    "iter_time": "200",
    "jobs": str(multiprocessing.cpu_count() + 1),
    "kernel": "stable",
    "keymap": "",
    "log": "$WORK/log.txt",
    "mirror_alpine": "http://dl-2.alpinelinux.org/alpine/",
    "mirrors_postmarketos": ["http://mirror.postmarketos.org/postmarketos/"],
    "nonfree_firmware": True,
    "nonfree_userland": False,
    "port_distccd": "33632",
    "ssh_keys": False,
    "timezone": "GMT",
    "ui": "weston",
    "ui_extras": False,
    "user": "user",
    "work": os.path.expanduser("~") + "/.local/var/pmbootstrap",
    "boot_size": "128",
}

#
# CHROOT
#

# Usually the ID for the first user created is 1000. However, we want
# pmbootstrap to work even if the 'user' account inside the chroots has
# another UID, so we force it to be different.
chroot_uid_user = "12345"

# The PATH variable used inside all chroots
chroot_path = ":".join([
    "/usr/lib/ccache/bin",
    "/usr/local/sbin",
    "/usr/local/bin",
    "/usr/sbin:/usr/bin",
    "/sbin",
    "/bin"
])

# The PATH variable used on the host, to find the "chroot" and "sh"
# executables. As pmbootstrap runs as user, not as root, the location
# for the chroot executable may not be in the PATH (Debian).
chroot_host_path = os.environ["PATH"] + ":/usr/sbin/"

# Folders, that get mounted inside the chroot
# $WORK gets replaced with args.work
# $ARCH gets replaced with the chroot architecture (eg. x86_64, armhf)
# $CHANNEL gets replaced with the release channel (e.g. edge, stable)
chroot_mount_bind = {
    "/proc": "/proc",
    "$WORK/cache_apk_$ARCH": "/var/cache/apk",
    "$WORK/cache_ccache_$ARCH": "/mnt/pmbootstrap-ccache",
    "$WORK/cache_distfiles": "/var/cache/distfiles",
    "$WORK/cache_git": "/mnt/pmbootstrap-git",
    "$WORK/cache_rust": "/mnt/pmbootstrap-rust",
    "$WORK/config_abuild": "/mnt/pmbootstrap-abuild-config",
    "$WORK/config_apk_keys": "/etc/apk/keys",
    "$WORK/packages/$CHANNEL": "/mnt/pmbootstrap-packages",
}

# Building chroots (all chroots, except for the rootfs_ chroot) get symlinks in
# the "pmos" user's home folder pointing to mountfolders from above.
# Rust packaging is new and still a bit weird in Alpine and postmarketOS. As of
# writing, we only have one package (squeekboard), and use cargo to download
# the source of all dependencies at build time and compile it. Usually, this is
# a no-go, but at least until this is resolved properly, let's cache the
# dependencies and downloads as suggested in "Caching the Cargo home in CI":
# https://doc.rust-lang.org/cargo/guide/cargo-home.html
chroot_home_symlinks = {
    "/mnt/pmbootstrap-abuild-config": "/home/pmos/.abuild",
    "/mnt/pmbootstrap-ccache": "/home/pmos/.ccache",
    "/mnt/pmbootstrap-packages": "/home/pmos/packages/pmos",
    "/mnt/pmbootstrap-rust/registry/index": "/home/pmos/.cargo/registry/index",
    "/mnt/pmbootstrap-rust/registry/cache": "/home/pmos/.cargo/registry/cache",
    "/mnt/pmbootstrap-rust/git/db": "/home/pmos/.cargo/git/db",
}

# Device nodes to be created in each chroot. Syntax for each entry:
# [permissions, type, major, minor, name]
chroot_device_nodes = [
    [666, "c", 1, 3, "null"],
    [666, "c", 1, 5, "zero"],
    [666, "c", 1, 7, "full"],
    [644, "c", 1, 8, "random"],
    [644, "c", 1, 9, "urandom"],
]

# Age in hours that we keep the APKINDEXes before downloading them again.
# You can force-update them with 'pmbootstrap update'.
apkindex_retention_time = 4


# When chroot is considered outdated (in seconds)
chroot_outdated = 3600 * 24 * 2

#
# BUILD
#
# Officially supported host/target architectures for postmarketOS. Only
# specify architectures supported by Alpine here. For cross-compiling,
# we need to generate the "musl-$ARCH", "binutils-$ARCH" and "gcc-$ARCH"
# packages (use "pmbootstrap aportgen musl-armhf" etc.).
build_device_architectures = ["armhf", "armv7", "aarch64", "x86_64", "x86"]

# Packages, that will be installed in a chroot before it builds packages
# for the first time
build_packages = ["abuild", "build-base", "ccache", "git"]

# Necessary kernel config options
necessary_kconfig_options = {
    ">=0.0.0": {  # all versions
        "all": {  # all arches
            "ANDROID_PARANOID_NETWORK": False,
            "BLK_DEV_INITRD": True,
            "CGROUPS": True,
            "CRYPTO_XTS": True,
            "DEVTMPFS": True,
            "DM_CRYPT": True,
            "EXT4_FS": True,
            "KINETO_GAN": False,
            "PFT": False,
            "SYSVIPC": True,
            "USE_VFB": False,
            "VT": True,
        }
    },
    ">=4.0.0": {
        "all": {
            "UEVENT_HELPER": True,
            "USER_NS": True,
        },
    },
    "<5.2.0": {
        "armhf armv7 x86": {
            "LBDAF": True
        }
    }
}

# Necessary anbox kernel config options
necessary_kconfig_options_anbox = {
    ">=0.0.0": {  # all versions
        "all": {  # all arches
            "SQUASHFS": True,
            "SQUASHFS_XZ": True,
            "SQUASHFS_XATTR": True,
            "TMPFS_XATTR": True,
            "ASHMEM": True,
            "ANDROID_BINDER_IPC": True,
            "ANDROID_BINDERFS": False,
            "ANDROID_BINDER_DEVICES": ["binder", "hwbinder"],
            "NETFILTER_XTABLES": True,
            "NETFILTER_XT_MATCH_COMMENT": True,
            "IP_NF_MANGLE": True,
            "FUSE_FS": True,
            "BLK_DEV_LOOP": True,
            "TUN": True,
            "VETH": True,
            "VLAN_8021Q": True,  # prerequisite for bridge
            "BRIDGE": True,
            "BRIDGE_VLAN_FILTERING": True,
        }
    },
}

#
# PARSE
#

# Variables belonging to a package or subpackage in APKBUILD files
apkbuild_package_attributes = {
    "pkgdesc": {},
    "depends": {"array": True},
    "provides": {"array": True},

    # UI meta-packages can specify apps in "_pmb_recommends" to be explicitly
    # installed by default, and not implicitly as dependency of the UI meta-
    # package ("depends"). This makes these apps uninstallable, without
    # removing the meta-package. (#1933). To disable this feature, use:
    # "pmbootstrap install --no-recommends".
    "_pmb_recommends": {"array": True},
}

# Variables in APKBUILD files, that get parsed
apkbuild_attributes = {
    **apkbuild_package_attributes,

    "arch": {"array": True},
    "depends_dev": {"array": True},
    "makedepends": {"array": True},
    "checkdepends": {"array": True},
    "options": {"array": True},
    "pkgname": {},
    "pkgrel": {},
    "pkgver": {},
    "subpackages": {},
    "url": {},

    # cross-compilers
    "makedepends_build": {"array": True},
    "makedepends_host": {"array": True},

    # kernels
    "_flavor": {},
    "_device": {},
    "_kernver": {},
    "_outdir": {},

    # mesa
    "_llvmver": {},

    # Overridden packages
    "_pkgver": {},
    "_pkgname": {},

    # git commit
    "_commit": {},
    "source": {"array": True},
}

# Reference: https://postmarketos.org/apkbuild-options
apkbuild_custom_valid_options = [
    "!pmb:crossdirect",
    "!pmb:kconfig-check",
    "pmb:kconfigcheck-anbox",
    "pmb:cross-native",
    "pmb:strict",
]

# Variables from deviceinfo. Reference: <https://postmarketos.org/deviceinfo>
deviceinfo_attributes = [
    # general
    "format_version",
    "name",
    "manufacturer",
    "codename",
    "year",
    "dtb",
    "modules_initfs",
    "arch",

    # device
    "chassis",
    "keyboard",
    "external_storage",
    "screen_width",
    "screen_height",
    "dev_touchscreen",
    "dev_touchscreen_calibration",

    # bootloader
    "flash_method",
    "boot_filesystem",

    # flash
    "flash_heimdall_partition_kernel",
    "flash_heimdall_partition_initfs",
    "flash_heimdall_partition_system",
    "flash_heimdall_partition_vbmeta",
    "flash_fastboot_partition_kernel",
    "flash_fastboot_partition_system",
    "flash_fastboot_partition_vbmeta",
    "generate_legacy_uboot_initfs",
    "kernel_cmdline",
    "generate_bootimg",
    "bootimg_qcdt",
    "bootimg_mtk_mkimage",
    "bootimg_dtb_second",
    "flash_offset_base",
    "flash_offset_kernel",
    "flash_offset_ramdisk",
    "flash_offset_second",
    "flash_offset_tags",
    "flash_pagesize",
    "flash_fastboot_max_size",
    "flash_sparse",
    "rootfs_image_sector_size",
    "sd_embed_firmware",
    "sd_embed_firmware_step_size",
    "partition_blacklist",
    "boot_part_start",

    # weston
    "weston_pixman_type",

    # keymaps
    "keymaps",
]

# Valid types for the 'chassis' atribute in deviceinfo
# See https://www.freedesktop.org/software/systemd/man/machine-info.html
deviceinfo_chassis_types = [
    "desktop",
    "laptop",
    "convertible",
    "server",
    "tablet",
    "handset",
    "watch",
    "embedded",
    "vm"
]

#
# INITFS
#
initfs_hook_prefix = "postmarketos-mkinitfs-hook-"
default_ip = "172.16.42.1"


#
# INSTALL
#

# Packages, that will be installed inside the native chroot to perform
# the installation to the device.
# util-linux: losetup, fallocate
install_native_packages = ["cryptsetup", "util-linux", "e2fsprogs", "parted", "dosfstools"]
install_device_packages = ["postmarketos-base"]

# Groups for the default user
install_user_groups = ["wheel", "video", "audio", "input", "plugdev", "netdev"]

#
# FLASH
#

flash_methods = ["fastboot", "heimdall", "0xffff", "uuu", "none"]

# These folders will be mounted at the same location into the native
# chroot, before the flash programs get started.
flash_mount_bind = [
    "/sys/bus/usb/devices/",
    "/sys/dev/",
    "/sys/devices/",
    "/dev/bus/usb/"
]

"""
Flasher abstraction. Allowed variables:

$BOOT: Path to the /boot partition
$FLAVOR: Kernel flavor
$IMAGE: Path to the combined boot/rootfs image
$IMAGE_SPLIT_BOOT: Path to the (split) boot image
$IMAGE_SPLIT_ROOT: Path to the (split) rootfs image
$PARTITION_KERNEL: Partition to flash the kernel/boot.img to
$PARTITION_SYSTEM: Partition to flash the rootfs to

Fastboot specific: $KERNEL_CMDLINE
Heimdall specific: $PARTITION_INITFS
uuu specific: $UUU_SCRIPT
"""
flashers = {
    "fastboot": {
        "depends": ["android-tools", "avbtool"],
        "actions": {
            "list_devices": [["fastboot", "devices", "-l"]],
            "flash_rootfs": [["fastboot", "flash", "$PARTITION_SYSTEM",
                              "$IMAGE"]],
            "flash_kernel": [["fastboot", "flash", "$PARTITION_KERNEL",
                              "$BOOT/boot.img-$FLAVOR"]],
            "flash_vbmeta": [
                # Generate vbmeta image with "disable verification" flag
                ["avbtool", "make_vbmeta_image", "--flags", "2",
                    "--padding_size", "$FLASH_PAGESIZE",
                    "--output", "/vbmeta.img"],
                ["fastboot", "flash", "$PARTITION_VBMETA", "/vbmeta.img"],
                ["rm", "-f", "/vbmeta.img"]
            ],
            "boot": [["fastboot", "--cmdline", "$KERNEL_CMDLINE",
                      "boot", "$BOOT/boot.img-$FLAVOR"]],
        },
    },
    # Some devices provide Fastboot but using Android boot images is not practical
    # for them (e.g. because they support booting from FAT32 partitions directly
    # and/or the Android boot partition is too small). This can be implemented
    # using --split (separate image files for boot and rootfs).
    # This flasher allows flashing the split image files using Fastboot.
    "fastboot-bootpart": {
        "split": True,
        "depends": ["android-tools"],
        "actions": {
            "list_devices": [["fastboot", "devices", "-l"]],
            "flash_rootfs": [["fastboot", "flash", "$PARTITION_SYSTEM",
                              "$IMAGE_SPLIT_ROOT"]],
            "flash_kernel": [["fastboot", "flash", "$PARTITION_KERNEL",
                              "$IMAGE_SPLIT_BOOT"]],
            # TODO: Add support for boot
        },
    },
    # Some Samsung devices need the initramfs to be baked into the kernel (e.g.
    # i9070, i9100). We want the initramfs to be generated after the kernel was
    # built, so we put the real initramfs on another partition (e.g. RECOVERY)
    # and load it from the initramfs in the kernel. This method is called
    # "isorec" (isolated recovery), a term coined by Lanchon.
    "heimdall-isorec": {
        "depends": ["heimdall"],
        "actions": {
            "list_devices": [["heimdall", "detect"]],
            "flash_rootfs": [
                ["heimdall_wait_for_device.sh"],
                ["heimdall", "flash", "--$PARTITION_SYSTEM", "$IMAGE"]],
            "flash_kernel": [["heimdall_flash_kernel.sh",
                              "$BOOT/initramfs-$FLAVOR", "$PARTITION_INITFS",
                              "$BOOT/vmlinuz-$FLAVOR", "$PARTITION_KERNEL"]]
        },
    },
    # Some Samsung devices need a 'boot.img' file, just like the one generated
    # fastboot compatible devices. Example: s7562, n7100
    "heimdall-bootimg": {
        "depends": ["heimdall", "avbtool"],
        "actions": {
            "list_devices": [["heimdall", "detect"]],
            "flash_rootfs": [
                ["heimdall_wait_for_device.sh"],
                ["heimdall", "flash", "--$PARTITION_SYSTEM", "$IMAGE"]],
            "flash_kernel": [
                ["heimdall_wait_for_device.sh"],
                ["heimdall", "flash", "--$PARTITION_KERNEL", "$BOOT/boot.img-$FLAVOR"]],
            "flash_vbmeta": [
                ["avbtool", "make_vbmeta_image", "--flags", "2",
                    "--padding_size", "$FLASH_PAGESIZE",
                    "--output", "/vbmeta.img"],
                ["heimdall", "flash", "--$PARTITION_VBMETA", "/vbmeta.img"],
                ["rm", "-f", "/vbmeta.img"]]
        },
    },
    "adb": {
        "depends": ["android-tools"],
        "actions": {
            "list_devices": [["adb", "-P", "5038", "devices"]],
            "sideload": [["echo", "< wait for any device >"],
                         ["adb", "-P", "5038", "wait-for-usb-sideload"],
                         ["adb", "-P", "5038", "sideload",
                          "$RECOVERY_ZIP"]],
        }
    },
    "uuu": {
        "depends": ["uuu"],
        "actions": {
            "flash_rootfs": [
                # There's a bug(?) in uuu where it clobbers the path in the cmd
                # script if the script is not in pwd...
                ["cp", "$UUU_SCRIPT", "./flash_script.lst"],
                ["uuu", "flash_script.lst"],
            ],
        },
    }
}

#
# GIT
#
git_repos = {
    "aports_upstream": "https://gitlab.alpinelinux.org/alpine/aports.git",
    "pmaports": "https://gitlab.com/postmarketOS/pmaports.git",
}

# When a git repository is considered outdated (in seconds)
# (Measuring timestamp of FETCH_HEAD: https://stackoverflow.com/a/9229377)
git_repo_outdated = 3600 * 24 * 2

#
# APORTGEN
#
aportgen = {
    "cross": {
        "prefixes": ["binutils", "busybox-static", "gcc", "musl", "grub-efi"],
        "confirm_overwrite": False,
    },
    "device/testing": {
        "prefixes": ["device", "linux"],
        "confirm_overwrite": True,
    }
}

#
# NEWAPKBUILD
# Options passed through to the "newapkbuild" command from Alpine Linux. They
# are duplicated here, so we can use Python's argparse for argument parsing and
# help page display. The -f (force) flag is not defined here, as we use that in
# the Python code only and don't pass it through.
#
newapkbuild_arguments_strings = [
    ["-n", "pkgname", "set package name (only use with SRCURL)"],
    ["-d", "pkgdesc", "set package description"],
    ["-l", "license", "set package license identifier from"
                      " <https://spdx.org/licenses/>"],
    ["-u", "url", "set package URL"],
]
newapkbuild_arguments_switches_pkgtypes = [
    ["-a", "autotools", "create autotools package (use ./configure ...)"],
    ["-C", "cmake", "create CMake package (assume cmake/ is there)"],
    ["-m", "meson", "create meson package (assume meson.build is there)"],
    ["-p", "perl", "create perl package (assume Makefile.PL is there)"],
    ["-y", "python", "create python package (assume setup.py is there)"],
]
newapkbuild_arguments_switches_other = [
    ["-s", "sourceforge", "use sourceforge source URL"],
    ["-c", "copy_samples", "copy a sample init.d, conf.d and install script"],
]

#
# UPGRADE
#
# Patterns of package names to ignore for automatic pmaport upgrading ("pmbootstrap aportupgrade --all")
upgrade_ignore = ["device-*", "firmware-*", "linux-*", "postmarketos-*", "*-aarch64", "*-armhf", "*-armv7"]
