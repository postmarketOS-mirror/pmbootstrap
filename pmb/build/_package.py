# Copyright 2021 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import datetime
import logging
import os

import pmb.build
import pmb.build.autodetect
import pmb.chroot
import pmb.chroot.apk
import pmb.chroot.distccd
import pmb.helpers.pmaports
import pmb.helpers.repo
import pmb.parse
import pmb.parse.arch


stack = []


def skip_already_built(args, pkgname, arch):
    """
    Check if the package was already built in this session, and add it
    to the cache in case it was not built yet.

    :returns: True when it can be skipped or False
    """
    if arch not in args.cache["built"]:
        args.cache["built"][arch] = []
    if pkgname in args.cache["built"][arch]:
        logging.verbose(pkgname + ": already checked this session,"
                        " no need to build it or its dependencies")
        return True
    args.cache["built"][arch].append(pkgname)
    return False


def get_apkbuild(args, pkgname, arch):
    """
    Parse the APKBUILD path for pkgname. When there is none, try to find it in
    the binary package APKINDEX files or raise an exception.

    :param pkgname: package name to be built, as specified in the APKBUILD
    :returns: None or parsed APKBUILD
    """
    # Get existing binary package indexes
    pmb.helpers.repo.update(args, arch)

    # Get pmaport, skip upstream only packages
    pmaport = pmb.helpers.pmaports.get(args, pkgname, False)
    if pmaport:
        return pmaport
    if pmb.parse.apkindex.providers(args, pkgname, arch, False):
        return None
    raise RuntimeError("Package '" + pkgname + "': Could not find aport, and"
                       " could not find this package in any APKINDEX!")


def check_build_for_arch(args, pkgname, arch):
    """
    Check if pmaport can be built or exists as binary for a specific arch.
    :returns: * True when it can be built
              * False when it can't be built, but exists in a binary repo
                (e.g. temp/mesa can't be built for x86_64, but Alpine has it)
    :raises: RuntimeError if the package can't be built for the given arch and
             does not exist as binary package.
    """
    # Check for pmaport with arch
    if pmb.helpers.package.check_arch(args, pkgname, arch, False):
        return True

    # Check for binary package
    binary = pmb.parse.apkindex.package(args, pkgname, arch, False)
    if binary:
        pmaport = pmb.helpers.pmaports.get(args, pkgname)
        pmaport_version = pmaport["pkgver"] + "-r" + pmaport["pkgrel"]
        logging.debug(pkgname + ": found pmaport (" + pmaport_version + ") and"
                      " binary package (" + binary["version"] + ", from"
                      " postmarketOS or Alpine), but pmaport can't be built"
                      " for " + arch + " -> using binary package")
        return False

    # No binary package exists and can't build it
    logging.info("NOTE: You can edit the 'arch=' line inside the APKBUILD")
    if args.action == "build":
        logging.info("NOTE: Alternatively, use --arch to build for another"
                     " architecture ('pmbootstrap build --arch=armhf " +
                     pkgname + "')")
    raise RuntimeError("Can't build '" + pkgname + "' for architecture " +
                       arch)


def get_depends(args, apkbuild):
    """
    Alpine's abuild always builds/installs the "depends" and "makedepends"
    of a package before building it. We used to only care about "makedepends"
    and it's still possible to ignore the depends with --ignore-depends.

    :returns: list of dependency pkgnames (eg. ["sdl2", "sdl2_net"])
    """
    # Read makedepends and depends
    ret = list(apkbuild["makedepends"])
    if "!check" not in apkbuild["options"]:
        ret += apkbuild["checkdepends"]
    if "ignore_depends" not in args or not args.ignore_depends:
        ret += apkbuild["depends"]
    ret = sorted(set(ret))

    # Don't recurse forever when a package depends on itself (#948)
    for pkgname in [apkbuild["pkgname"]] + list(apkbuild["subpackages"].keys()):
        if pkgname in ret:
            logging.verbose(apkbuild["pkgname"] + ": ignoring dependency on"
                            " itself: " + pkgname)
            ret.remove(pkgname)
    return ret


def build_depends(args, apkbuild, arch, strict):
    """
    Get and build dependencies with verbose logging messages.

    :returns: (depends, depends_built)
    """
    # Get dependencies
    pkgname = apkbuild["pkgname"]
    depends = get_depends(args, apkbuild)
    logging.verbose(pkgname + ": build/install dependencies: " +
                    ", ".join(depends))

    # --no-depends: check for binary packages
    depends_built = []
    if "no_depends" in args and args.no_depends:
        pmb.helpers.repo.update(args, arch)
        for depend in depends:
            # Check if binary package is missing
            if not pmb.parse.apkindex.package(args, depend, arch, False):
                raise RuntimeError("Missing binary package for dependency '" +
                                   depend + "' of '" + pkgname + "', but"
                                   " pmbootstrap won't build any depends since"
                                   " it was started with --no-depends.")
            # Check if binary package is outdated
            apkbuild_dep = get_apkbuild(args, depend, arch)
            if apkbuild_dep and pmb.build.is_necessary(args, arch, apkbuild_dep):
                raise RuntimeError(f"Binary package for dependency '{depend}'"
                                   f" of '{pkgname}' is outdated, but"
                                   f" pmbootstrap won't build any depends"
                                   f" since it was started with --no-depends.")
    else:
        # Build the dependencies
        for depend in depends:
            if package(args, depend, arch, strict=strict):
                depends_built += [depend]
        logging.verbose(pkgname + ": build dependencies: done, built: " +
                        ", ".join(depends_built))

    return (depends, depends_built)


def is_necessary_warn_depends(args, apkbuild, arch, force, depends_built):
    """
    Check if a build is necessary, and warn if it is not, but there were
    dependencies built.

    :returns: True or False
    """
    pkgname = apkbuild["pkgname"]

    # Check if necessary (this warns about binary version > aport version, so
    # call it even in force mode)
    ret = pmb.build.is_necessary(args, arch, apkbuild)
    if force:
        ret = True

    if not ret and len(depends_built):
        # Warn of potentially outdated package
        logging.warning("WARNING: " + pkgname + " depends on rebuilt" +
                        " package(s) " + ",".join(depends_built) + " (use" +
                        " 'pmbootstrap build " + pkgname + " --force' if" +
                        " necessary!)")

    logging.verbose(pkgname + ": build necessary: " + str(ret))
    return ret


def stack_check_recursion(pkgname):
    global stack

    if pkgname not in stack:
        return

    msg = f"Recursion found while building '{stack[0]}'!\n\n"

    msg += f"Package '{pkgname}' depends on itself:\n\n"
    msg += f"{pkgname}\n"
    for i in range(stack.index(pkgname) + 1, len(stack)):
        msg += f"-> {stack[i]}\n"
    msg += f"-> {pkgname}\n"

    raise RuntimeError(msg)


def init_buildenv(args, apkbuild, arch, strict=False, force=False, cross=None,
                  suffix="native", skip_init_buildenv=False, src=None):
    """
    Build all dependencies, check if we need to build at all (otherwise we've
    just initialized the build environment for nothing) and then setup the
    whole build environment (abuild, gcc, dependencies, cross-compiler).

    :param cross: None, "native", "distcc", or "crossdirect"
    :param skip_init_buildenv: can be set to False to avoid initializing the
                               build environment. Use this when building
                               something during initialization of the build
                               environment (e.g. qemu aarch64 bug workaround)
    :param src: override source used to build the package with a local folder
    :returns: True when the build is necessary (otherwise False)
    """

    depends_arch = arch
    if cross == "native":
        depends_arch = args.arch_native

    # Build dependencies
    depends, built = build_depends(args, apkbuild, depends_arch, strict)

    # Check if build is necessary
    if not is_necessary_warn_depends(args, apkbuild, arch, force, built):
        return False

    # Install and configure abuild, ccache, gcc, dependencies
    if not skip_init_buildenv:
        pmb.build.init(args, suffix)
        pmb.build.other.configure_abuild(args, suffix)
        pmb.build.other.configure_ccache(args, suffix)
    if not strict and "pmb:strict" not in apkbuild["options"] and len(depends):
        pmb.chroot.apk.install(args, depends, suffix)
    if src:
        pmb.chroot.apk.install(args, ["rsync"], suffix)

    # Cross-compiler init
    if cross:
        cross_pkgs = ["ccache-cross-symlinks"]
        if "gcc4" in depends:
            cross_pkgs += ["gcc4-" + arch]
        elif "gcc6" in depends:
            cross_pkgs += ["gcc6-" + arch]
        else:
            cross_pkgs += ["gcc-" + arch, "g++-" + arch]
        if "clang" in depends or "clang-dev" in depends:
            cross_pkgs += ["clang"]
        if cross == "crossdirect":
            cross_pkgs += ["crossdirect"]
            if "rust" in depends or "cargo" in depends:
                cross_pkgs += ["rust"]
        pmb.chroot.apk.install(args, cross_pkgs)
    if cross == "distcc":
        pmb.chroot.distccd.start(args, arch)
    if cross == "crossdirect":
        pmb.chroot.mount_native_into_foreign(args, suffix)

    return True


def get_gcc_version(args, arch):
    """
    Get the GCC version for a specific arch from parsing the right APKINDEX.
    We feed this to ccache, so it knows the right GCC version, when
    cross-compiling in a foreign arch chroot with distcc. See the "using
    ccache with other compiler wrappers" section of their man page:
    <https://linux.die.net/man/1/ccache>
    :returns: a string like "6.4.0-r5"
    """
    return pmb.parse.apkindex.package(args, "gcc-" + arch,
                                      args.arch_native)["version"]


def get_pkgver(original_pkgver, original_source=False, now=None):
    """
    Get the original pkgver when using the original source. Otherwise, get the
    pkgver with an appended suffix of current date and time. For example:
        _p20180218550502
    When appending the suffix, an existing suffix (e.g. _git20171231) gets
    replaced.

    :param original_pkgver: unmodified pkgver from the package's APKBUILD.
    :param original_source: the original source is used instead of overriding
                            it with --src.
    :param now: use a specific date instead of current date (for test cases)
    """
    if original_source:
        return original_pkgver

    # Append current date
    no_suffix = original_pkgver.split("_", 1)[0]
    now = now if now else datetime.datetime.now()
    new_suffix = "_p" + now.strftime("%Y%m%d%H%M%S")
    return no_suffix + new_suffix


def override_source(args, apkbuild, pkgver, src, suffix="native"):
    """
    Mount local source inside chroot and append new functions (prepare() etc.)
    to the APKBUILD to make it use the local source.
    """
    if not src:
        return

    # Mount source in chroot
    mount_path = "/mnt/pmbootstrap-source-override/"
    mount_path_outside = args.work + "/chroot_" + suffix + mount_path
    pmb.helpers.mount.bind(args, src, mount_path_outside, umount=True)

    # Delete existing append file
    append_path = "/tmp/APKBUILD.append"
    append_path_outside = args.work + "/chroot_" + suffix + append_path
    if os.path.exists(append_path_outside):
        pmb.chroot.root(args, ["rm", append_path], suffix)

    # Add src path to pkgdesc, cut it off after max length
    pkgdesc = ("[" + src + "] " + apkbuild["pkgdesc"])[:127]

    # Appended content
    append = """
             # ** Overrides below appended by pmbootstrap for --src **

             pkgver=\"""" + pkgver + """\"
             pkgdesc=\"""" + pkgdesc + """\"
             _pmb_src_copy="/tmp/pmbootstrap-local-source-copy"

             # Empty $source avoids patching in prepare()
             _pmb_source_original="$source"
             source=""
             sha512sums=""

             fetch() {
                 # Update source copy
                 msg "Copying source from host system: """ + src + """\"
                 rsync -a --exclude=".git/" --delete --ignore-errors --force \\
                     \"""" + mount_path + """\" "$_pmb_src_copy" || true

                 # Link local source files (e.g. kernel config)
                 mkdir "$srcdir"
                 local s
                 for s in $_pmb_source_original; do
                     is_remote "$s" || ln -sf "$startdir/$s" "$srcdir/"
                 done
             }

             unpack() {
                 ln -sv "$_pmb_src_copy" "$builddir"
             }
             """

    # Write and log append file
    with open(append_path_outside, "w", encoding="utf-8") as handle:
        for line in append.split("\n"):
            handle.write(line[13:].replace(" " * 4, "\t") + "\n")
    pmb.chroot.user(args, ["cat", append_path], suffix)

    # Append it to the APKBUILD
    apkbuild_path = "/home/pmos/build/APKBUILD"
    shell_cmd = ("cat " + apkbuild_path + " " + append_path + " > " +
                 append_path + "_")
    pmb.chroot.user(args, ["sh", "-c", shell_cmd], suffix)
    pmb.chroot.user(args, ["mv", append_path + "_", apkbuild_path], suffix)


def link_to_git_dir(args, suffix):
    """
    Make /home/pmos/build/.git point to the .git dir from pmaports.git, with a
    symlink so abuild does not fail (#1841).

    abuild expects the current working directory to be a subdirectory of a
    cloned git repository (e.g. main/openrc from aports.git). If git is
    installed, it will try to get the last git commit from that repository, and
    place it in the resulting apk (.PKGINFO) as well as use the date from that
    commit as SOURCE_DATE_EPOCH (for reproducible builds).

    With that symlink, we actually make it use the last git commit from
    pmaports.git for SOURCE_DATE_EPOCH and have that in the resulting apk's
    .PKGINFO.
    """
    # Mount pmaports.git in chroot, in case the user did not use pmbootstrap to
    # clone it (e.g. how we build on sourcehut). Do this here and not at the
    # initialization of the chroot, because the pmaports dir may not exist yet
    # at that point. Use umount=True, so we don't have an old path mounted
    # (some tests change the pmaports dir).
    inside_destination = "/mnt/pmaports"
    outside_destination = args.work + "/chroot_" + suffix + inside_destination
    pmb.helpers.mount.bind(args, args.aports, outside_destination, umount=True)

    # Create .git symlink
    pmb.chroot.user(args, ["mkdir", "-p", "/home/pmos/build"], suffix)
    pmb.chroot.user(args, ["ln", "-sf", inside_destination + "/.git",
                           "/home/pmos/build/.git"], suffix)


def run_abuild(args, apkbuild, arch, strict=False, force=False, cross=None,
               suffix="native", src=None):
    """
    Set up all environment variables and construct the abuild command (all
    depending on the cross-compiler method and target architecture), copy
    the aport to the chroot and execute abuild.

    :param cross: None, "native", "distcc", or "crossdirect"
    :param src: override source used to build the package with a local folder
    :returns: (output, cmd, env), output is the destination apk path relative
              to the package folder ("x86_64/hello-1-r2.apk"). cmd and env are
              used by the test case, and they are the full abuild command and
              the environment variables dict generated in this function.
    """
    # Sanity check
    if cross == "native" and "!tracedeps" not in apkbuild["options"]:
        logging.info("WARNING: Option !tracedeps is not set, but we're"
                     " cross-compiling in the native chroot. This will"
                     " probably fail!")

    # Pretty log message
    pkgver = get_pkgver(apkbuild["pkgver"], src is None)
    output = (arch + "/" + apkbuild["pkgname"] + "-" + pkgver +
              "-r" + apkbuild["pkgrel"] + ".apk")
    message = "(" + suffix + ") build " + output
    if src:
        message += " (source: " + src + ")"
    logging.info(message)

    # Environment variables
    env = {"CARCH": arch,
           "SUDO_APK": "abuild-apk --no-progress"}
    if cross == "native":
        hostspec = pmb.parse.arch.alpine_to_hostspec(arch)
        env["CROSS_COMPILE"] = hostspec + "-"
        env["CC"] = hostspec + "-gcc"
    if cross == "distcc":
        env["CCACHE_PREFIX"] = "distcc"
        env["CCACHE_PATH"] = "/usr/lib/arch-bin-masquerade/" + arch + ":/usr/bin"
        env["CCACHE_COMPILERCHECK"] = "string:" + get_gcc_version(args, arch)
        env["DISTCC_HOSTS"] = "@127.0.0.1:/home/pmos/.distcc-sshd/distccd"
        env["DISTCC_SSH"] = ("ssh -o StrictHostKeyChecking=no -p" +
                             args.port_distccd)
        env["DISTCC_BACKOFF_PERIOD"] = "0"
        if not args.distcc_fallback:
            env["DISTCC_FALLBACK"] = "0"
        if args.verbose:
            env["DISTCC_VERBOSE"] = "1"
    if cross == "crossdirect":
        env["PATH"] = ":".join(["/native/usr/lib/crossdirect/" + arch,
                                pmb.config.chroot_path])
    if not args.ccache:
        env["CCACHE_DISABLE"] = "1"

    # Build the abuild command
    cmd = ["abuild", "-D", "postmarketOS"]
    if strict or "pmb:strict" in apkbuild["options"]:
        if not strict:
            logging.debug(apkbuild["pkgname"] + ": 'pmb:strict' found in"
                          " options, building in strict mode")
        cmd += ["-r"]  # install depends with abuild
    else:
        cmd += ["-d"]  # do not install depends with abuild
    if force:
        cmd += ["-f"]

    # Copy the aport to the chroot and build it
    pmb.build.copy_to_buildpath(args, apkbuild["pkgname"], suffix)
    override_source(args, apkbuild, pkgver, src, suffix)
    link_to_git_dir(args, suffix)
    pmb.chroot.user(args, cmd, suffix, "/home/pmos/build", env=env)
    return (output, cmd, env)


def finish(args, apkbuild, arch, output, strict=False, suffix="native"):
    """
    Various finishing tasks that need to be done after a build.
    """
    # Verify output file
    channel = pmb.config.pmaports.read_config(args)["channel"]
    path = f"{args.work}/packages/{channel}/{output}"
    if not os.path.exists(path):
        raise RuntimeError("Package not found after build: " + path)

    # Clear APKINDEX cache (we only parse APKINDEX files once per session and
    # cache the result for faster dependency resolving, but after we built a
    # package we need to parse it again)
    pmb.parse.apkindex.clear_cache(args, f"{args.work}/packages/{channel}"
                                         f"/{arch}/APKINDEX.tar.gz")

    # Uninstall build dependencies (strict mode)
    if strict or "pmb:strict" in apkbuild["options"]:
        logging.info("(" + suffix + ") uninstall build dependencies")
        pmb.chroot.user(args, ["abuild", "undeps"], suffix, "/home/pmos/build",
                        env={"SUDO_APK": "abuild-apk --no-progress"})


def package(args, pkgname, arch=None, force=False, strict=False,
            skip_init_buildenv=False, src=None):
    """
    Build a package and its dependencies with Alpine Linux' abuild.

    If this function is called multiple times on the same pkgname but first
    with force=False and then force=True the force argument will be ignored due
    to the package cache.
    See the skip_already_built() call below.

    :param pkgname: package name to be built, as specified in the APKBUILD
    :param arch: architecture we're building for (default: native)
    :param force: always build, even if not necessary
    :param strict: avoid building with irrelevant dependencies installed by
                   letting abuild install and uninstall all dependencies.
    :param skip_init_buildenv: can be set to False to avoid initializing the
                               build environment. Use this when building
                               something during initialization of the build
                               environment (e.g. qemu aarch64 bug workaround)
    :param src: override source used to build the package with a local folder
    :returns: None if the build was not necessary
              output path relative to the packages folder ("armhf/ab-1-r2.apk")
    """
    global stack

    stack_check_recursion(pkgname)
    stack.append(pkgname)
    stack_str = f"[package build stack] {' -> '.join(stack)}"

    # Once per session is enough
    arch = arch or args.arch_native
    logging.verbose(f"{stack_str}: evaluating")
    if skip_already_built(args, pkgname, arch):
        logging.verbose(f"{stack_str}: skip build: skip_already_built")
        stack.pop()
        return

    # Only build when APKBUILD exists
    apkbuild = get_apkbuild(args, pkgname, arch)
    if not apkbuild:
        logging.verbose(f"{stack_str}: skip build: get_apkbuild")
        stack.pop()
        return

    # Detect the build environment (skip unnecessary builds)
    if not check_build_for_arch(args, pkgname, arch):
        logging.verbose(f"{stack_str}: skip build: check_build_for_arch")
        stack.pop()
        return
    suffix = pmb.build.autodetect.suffix(args, apkbuild, arch)
    cross = pmb.build.autodetect.crosscompile(args, apkbuild, arch, suffix)
    logging.verbose(f"{stack_str}: building dependencies")
    if not init_buildenv(args, apkbuild, arch, strict, force, cross, suffix,
                         skip_init_buildenv, src):
        logging.verbose(f"{stack_str}: skip build: init_buildenv")
        stack.pop()
        return

    # Build and finish up
    logging.verbose(f"{stack_str}: building")
    (output, cmd, env) = run_abuild(args, apkbuild, arch, strict, force, cross,
                                    suffix, src)
    finish(args, apkbuild, arch, output, strict, suffix)

    logging.verbose(f"{stack_str}: built successfully")
    stack.pop()
    return output
