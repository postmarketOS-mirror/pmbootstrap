# Copyright 2020 Nick Reitemeyer
# SPDX-License-Identifier: GPL-3.0-or-later
import glob
import os
import pmb.helpers.run
import pmb.aportgen.core
import pmb.parse.apkindex
import pmb.chroot.apk
import pmb.chroot.apk_static


def generate(args, pkgname):
    arch = "x86"
    if pkgname != "grub-efi-x86":
        raise RuntimeError("only grub-efi-x86 is available")
    package_data = pmb.parse.apkindex.package(args, "grub")
    version = package_data["version"]
    pkgver = version.split("-r")[0]
    pkgrel = version.split("-r")[1]

    pmb.chroot.apk.install(args, ["grub-efi"], "buildroot_x86")
    pattern = (args.work + "/cache_apk_" + arch + "/grub-efi-" +
               version + ".*.apk")
    glob_result = glob.glob(pattern)
    if not len(glob_result):
        raise RuntimeError("Could not find aport " + pattern + "!"
                           " Update your aports_upstream git repo"
                           " to the latest version, delete your http cache"
                           " (pmbootstrap zap -hc) and try again.")
    path = glob_result[0]
    path_target = (args.work + "/cache_distfiles/grub-efi-" +
                   version + "-" + arch + ".apk")
    if not os.path.exists(path_target):
        pmb.helpers.run.root(args, ["cp", path, path_target])

    # Hash the distfile
    hashes = pmb.chroot.user(args, ["sha512sum",
                                    "grub-efi-" + version + "-" + arch + ".apk"],
                             "buildroot_" + arch, "/var/cache/distfiles",
                             output_return=True)

    # Write the APKBUILD
    channel_cfg = pmb.config.pmaports.read_config_channel(args)
    mirrordir = channel_cfg["mirrordir_alpine"]
    pmb.helpers.run.user(args, ["mkdir", "-p", args.work + "/aportgen"])
    with open(args.work + "/aportgen/APKBUILD", "w", encoding="utf-8") as handle:
        apkbuild = f"""\
            # Automatically generated aport, do not edit!
            # Generator: pmbootstrap aportgen {pkgname}

            pkgname={pkgname}
            pkgver={pkgver}
            pkgrel={pkgrel}

            _arch="{arch}"
            _mirror="{args.mirror_alpine}"

            pkgdesc="GRUB $_arch EFI files for every architecture"
            url="https://www.gnu.org/software/grub/"
            license="GPL-3.0-or-later"
            arch="all"
            source="grub-efi-$pkgver-r$pkgrel-$_arch.apk::$_mirror/{mirrordir}/main/$_arch/grub-efi-$pkgver-r$pkgrel.apk"

            package() {{
                mkdir -p "$pkgdir"
                cd "$pkgdir"
                tar -xf "$srcdir/grub-efi-$pkgver-r$pkgrel-$_arch.apk"
                rm .PKGINFO .SIGN.*
            }}
        """
        for line in apkbuild.split("\n"):
            handle.write(line[12:].replace(" " * 4, "\t") + "\n")

        handle.write("sha512sums=\"" + hashes.rstrip() + "\"\n")
