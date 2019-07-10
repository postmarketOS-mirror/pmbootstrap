"""
Copyright 2019 Oliver Smith

This file is part of pmbootstrap.

pmbootstrap is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

pmbootstrap is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with pmbootstrap.  If not, see <http://www.gnu.org/licenses/>.
"""
import glob
import logging
import os
import re
import pmb.chroot
import pmb.config
import pmb.helpers.pmaports
import pmb.helpers.run


def folder_size(args, path):
    """
    Run `du` to calculate the size of a folder (this is less code and
    faster than doing the same task in pure Python). This result is only
    approximatelly right, but good enough for pmbootstrap's use case (#760).

    :returns: folder size in bytes
    """
    output = pmb.helpers.run.root(args, ["du", "--summarize",
                                         "--block-size=1",
                                         path], output_return=True)

    # Only look at last line to filter out sudo garbage (#1766)
    last_line = output.split("\n")[-2]

    ret = int(last_line.split("\t")[0])
    return ret


def check_grsec(args):
    """
    Check if the current kernel is based on the grsec patchset, and if
    the chroot_deny_chmod option is enabled. Raise an exception in that
    case, with a link to the issue. Otherwise, do nothing.
    """
    path = "/proc/sys/kernel/grsecurity/chroot_deny_chmod"
    if not os.path.exists(path):
        return

    raise RuntimeError("You're running a kernel based on the grsec"
                       " patchset. This is not supported.")


def check_binfmt_misc(args):
    """
    Check if the 'binfmt_misc' module is loaded by checking, if
    /proc/sys/fs/binfmt_misc/ exists. If it exists, then do nothing.
    Otherwise, raise an exception pointing to user to the Wiki.
    """
    path = "/proc/sys/fs/binfmt_misc/status"
    if os.path.exists(path):
        return

    link = "https://postmarketos.org/binfmt_misc"
    raise RuntimeError("It appears that your system has not loaded the"
                       " module 'binfmt_misc'. This is required to run"
                       " foreign architecture programs with QEMU (eg."
                       " armhf on x86_64):\n See: <" + link + ">")


def delete_apk(args, pkgname, version):
    """
    Remove a cached binary package for all arches.

    :param pkgname: package name (e.g. "binutils-armhf")
    :param version: $pkgver-r$pkgrel (e.g. "1.0.0-r2")
    """
    pattern = args.work + "/cache_apk_*/" + pkgname + "-" + version + ".*.apk"
    matches = glob.glob(pattern)
    logging.info("(native) Removing package: " + pkgname + "-" + version)
    if not matches:
        logging.info("(native) (Package not found, nothing to do.)")
        return
    for match in matches:
        logging.info("(native) % rm " + match)
        pmb.helpers.run.root(args, ["rm", match])


def migrate_success(args, version):
    logging.info("Migration to version " + str(version) + " done")
    with open(args.work + "/version", "w") as handle:
        handle.write(str(version) + "\n")


def migrate_work_folder(args):
    # Read current version
    current = 0
    path = args.work + "/version"
    if os.path.exists(path):
        with open(path, "r") as f:
            current = int(f.read().rstrip())

    # Compare version, print warning or do nothing
    required = pmb.config.work_version
    if current == required:
        return
    logging.info("WARNING: Your work folder version needs to be migrated"
                 " (from version " + str(current) + " to " + str(required) +
                 ")!")

    # 0 => 1
    if current == 0:
        # Ask for confirmation
        logging.info("Changelog:")
        logging.info("* Building chroots have a different username (#709)")
        logging.info("Migration will do the following:")
        logging.info("* Zap your chroots")
        logging.info("* Adjust '" + args.work + "/config_abuild/abuild.conf'")
        if not pmb.helpers.cli.confirm(args):
            raise RuntimeError("Aborted.")

        # Zap and update abuild.conf
        pmb.chroot.zap(args, False)
        conf = args.work + "/config_abuild/abuild.conf"
        if os.path.exists(conf):
            pmb.helpers.run.root(args, ["sed", "-i",
                                        "s./home/user/./home/pmos/.g", conf])
        # Update version file
        migrate_success(args, 1)
        current = 1

    # 1 => 2
    if current == 1:
        # Ask for confirmation
        logging.info("Changelog:")
        logging.info("* Fix: cache_distfiles was writable for everyone")
        logging.info("Migration will do the following:")
        logging.info("* Fix permissions of '" + args.work +
                     "/cache_distfiles'")
        if not pmb.helpers.cli.confirm(args):
            raise RuntimeError("Aborted.")

        # Fix permissions
        dir = "/var/cache/distfiles"
        for cmd in [["chown", "-R", "root:abuild", dir],
                    ["chmod", "-R", "664", dir],
                    ["chmod", "a+X", dir]]:
            pmb.chroot.root(args, cmd)
        migrate_success(args, 2)
        current = 2

    if current == 2:
        # Ask for confirmation
        logging.info("Changelog:")
        logging.info("* Device chroots have a different user UID (#1576)")
        logging.info("Migration will do the following:")
        logging.info("* Zap your chroots")
        if not pmb.helpers.cli.confirm(args):
            raise RuntimeError("Aborted.")

        # Zap chroots
        pmb.chroot.zap(args, False)

        # Update version file
        migrate_success(args, 3)
        current = 3

    if current == 3:
        logging.info("Changelog:")
        logging.info("* armhf triplet was changed in abuild (pmaports#295)")
        logging.info("Migration will do the following:")
        logging.info("* Zap your chroots")
        logging.info("* Delete invalid armhf packages from cache")
        logging.info("Note:")
        logging.info("* If you are getting strange compiling errors when")
        logging.info("  compiling to armhf (and other arches work fine!),")
        logging.info("  then the invalid packages are probably still")
        logging.info("  cached in your network. In that case, ask in the chat")
        logging.info("  for advice: https://postmarketos.org/chat")
        if not pmb.helpers.cli.confirm(args):
            raise RuntimeError("Aborted.")

        pmb.chroot.zap(args, False)
        delete_apk(args, "binutils-armhf", "2.31.1-r2")
        delete_apk(args, "busybox-static-armhf", "1.30.1-r2")
        delete_apk(args, "gcc-armhf", "8.3.0-r0")
        delete_apk(args, "gcc4-armhf", "9999-r1")
        delete_apk(args, "gcc6-armhf", "9999-r6")
        delete_apk(args, "musl-armhf", "1.1.22-r2")
        migrate_success(args, 4)
        current = 4

    # Can't migrate, user must delete it
    if current != required:
        raise RuntimeError("Sorry, we can't migrate that automatically. Please"
                           " run 'pmbootstrap shutdown', then delete your"
                           " current work folder manually ('sudo rm -rf " +
                           args.work + "') and start over with 'pmbootstrap"
                           " init'. All your binary packages and caches will"
                           " be lost.")


def validate_hostname(hostname):
    """
    Check whether the string is a valid hostname, according to
    <http://en.wikipedia.org/wiki/Hostname#Restrictions_on_valid_host_names>
    """
    # Check length
    if len(hostname) > 63:
        logging.fatal("ERROR: Hostname '" + hostname + "' is too long.")
        return False

    # Check that it only contains valid chars
    if not re.match("^[0-9a-z-]*$", hostname):
        logging.fatal("ERROR: Hostname must only contain letters (a-z),"
                      " digits (0-9) or minus signs (-)")
        return False

    # Check that doesn't begin or end with a minus sign
    if hostname[:1] == "-" or hostname[-1:] == "-":
        logging.fatal("ERROR: Hostname must not begin or end with a minus sign")
        return False
    return True
