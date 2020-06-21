# Copyright 2020 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import pmb.aportgen.core
import pmb.build
import pmb.chroot.apk
import pmb.chroot.apk_static
import pmb.helpers.run
import pmb.parse.apkindex


def generate(args, pkgname):
    arch = pkgname.split("-")[2]

    # Parse version from APKINDEX
    package_data = pmb.parse.apkindex.package(args, "busybox")
    version = package_data["version"]
    pkgver = version.split("-r")[0]
    pkgrel = version.split("-r")[1]

    # Prepare aportgen tempdir inside and outside of chroot
    tempdir = "/tmp/aportgen"
    pmb.chroot.root(args, ["rm", "-rf", tempdir])
    pmb.helpers.run.user(args, ["mkdir", "-p", f"{args.work}/aportgen",
                                f"{args.work}/chroot_native/{tempdir}"])

    # Write the APKBUILD
    channel_cfg = pmb.config.pmaports.read_config_channel(args)
    mirrordir = channel_cfg["mirrordir_alpine"]
    apkbuild_path = f"{args.work}/chroot_native/{tempdir}/APKBUILD"
    with open(apkbuild_path, "w", encoding="utf-8") as handle:
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
                busybox-static-$pkgver-r$pkgrel-$_arch-{mirrordir}.apk::$_mirror/{mirrordir}/main/$_arch/busybox-static-$pkgver-r$pkgrel.apk
            "

            package() {{
                mkdir -p "$pkgdir/usr/$_target"
                cd "$pkgdir/usr/$_target"
                tar -xf $srcdir/busybox-static-$pkgver-r$pkgrel-$_arch-{mirrordir}.apk
                rm .PKGINFO .SIGN.*
            }}
        """
        for line in apkbuild.split("\n"):
            handle.write(line[12:].replace(" " * 4, "\t") + "\n")

    # Generate checksums
    pmb.build.init(args)
    pmb.chroot.root(args, ["chown", "-R", "pmos:pmos", tempdir])
    pmb.chroot.user(args, ["abuild", "checksum"], working_dir=tempdir)
    pmb.helpers.run.user(args, ["cp", apkbuild_path, f"{args.work}/aportgen"])
