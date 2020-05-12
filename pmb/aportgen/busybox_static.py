# Copyright 2020 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import glob
import os
import pmb.helpers.run
import pmb.aportgen.core
import pmb.parse.apkindex
import pmb.chroot.apk
import pmb.chroot.apk_static


def generate(args, pkgname):
    # Install busybox-static in chroot to get verified apks
    arch = pkgname.split("-")[2]
    pmb.chroot.apk.install(args, ["busybox-static"], "buildroot_" + arch)

    # Parse version from APKINDEX
    package_data = pmb.parse.apkindex.package(args, "busybox")
    version = package_data["version"]
    pkgver = version.split("-r")[0]
    pkgrel = version.split("-r")[1]

    # Copy the apk file to the distfiles cache
    pattern = (args.work + "/cache_apk_" + arch + "/busybox-static-" +
               version + ".*.apk")
    glob_result = glob.glob(pattern)
    if not len(glob_result):
        raise RuntimeError("Could not find aport " + pattern + "!"
                           " Update your aports_upstream git repo"
                           " to the latest version, delete your http cache"
                           " (pmbootstrap zap -hc) and try again.")
    path = glob_result[0]
    path_target = (args.work + "/cache_distfiles/busybox-static-" +
                   version + "-" + arch + ".apk")
    if not os.path.exists(path_target):
        pmb.helpers.run.root(args, ["cp", path, path_target])

    # Hash the distfile
    hashes = pmb.chroot.user(args, ["sha512sum",
                                    "busybox-static-" + version + "-" + arch + ".apk"],
                             "buildroot_" + arch, "/var/cache/distfiles",
                             output_return=True)

    # Write the APKBUILD
    pmb.helpers.run.user(args, ["mkdir", "-p", args.work + "/aportgen"])
    with open(args.work + "/aportgen/APKBUILD", "w", encoding="utf-8") as handle:
        apkbuild = f"""\
            # Automatically generated aport, do not edit!
            # Generator: pmbootstrap aportgen {pkgname}

            # Stub for apkbuild-lint
            if [ -z "$(type -t arch_to_hostspec)" ]; then
                arch_to_hostspec() {{ :; }}
            fi

            pkgname={pkgname}
            pkgver={pkgver}
            pkgrel={pkgrel}

            _arch="{arch}"
            _mirror="{args.mirror_alpine}"

            url="http://busybox.net"
            license="GPL2"
            arch="all"
            options="!check !strip"
            pkgdesc="Statically linked Busybox for $_arch"
            _target="$(arch_to_hostspec $_arch)"

            source="
                busybox-static-$pkgver-r$pkgrel-$_arch.apk::$_mirror/edge/main/$_arch/busybox-static-$pkgver-r$pkgrel.apk
            "

            package() {{
                mkdir -p "$pkgdir/usr/$_target"
                cd "$pkgdir/usr/$_target"
                tar -xf $srcdir/busybox-static-$pkgver-r$pkgrel-$_arch.apk
                rm .PKGINFO .SIGN.*
            }}
        """
        for line in apkbuild.split("\n"):
            handle.write(line[12:].replace(" " * 4, "\t") + "\n")

        # Hashes
        handle.write("sha512sums=\"" + hashes.rstrip() + "\"\n")
