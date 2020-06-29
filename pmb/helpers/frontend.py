# Copyright 2020 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import glob
import json
import logging
import os
import sys

import pmb.aportgen
import pmb.build
import pmb.build.autodetect
import pmb.chroot
import pmb.chroot.initfs
import pmb.chroot.other
import pmb.config
import pmb.export
import pmb.flasher
import pmb.helpers.git
import pmb.helpers.lint
import pmb.helpers.logging
import pmb.helpers.pkgrel_bump
import pmb.helpers.pmaports
import pmb.helpers.repo
import pmb.helpers.repo_missing
import pmb.helpers.run
import pmb.helpers.aportupgrade
import pmb.helpers.status
import pmb.install
import pmb.install.blockdevice
import pmb.parse
import pmb.qemu


def _parse_flavor(args, autoinstall=True):
    """
    Verify the flavor argument if specified, or return a default value.
    :param autoinstall: make sure that at least one kernel flavor is installed
    """
    # Install at least one kernel and get installed flavors
    suffix = "rootfs_" + args.device
    flavors = pmb.chroot.other.kernel_flavors_installed(args, suffix, autoinstall)

    # Parse and verify the flavor argument
    flavor = args.flavor
    if flavor:
        if flavor not in flavors:
            raise RuntimeError("No kernel installed with flavor " + flavor + "!" +
                               " Run 'pmbootstrap flasher list_flavors' to get a list.")
        return flavor
    if not len(flavors):
        raise RuntimeError(
            "No kernel flavors installed in chroot " + suffix + "! Please let"
            " your device package depend on a package starting with 'linux-'.")
    return flavors[0]


def _parse_suffix(args):
    if "rootfs" in args and args.rootfs:
        return "rootfs_" + args.device
    elif args.buildroot:
        if args.buildroot == "device":
            return "buildroot_" + args.deviceinfo["arch"]
        else:
            return "buildroot_" + args.buildroot
    elif args.suffix:
        return args.suffix
    else:
        return "native"


def aportgen(args):
    for package in args.packages:
        logging.info("Generate aport: " + package)
        pmb.aportgen.generate(args, package)


def build(args):
    # Strict mode: zap everything
    if args.strict:
        pmb.chroot.zap(args, False)

    if args.envkernel:
        pmb.build.envkernel.package_kernel(args)
        return

    # Set src and force
    src = os.path.realpath(os.path.expanduser(args.src[0])) if args.src else None
    force = True if src else args.force
    if src and not os.path.exists(src):
        raise RuntimeError("Invalid path specified for --src: " + src)

    # Build all packages
    for package in args.packages:
        arch_package = args.arch or pmb.build.autodetect.arch(args, package)
        if not pmb.build.package(args, package, arch_package, force,
                                 args.strict, src=src):
            logging.info("NOTE: Package '" + package + "' is up to date. Use"
                         " 'pmbootstrap build " + package + " --force'"
                         " if needed.")


def build_init(args):
    suffix = _parse_suffix(args)
    pmb.build.init(args, suffix)


def checksum(args):
    for package in args.packages:
        if args.verify:
            pmb.build.checksum.verify(args, package)
        else:
            pmb.build.checksum.update(args, package)


def chroot(args):
    # Suffix
    suffix = _parse_suffix(args)
    if (args.user and suffix != "native" and
            not suffix.startswith("buildroot_")):
        raise RuntimeError("--user is only supported for native or"
                           " buildroot_* chroots.")
    if args.xauth and suffix != "native":
        raise RuntimeError("--xauth is only supported for native chroot.")

    # apk: check minimum version, install packages
    pmb.chroot.apk.check_min_version(args, suffix)
    if args.add:
        pmb.chroot.apk.install(args, args.add.split(","), suffix)

    # Xauthority
    env = {}
    if args.xauth:
        pmb.chroot.other.copy_xauthority(args)
        env["DISPLAY"] = os.environ.get("DISPLAY")
        env["XAUTHORITY"] = "/home/pmos/.Xauthority"

    # Install blockdevice
    if args.install_blockdev:
        size_boot = 128  # 128 MiB
        size_root = 4096  # 4 GiB
        size_reserve = 2048  # 2 GiB
        pmb.install.blockdevice.create_and_mount_image(args, size_boot,
                                                       size_root, size_reserve)

    # Run the command as user/root
    if args.user:
        logging.info("(" + suffix + ") % su pmos -c '" +
                     " ".join(args.command) + "'")
        pmb.chroot.user(args, args.command, suffix, output=args.output,
                        env=env)
    else:
        logging.info("(" + suffix + ") % " + " ".join(args.command))
        pmb.chroot.root(args, args.command, suffix, output=args.output,
                        env=env)


def config(args):
    keys = pmb.config.config_keys
    if args.name and args.name not in keys:
        logging.info("NOTE: Valid config keys: " + ", ".join(keys))
        raise RuntimeError("Invalid config key: " + args.name)

    cfg = pmb.config.load(args)
    if args.reset:
        if args.name is None:
            raise RuntimeError("config --reset requires a name to be given.")
        value = pmb.config.defaults[args.name]
        cfg["pmbootstrap"][args.name] = value
        logging.info("Config changed to default: " + args.name + "='" + value + "'")
        pmb.config.save(args, cfg)
    elif args.value is not None:
        cfg["pmbootstrap"][args.name] = args.value
        logging.info("Config changed: " + args.name + "='" + args.value + "'")
        pmb.config.save(args, cfg)
    elif args.name:
        value = cfg["pmbootstrap"].get(args.name, "")
        print(value)
    else:
        cfg.write(sys.stdout)

    # Don't write the "Done" message
    pmb.helpers.logging.disable()


def repo_missing(args):
    missing = pmb.helpers.repo_missing.generate(args, args.arch, args.overview,
                                                args.package, args.built)
    print(json.dumps(missing, indent=4))


def index(args):
    pmb.build.index_repo(args)


def initfs(args):
    pmb.chroot.initfs.frontend(args)


def install(args):
    if args.no_fde:
        logging.warning("WARNING: --no-fde is deprecated, as it is now the default.")
    if args.rsync and args.full_disk_encryption:
        raise ValueError("Installation using rsync is not compatible with full"
                         " disk encryption.")
    if args.rsync and not args.sdcard:
        raise ValueError("Installation using rsync only works on sdcard.")

    # On-device installer checks
    # Note that this can't be in the mutually exclusive group that has most of
    # the conflicting options, because then it would not work with --sdcard.
    if args.on_device_installer:
        if args.full_disk_encryption:
            raise ValueError("--on-device-installer cannot be combined with"
                             " --fde. The user can choose to encrypt their"
                             " installation later in the on-device installer.")
        if args.android_recovery_zip:
            raise ValueError("--on-device-installer cannot be combined with"
                             " --android-recovery-zip (patches welcome)")
        if args.no_image:
            raise ValueError("--on-device-installer cannot be combined with"
                             " --no-image")
        if args.rsync:
            raise ValueError("--on-device-installer cannot be combined with"
                             " --rsync")

    # On-device installer overrides
    if args.on_device_installer:
        # To make code for the on-device installer not needlessly complex, just
        # hardcode "user" as username here. (The on-device installer will set
        # a password for the user, disable SSH password authentication,
        # optionally add a new user for SSH that must not have the same
        # username etc.)
        if args.user != "user":
            logging.warning(f"WARNING: custom username '{args.user}' will be"
                            " replaced with 'user' for the on-device"
                            " installer.")
            args.user = "user"

    if not args.sdcard and args.split is None:
        # Default to split if the flash method requires it
        flasher = pmb.config.flashers.get(args.deviceinfo["flash_method"], {})
        if flasher.get("split", False):
            args.split = True

    # Don't install locally compiled packages and package signing keys
    if not args.install_local_pkgs:
        # Implies that we don't build outdated packages (overriding the answer
        # in 'pmbootstrap init')
        args.install_build_pkgs = False

        # Safest way to avoid installing local packages is having none
        if glob.glob(f"{args.work}/packages/*"):
            raise ValueError("--no-local-pkgs specified, but locally built"
                             " packages found. Consider 'pmbootstrap zap -p'"
                             " to delete them.")

    pmb.install.install(args)


def flasher(args):
    pmb.flasher.frontend(args)


def export(args):
    pmb.export.frontend(args)


def update(args):
    existing_only = not args.non_existing
    if not pmb.helpers.repo.update(args, args.arch, True, existing_only):
        logging.info("No APKINDEX files exist, so none have been updated."
                     " The pmbootstrap command downloads the APKINDEX files on"
                     " demand.")
        logging.info("If you want to force downloading the APKINDEX files for"
                     " all architectures (not recommended), use:"
                     " pmbootstrap update --non-existing")


def newapkbuild(args):
    # Check for SRCURL usage
    is_url = False
    for prefix in ["http://", "https://", "ftp://"]:
        if args.pkgname_pkgver_srcurl.startswith(prefix):
            is_url = True
            break

    # Sanity check: -n is only allowed with SRCURL
    if args.pkgname and not is_url:
        raise RuntimeError("You can only specify a pkgname (-n) when using"
                           " SRCURL as last parameter.")

    # Passthrough: Strings (e.g. -d "my description")
    pass_through = []
    for entry in pmb.config.newapkbuild_arguments_strings:
        value = getattr(args, entry[1])
        if value:
            pass_through += [entry[0], value]

    # Passthrough: Switches (e.g. -C for CMake)
    for entry in (pmb.config.newapkbuild_arguments_switches_pkgtypes +
                  pmb.config.newapkbuild_arguments_switches_other):
        if getattr(args, entry[1]) is True:
            pass_through.append(entry[0])

    # Passthrough: PKGNAME[-PKGVER] | SRCURL
    pass_through.append(args.pkgname_pkgver_srcurl)
    pmb.build.newapkbuild(args, args.folder, pass_through, args.force)


def kconfig(args):
    if args.action_kconfig == "check":
        # Handle passing a file directly
        if args.file:
            if pmb.parse.kconfig.check_file(args, args.package,
                                            force_anbox_check=args.anbox,
                                            details=True):
                logging.info("kconfig check succeeded!")
                return
            raise RuntimeError("kconfig check failed!")

        # Default to all kernel packages
        packages = []
        if args.package:
            packages = [args.package]
        else:
            for aport in pmb.helpers.pmaports.get_list(args):
                if aport.startswith("linux-"):
                    packages.append(aport.split("linux-")[1])

        # Iterate over all kernels
        error = False
        skipped = 0
        packages.sort()
        for package in packages:
            if not args.force:
                pkgname = package if package.startswith("linux-") else "linux-" + package
                aport = pmb.helpers.pmaports.find(args, pkgname)
                apkbuild = pmb.parse.apkbuild(args, aport + "/APKBUILD")
                if "!pmb:kconfigcheck" in apkbuild["options"]:
                    skipped += 1
                    continue
            if not pmb.parse.kconfig.check(args, package,
                                           force_anbox_check=args.anbox,
                                           details=True):
                error = True

        # At least one failure
        if error:
            raise RuntimeError("kconfig check failed!")
        else:
            if skipped:
                logging.info("NOTE: " + str(skipped) + " kernel(s) was skipped"
                             " (consider 'pmbootstrap kconfig check -f')")
            logging.info("kconfig check succeeded!")
    elif args.action_kconfig == "edit":
        pmb.build.menuconfig(args, args.package)


def apkbuild_parse(args):
    # Default to all packages
    packages = args.packages
    if not packages:
        packages = pmb.helpers.pmaports.get_list(args)

    # Iterate over all packages
    for package in packages:
        print(package + ":")
        aport = pmb.helpers.pmaports.find(args, package)
        path = aport + "/APKBUILD"
        print(json.dumps(pmb.parse.apkbuild(args, path), indent=4,
                         sort_keys=True))


def apkindex_parse(args):
    result = pmb.parse.apkindex.parse(args, args.apkindex_path)
    if args.package:
        if args.package not in result:
            raise RuntimeError("Package not found in the APKINDEX: " +
                               args.package)
        result = result[args.package]
    print(json.dumps(result, indent=4))


def pkgrel_bump(args):
    would_bump = True
    if args.auto:
        would_bump = pmb.helpers.pkgrel_bump.auto(args, args.dry)
    else:
        # Each package must exist
        for package in args.packages:
            pmb.helpers.pmaports.find(args, package)

        # Increase pkgrel
        for package in args.packages:
            pmb.helpers.pkgrel_bump.package(args, package, dry=args.dry)

    if args.dry and would_bump:
        logging.info("Pkgrels of package(s) would have been bumped!")
        sys.exit(1)


def aportupgrade(args):
    if args.all or args.all_stable or args.all_git:
        pmb.helpers.aportupgrade.upgrade_all(args)
    else:
        # Each package must exist
        for package in args.packages:
            pmb.helpers.pmaports.find(args, package)

        # Check each package for a new version
        for package in args.packages:
            pmb.helpers.aportupgrade.upgrade(args, package)


def qemu(args):
    pmb.qemu.run(args)


def shutdown(args):
    pmb.chroot.shutdown(args)


def stats(args):
    # Chroot suffix
    suffix = "native"
    if args.arch != args.arch_native:
        suffix = "buildroot_" + args.arch

    # Install ccache and display stats
    pmb.chroot.apk.install(args, ["ccache"], suffix)
    logging.info("(" + suffix + ") % ccache -s")
    pmb.chroot.user(args, ["ccache", "-s"], suffix, output="stdout")


def work_migrate(args):
    # do nothing (pmb/__init__.py already did the migration)
    pmb.helpers.logging.disable()


def log(args):
    if args.clear_log:
        pmb.helpers.run.user(args, ["truncate", "-s", "0", args.log])
    pmb.helpers.run.user(args, ["tail", "-f", args.log, "-n", args.lines],
                         output="tui")


def log_distccd(args):
    logpath = "/home/pmos/distccd.log"
    if args.clear_log:
        pmb.chroot.user(args, ["truncate", "-s", "0", logpath])
    pmb.chroot.user(args, ["tail", "-f", logpath, "-n", args.lines],
                    output="tui")


def zap(args):
    pmb.chroot.zap(args, dry=args.dry, http=args.http,
                   distfiles=args.distfiles, pkgs_local=args.pkgs_local,
                   pkgs_local_mismatch=args.pkgs_local_mismatch,
                   pkgs_online_mismatch=args.pkgs_online_mismatch,
                   rust=args.rust)

    # Don't write the "Done" message
    pmb.helpers.logging.disable()


def bootimg_analyze(args):
    bootimg = pmb.parse.bootimg(args, args.path)
    tmp_output = "Put these variables in the deviceinfo file of your device:\n"
    for line in pmb.aportgen.device.generate_deviceinfo_fastboot_content(args, bootimg).split("\n"):
        tmp_output += "\n" + line.lstrip()
    logging.info(tmp_output)


def pull(args):
    failed = []
    for repo in pmb.config.git_repos.keys():
        if pmb.helpers.git.pull(args, repo) < 0:
            failed.append(repo)

    if not failed:
        return True

    logging.info("---")
    logging.info("WARNING: failed to update: " + ", ".join(failed))
    logging.info("")
    logging.info("'pmbootstrap pull' will only update the repositories, if:")
    logging.info("* they are on an officially supported branch (e.g. master)")
    logging.info("* the history is not conflicting (fast-forward is possible)")
    logging.info("* the git workdirs are clean")
    logging.info("You have changed mentioned repositories, so they don't meet")
    logging.info("these conditions anymore.")
    logging.info("")
    logging.info("Fix and try again:")
    for name_repo in failed:
        logging.info("* " + pmb.helpers.git.get_path(args, name_repo))
    logging.info("---")
    return False


def lint(args):
    packages = args.packages
    if not packages:
        packages = pmb.helpers.pmaports.get_list(args)

    for package in packages:
        pmb.helpers.lint.check(args, package)


def status(args):
    if not pmb.helpers.status.print_status(args, args.details):
        sys.exit(1)
