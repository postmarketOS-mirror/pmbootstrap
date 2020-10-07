# Copyright 2020 Pablo Castellano, Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import os
import re
import signal
import shlex
import shutil

import pmb.build
import pmb.chroot
import pmb.chroot.apk
import pmb.chroot.other
import pmb.chroot.initfs
import pmb.config
import pmb.helpers.run
import pmb.parse.arch


def system_image(args):
    """
    Returns path to rootfs for specified device. In case that it doesn't
    exist, raise and exception explaining how to generate it.
    """
    path = args.work + "/chroot_native/home/pmos/rootfs/" + args.device + ".img"
    if not os.path.exists(path):
        logging.debug("Could not find rootfs: " + path)
        raise RuntimeError("The rootfs has not been generated yet, please "
                           "run 'pmbootstrap install' first.")
    return path


def which_qemu(args, arch):
    """
    Finds the qemu executable or raises an exception otherwise
    """
    executable = "qemu-system-" + arch
    if shutil.which(executable):
        return executable
    else:
        raise RuntimeError("Could not find the '" + executable + "' executable"
                           " in your PATH. Please install it in order to"
                           " run qemu.")


def create_gdk_loader_cache(args):
    """
    Create a gdk loader cache that can be used for running GTK UIs outside of
    the chroot.
    """
    gdk_cache_dir = "/usr/lib/gdk-pixbuf-2.0/2.10.0/"
    custom_cache_path = gdk_cache_dir + "loaders-pmos-chroot.cache"
    rootfs_native = args.work + "/chroot_native"
    if os.path.isfile(rootfs_native + custom_cache_path):
        return rootfs_native + custom_cache_path

    cache_path = gdk_cache_dir + "loaders.cache"
    if not os.path.isfile(rootfs_native + cache_path):
        raise RuntimeError("gdk pixbuf cache file not found: " + cache_path)

    pmb.chroot.root(args, ["cp", cache_path, custom_cache_path])
    cmd = ["sed", "-i", "-e",
           "s@\"" + gdk_cache_dir + "@\"" + rootfs_native + gdk_cache_dir + "@",
           custom_cache_path]
    pmb.chroot.root(args, cmd)
    return rootfs_native + custom_cache_path


def command_qemu(args, arch, img_path):
    """
    Generate the full qemu command with arguments to run postmarketOS
    """
    cmdline = args.deviceinfo["kernel_cmdline"]
    if args.cmdline:
        cmdline = args.cmdline

    if "video=" not in cmdline:
        cmdline += " video=" + args.qemu_video

    logging.debug("Kernel cmdline: " + cmdline)

    port_ssh = str(args.port)

    suffix = "rootfs_" + args.device
    rootfs = args.work + "/chroot_" + suffix
    flavor = pmb.chroot.other.kernel_flavors_installed(args, suffix)[0]

    if args.host_qemu:
        qemu_bin = which_qemu(args, arch)
        env = {}
        command = [qemu_bin]
    else:
        rootfs_native = args.work + "/chroot_native"
        env = {"QEMU_MODULE_DIR": rootfs_native + "/usr/lib/qemu",
               "GBM_DRIVERS_PATH": rootfs_native + "/usr/lib/xorg/modules/dri",
               "LIBGL_DRIVERS_PATH": rootfs_native + "/usr/lib/xorg/modules/dri"}

        if "gtk" in args.qemu_display:
            gdk_cache = create_gdk_loader_cache(args)
            env.update({"GTK_THEME": "Default",
                        "GDK_PIXBUF_MODULE_FILE": gdk_cache,
                        "XDG_DATA_DIRS": rootfs_native + "/usr/local/share:" +
                        rootfs_native + "/usr/share"})

        command = [rootfs_native + "/lib/ld-musl-" +
                   args.arch_native + ".so.1"]
        command += ["--library-path=" + rootfs_native + "/lib:" +
                    rootfs_native + "/usr/lib:" +
                    rootfs_native + "/usr/lib/pulseaudio"]
        command += [rootfs_native + "/usr/bin/qemu-system-" + arch]
        command += ["-L", rootfs_native + "/usr/share/qemu/"]

    command += ["-nodefaults"]
    command += ["-kernel", rootfs + "/boot/vmlinuz-" + flavor]
    command += ["-initrd", rootfs + "/boot/initramfs-" + flavor]
    command += ["-append", shlex.quote(cmdline)]

    command += ["-smp", str(os.cpu_count())]
    command += ["-m", str(args.memory)]

    command += ["-serial", "mon:stdio"]
    command += ["-drive", "file=" + img_path + ",format=raw,if=virtio"]
    if args.qemu_tablet:
        command += ["-device", "virtio-tablet-pci"]
    else:
        command += ["-device", "virtio-mouse-pci"]
    command += ["-device", "virtio-keyboard-pci"]
    command += ["-nic",
                "user,model=virtio-net-pci,"
                "hostfwd=tcp::" + port_ssh + "-:22,"
                ]

    if arch == "x86_64":
        command += ["-vga", "virtio"]
    elif arch == "aarch64":
        command += ["-M", "virt"]
        command += ["-cpu", "cortex-a57"]
        command += ["-device", "virtio-gpu-pci"]
    else:
        raise RuntimeError("Architecture {} not supported by this command yet.".format(arch))

    # Kernel Virtual Machine (KVM) support
    native = args.arch_native == args.deviceinfo["arch"]
    if args.qemu_kvm and native and os.path.exists("/dev/kvm"):
        command += ["-enable-kvm"]
        command += ["-cpu", "host"]
    else:
        logging.info("WARNING: QEMU is not using KVM and will run slower!")

    if args.qemu_cpu:
        command += ["-cpu", args.qemu_cpu]

    display = args.qemu_display
    if display != "none":
        display += ",gl=" + ("on" if args.qemu_gl else "off")

    command += ["-display", display]
    command += ["-show-cursor"]

    # Audio support
    if args.qemu_audio:
        command += ["-audiodev", args.qemu_audio + ",id=audio"]
        command += ["-soundhw", "hda"]

    return (command, env)


def resize_image(args, img_size_new, img_path):
    """
    Truncates the rootfs to a specific size. The value must be larger than the
    current image size, and it must be specified in MiB or GiB units (powers of 1024).

    :param img_size_new: new image size in M or G
    :param img_path: the path to the rootfs
    """
    # Current image size in bytes
    img_size = os.path.getsize(img_path)

    # Make sure we have at least 1 integer followed by either M or G
    pattern = re.compile("^[0-9]+[M|G]$")
    if not pattern.match(img_size_new):
        raise RuntimeError("You must specify the rootfs size in [M]iB or [G]iB, e.g. 2048M or 2G")

    # Remove M or G and convert to bytes
    img_size_new_bytes = int(img_size_new[:-1]) * 1024 * 1024

    # Convert further for G
    if (img_size_new[-1] == "G"):
        img_size_new_bytes = img_size_new_bytes * 1024

    if (img_size_new_bytes >= img_size):
        logging.info("Setting the rootfs size to " + img_size_new)
        pmb.helpers.run.root(args, ["truncate", "-s", img_size_new, img_path])
    else:
        # Convert to human-readable format
        # NOTE: We convert to M here, and not G, so that we don't have to display
        # a size like 1.25G, since decimal places are not allowed by truncate.
        # We don't want users thinking they can use decimal numbers, and so in
        # this example, they would need to use a size greater then 1280M instead.
        img_size_str = str(round(img_size / 1024 / 1024)) + "M"

        raise RuntimeError("The rootfs size must be " + img_size_str + " or greater")


def sigterm_handler(number, frame):
    raise RuntimeError("pmbootstrap was terminated by another process,"
                       " and killed the QEMU VM it was running.")


def install_depends(args, arch):
    """
    Install any necessary qemu dependencies in native chroot
    """
    depends = ["qemu", "qemu-system-" + arch, "qemu-ui-sdl", "qemu-ui-gtk",
               "mesa-gl", "mesa-egl", "mesa-dri-classic", "mesa-dri-gallium",
               "qemu-audio-alsa", "qemu-audio-pa", "qemu-audio-sdl"]
    pmb.chroot.apk.install(args, depends)


def run(args):
    """
    Run a postmarketOS image in qemu
    """
    if not args.device.startswith("qemu-"):
        raise RuntimeError("'pmbootstrap qemu' can be only used with one of "
                           "the QEMU device packages. Run 'pmbootstrap init' "
                           "and select the 'qemu' vendor.")
    arch = pmb.parse.arch.alpine_to_qemu(args.deviceinfo["arch"])

    img_path = system_image(args)
    if not args.host_qemu:
        install_depends(args, arch)
    logging.info("Running postmarketOS in QEMU VM (" + arch + ")")

    qemu, env = command_qemu(args, arch, img_path)

    # Workaround: QEMU runs as local user and needs write permissions in the
    # rootfs, which is owned by root
    if not os.access(img_path, os.W_OK):
        pmb.helpers.run.root(args, ["chmod", "666", img_path])

    # Resize the rootfs (or show hint)
    if args.image_size:
        resize_image(args, args.image_size, img_path)
    else:
        logging.info("NOTE: Run 'pmbootstrap qemu --image-size 2G' to set"
                     " the rootfs size when you run out of space!")

    # SSH/serial hints
    logging.info("Connect to the VM:")
    logging.info("* (ssh) ssh -p {port} {user}@localhost".format(**vars(args)))
    logging.info("* (serial) in this console (stdout/stdin)")

    # Run QEMU and kill it together with pmbootstrap
    process = None
    try:
        signal.signal(signal.SIGTERM, sigterm_handler)
        process = pmb.helpers.run.user(args, qemu, output="tui", env=env)
    except KeyboardInterrupt:
        # Don't show a trace when pressing ^C
        pass
    finally:
        if process:
            process.terminate()
