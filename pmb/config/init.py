# Copyright 2021 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import glob
import os
import shutil

import pmb.aportgen
import pmb.config
import pmb.config.pmaports
import pmb.helpers.cli
import pmb.helpers.devices
import pmb.helpers.logging
import pmb.helpers.other
import pmb.helpers.run
import pmb.helpers.ui
import pmb.chroot.zap
import pmb.parse.deviceinfo
import pmb.parse._apkbuild


def require_programs():
    missing = []
    for program in pmb.config.required_programs:
        if not shutil.which(program):
            missing.append(program)
    if missing:
        raise RuntimeError("Can't find all programs required to run"
                           " pmbootstrap. Please install first: " +
                           ", ".join(missing))


def ask_for_work_path(args):
    """
    Ask for the work path, until we can create it (when it does not exist) and
    write into it.
    :returns: (path, exists)
              * path: is the full path, with expanded ~ sign
              * exists: is False when the folder did not exist before we tested
                        whether we can create it
    """
    logging.info("Location of the 'work' path. Multiple chroots"
                 " (native, device arch, device rootfs) will be created"
                 " in there.")
    while True:
        try:
            work = os.path.expanduser(pmb.helpers.cli.ask(
                args, "Work path", None, args.work, False))
            work = os.path.realpath(work)
            exists = os.path.exists(work)

            # Work must not be inside the pmbootstrap path
            if (work == pmb.config.pmb_src or
                    work.startswith(pmb.config.pmb_src + "/")):
                logging.fatal("ERROR: The work path must not be inside the"
                              " pmbootstrap path. Please specify another"
                              " location.")
                continue

            # Create the folder with a version file
            if not exists:
                os.makedirs(work, 0o700, True)

            if not os.listdir(work):
                # Directory is empty, either because we just created it or
                # because user created it before running pmbootstrap init
                with open(work + "/version", "w") as handle:
                    handle.write(str(pmb.config.work_version) + "\n")

            # Create cache_git dir, so it is owned by the host system's user
            # (otherwise pmb.helpers.mount.bind would create it as root)
            os.makedirs(work + "/cache_git", 0o700, True)
            return (work, exists)
        except OSError:
            logging.fatal("ERROR: Could not create this folder, or write"
                          " inside it! Please try again.")


def ask_for_channel(args):
    """ Ask for the postmarketOS release channel. The channel dictates, which
        pmaports branch pmbootstrap will check out, and which repository URLs
        will be used when initializing chroots.
        :returns: channel name (e.g. "edge", "stable") """
    channels_cfg = pmb.helpers.git.parse_channels_cfg(args)
    count = len(channels_cfg["channels"])

    # List channels
    logging.info("Choose the postmarketOS release channel.")
    logging.info(f"Available ({count}):")
    for channel, channel_data in channels_cfg["channels"].items():
        logging.info(f"* {channel}: {channel_data['description']}")

    # Default for first run: "recommended" from channels.cfg
    # Otherwise, if valid: channel from pmaports.cfg of current branch
    # The actual channel name is not saved in pmbootstrap.cfg, because then we
    # would need to sync it with what is checked out in pmaports.git.
    default = pmb.config.pmaports.read_config(args)["channel"]
    choices = channels_cfg["channels"].keys()
    if args.is_default_channel or default not in choices:
        default = channels_cfg["meta"]["recommended"]

    # Ask until user gives valid channel
    while True:
        ret = pmb.helpers.cli.ask(args, "Channel", None, default,
                                  complete=choices)
        if ret in choices:
            return ret
        logging.fatal("ERROR: Invalid channel specified, please type in one"
                      " from the list above.")


def ask_for_ui(args, device):
    info = pmb.parse.deviceinfo(args, device)
    ui_list = pmb.helpers.ui.list(args, info["arch"])
    logging.info("Available user interfaces (" +
                 str(len(ui_list) - 1) + "): ")
    ui_completion_list = []
    for ui in ui_list:
        logging.info("* " + ui[0] + ": " + ui[1])
        ui_completion_list.append(ui[0])
    while True:
        ret = pmb.helpers.cli.ask(args, "User interface", None, args.ui, True,
                                  complete=ui_completion_list)
        if ret in dict(ui_list).keys():
            return ret
        logging.fatal("ERROR: Invalid user interface specified, please type in"
                      " one from the list above.")


def ask_for_ui_extras(args, ui):
    apkbuild = pmb.helpers.pmaports.get(args, "postmarketos-ui-" + ui,
                                        subpackages=False, must_exist=False)
    if not apkbuild:
        return False

    extra = apkbuild["subpackages"].get("postmarketos-ui-" + ui + "-extras")
    if extra is None:
        return False

    logging.info("This user interface has an extra package: " + extra["pkgdesc"])

    return pmb.helpers.cli.confirm(args, "Enable this package?",
                                   default=args.ui_extras)


def ask_for_keymaps(args, device):
    info = pmb.parse.deviceinfo(args, device)
    if "keymaps" not in info or info["keymaps"].strip() == "":
        return ""
    options = info["keymaps"].split(' ')
    logging.info("Available keymaps for device (" + str(len(options)) +
                 "): " + ", ".join(options))
    if args.keymap == "":
        args.keymap = options[0]

    while True:
        ret = pmb.helpers.cli.ask(args, "Keymap", None, args.keymap,
                                  True, complete=options)
        if ret in options:
            return ret
        logging.fatal("ERROR: Invalid keymap specified, please type in"
                      " one from the list above.")


def ask_for_timezone(args):
    localtimes = ["/etc/zoneinfo/localtime", "/etc/localtime"]
    zoneinfo_path = "/usr/share/zoneinfo/"
    for localtime in localtimes:
        if not os.path.exists(localtime):
            continue
        tz = ""
        if os.path.exists(localtime):
            tzpath = os.path.realpath(localtime)
            tzpath = tzpath.rstrip()
            if os.path.exists(tzpath):
                try:
                    _, tz = tzpath.split(zoneinfo_path)
                except:
                    pass
        if tz:
            logging.info("Your host timezone: " + tz)
            if pmb.helpers.cli.confirm(args, "Use this timezone instead of GMT?",
                                       default="y"):
                return tz
    logging.info("WARNING: Unable to determine timezone configuration on host,"
                 " using GMT.")
    return "GMT"


def ask_for_device_kernel(args, device):
    """
    Ask for the kernel that should be used with the device.

    :param device: code name, e.g. "lg-mako"
    :returns: None if the kernel is hardcoded in depends without subpackages
    :returns: kernel type ("downstream", "stable", "mainline", ...)
    """
    # Get kernels
    kernels = pmb.parse._apkbuild.kernels(args, device)
    if not kernels:
        return args.kernel

    # Get default
    default = args.kernel
    if default not in kernels:
        default = list(kernels.keys())[0]

    # Ask for kernel (extra message when downstream and upstream are available)
    logging.info("Which kernel do you want to use with your device?")
    if "downstream" in kernels:
        logging.info("Downstream kernels are typically the outdated Android"
                     " kernel forks.")
    if "downstream" in kernels and len(kernels) > 1:
        logging.info("Upstream kernels (mainline, stable, ...) get security"
                     " updates, but may have less working features than"
                     " downstream kernels.")

    # List kernels
    logging.info("Available kernels (" + str(len(kernels)) + "):")
    for type in sorted(kernels.keys()):
        logging.info("* " + type + ": " + kernels[type])
    while True:
        ret = pmb.helpers.cli.ask(args, "Kernel", None, default, True,
                                  complete=kernels)
        if ret in kernels.keys():
            return ret
        logging.fatal("ERROR: Invalid kernel specified, please type in one"
                      " from the list above.")
    return ret


def ask_for_device_nonfree(args, device):
    """
    Ask the user about enabling proprietary firmware (e.g. Wifi) and userland
    (e.g. GPU drivers). All proprietary components are in subpackages
    $pkgname-nonfree-firmware and $pkgname-nonfree-userland, and we show the
    description of these subpackages (so they can indicate which peripherals
    are affected).

    :returns: answers as dict, e.g. {"firmware": True, "userland": False}
    """
    # Parse existing APKBUILD or return defaults (when called from test case)
    apkbuild_path = pmb.helpers.devices.find_path(args, device, 'APKBUILD')
    ret = {"firmware": args.nonfree_firmware,
           "userland": args.nonfree_userland}
    if not apkbuild_path:
        return ret
    apkbuild = pmb.parse.apkbuild(args, apkbuild_path)

    # Only run when there is a "nonfree" subpackage
    nonfree_found = False
    for subpackage in apkbuild["subpackages"].keys():
        if subpackage.startswith("device-" + device + "-nonfree"):
            nonfree_found = True
    if not nonfree_found:
        return ret

    # Short explanation
    logging.info("This device has proprietary components, which trade some of"
                 " your freedom with making more peripherals work.")
    logging.info("We would like to offer full functionality without hurting"
                 " your freedom, but this is currently not possible for your"
                 " device.")

    # Ask for firmware and userland individually
    for type in ["firmware", "userland"]:
        subpkgname = "device-" + device + "-nonfree-" + type
        subpkg = apkbuild["subpackages"].get(subpkgname, {})
        if subpkg is None:
            raise RuntimeError("Cannot find subpackage function for " + subpkgname)
        if subpkg:
            logging.info(subpkgname + ": " + subpkg["pkgdesc"])
            ret[type] = pmb.helpers.cli.confirm(args, "Enable this package?",
                                                default=ret[type])
    return ret


def ask_for_device(args):
    vendors = sorted(pmb.helpers.devices.list_vendors(args))
    logging.info("Choose your target device vendor (either an "
                 "existing one, or a new one for porting).")
    logging.info("Available vendors (" + str(len(vendors)) + "): " +
                 ", ".join(vendors))

    current_vendor = None
    current_codename = None
    if args.device:
        current_vendor = args.device.split("-", 1)[0]
        current_codename = args.device.split("-", 1)[1]

    while True:
        vendor = pmb.helpers.cli.ask(args, "Vendor", None, current_vendor,
                                     False, r"[a-z0-9]+", vendors)

        new_vendor = vendor not in vendors
        codenames = []
        if new_vendor:
            logging.info("The specified vendor ({}) could not be found in"
                         " existing ports, do you want to start a new"
                         " port?".format(vendor))
            if not pmb.helpers.cli.confirm(args, default=True):
                continue
        else:
            # Unmaintained devices can be selected, but are not displayed
            devices = sorted(pmb.helpers.devices.list_codenames(args, vendor, unmaintained=False))
            # Remove "vendor-" prefixes from device list
            codenames = [x.split('-', 1)[1] for x in devices]
            logging.info("Available codenames (" + str(len(codenames)) + "): " +
                         ", ".join(codenames))

        if current_vendor != vendor:
            current_codename = ''
        codename = pmb.helpers.cli.ask(args, "Device codename", None,
                                       current_codename, False, r"[a-z0-9]+",
                                       codenames)

        device = vendor + '-' + codename
        device_path = pmb.helpers.devices.find_path(args, device, 'deviceinfo')
        device_exists = device_path is not None
        if not device_exists:
            if device == args.device:
                raise RuntimeError(
                    "This device does not exist anymore, check"
                    " <https://postmarketos.org/renamed>"
                    " to see if it was renamed")
            logging.info("You are about to do a new device port for '" +
                         device + "'.")
            if not pmb.helpers.cli.confirm(args, default=True):
                current_vendor = vendor
                continue

            # New port creation confirmed
            logging.info("Generating new aports for: {}...".format(device))
            pmb.aportgen.generate(args, "device-" + device)
            pmb.aportgen.generate(args, "linux-" + device)
        elif "/unmaintained/" in device_path:
            apkbuild = device_path[:-len("deviceinfo")] + 'APKBUILD'
            unmaintained = pmb.parse._apkbuild.unmaintained(apkbuild)
            logging.info(f"WARNING: {device} is unmaintained: {unmaintained}")
            if not pmb.helpers.cli.confirm(args):
                continue
        break

    kernel = ask_for_device_kernel(args, device)
    nonfree = ask_for_device_nonfree(args, device)
    return (device, device_exists, kernel, nonfree)


def ask_for_additional_options(args, cfg):
    # Allow to skip additional options
    logging.info("Additional options:"
                 f" extra free space: {args.extra_space} MB,"
                 f" boot partition size: {args.boot_size} MB,"
                 f" parallel jobs: {args.jobs},"
                 f" ccache per arch: {args.ccache_size},"
                 f" sudo timer: {args.sudo_timer}")

    if not pmb.helpers.cli.confirm(args, "Change them?",
                                   default=False):
        return

    # Extra space
    logging.info("Set extra free space to 0, unless you ran into a 'No space"
                 " left on device' error. In that case, the size of the"
                 " rootfs could not be calculated properly on your machine,"
                 " and we need to add extra free space to make the image big"
                 " enough to fit the rootfs (pmaports#1904)."
                 " How much extra free space do you want to add to the image"
                 " (in MB)?")
    answer = pmb.helpers.cli.ask(args, "Extra space size", None,
                                 args.extra_space, validation_regex="[0-9]+")
    cfg["pmbootstrap"]["extra_space"] = answer

    # Boot size
    logging.info("What should be the boot partition size (in MB)?")
    answer = pmb.helpers.cli.ask(args, "Boot size", None, args.boot_size,
                                 validation_regex="[1-9][0-9]*")
    cfg["pmbootstrap"]["boot_size"] = answer

    # Parallel job count
    logging.info("How many jobs should run parallel on this machine, when"
                 " compiling?")
    answer = pmb.helpers.cli.ask(args, "Jobs", None, args.jobs,
                                 validation_regex="[1-9][0-9]*")
    cfg["pmbootstrap"]["jobs"] = answer

    # Ccache size
    logging.info("We use ccache to speed up building the same code multiple"
                 " times. How much space should the ccache folder take up per"
                 " architecture? After init is through, you can check the current"
                 " usage with 'pmbootstrap stats'. Answer with 0 for infinite.")
    regex = "0|[0-9]+(k|M|G|T|Ki|Mi|Gi|Ti)"
    answer = pmb.helpers.cli.ask(args, "Ccache size", None, args.ccache_size,
                                 lowercase_answer=False, validation_regex=regex)
    cfg["pmbootstrap"]["ccache_size"] = answer

    # Sudo timer
    logging.info("pmbootstrap does everything in Alpine Linux chroots, so"
                 " your host system does not get modified. In order to"
                 " work with these chroots, pmbootstrap calls 'sudo'"
                 " internally. For long running operations, it is possible"
                 " that you'll have to authorize sudo more than once.")
    answer = pmb.helpers.cli.confirm(args, "Enable background timer to prevent"
                                     " repeated sudo authorization?",
                                     default=args.sudo_timer)
    cfg["pmbootstrap"]["sudo_timer"] = str(answer)


def ask_for_hostname(args, device):
    while True:
        ret = pmb.helpers.cli.ask(args, "Device hostname (short form, e.g. 'foo')",
                                  None, (args.hostname or device), True)
        if not pmb.helpers.other.validate_hostname(ret):
            continue
        # Don't store device name in user's config (gets replaced in install)
        if ret == device:
            return ""
        return ret


def ask_for_ssh_keys(args):
    if not len(glob.glob(os.path.expanduser("~/.ssh/id_*.pub"))):
        return False
    return pmb.helpers.cli.confirm(args,
                                   "Would you like to copy your SSH public keys to the device?",
                                   default=args.ssh_keys)


def ask_build_pkgs_on_install(args):
    logging.info("After pmaports are changed, the binary packages may be"
                 " outdated. If you want to install postmarketOS without"
                 " changes, reply 'n' for a faster installation.")
    return pmb.helpers.cli.confirm(args, "Build outdated packages during"
                                   " 'pmbootstrap install'?",
                                   default=args.build_pkgs_on_install)


def ask_for_locale(args):
    locales = pmb.config.locales
    logging.info(f"Available locales ({len(locales)}): {', '.join(locales)}")
    return pmb.helpers.cli.ask(args, "Choose default locale for installation",
                               default=args.locale,
                               lowercase_answer=False,
                               validation_regex="|".join(locales),
                               complete=locales)


def frontend(args):
    require_programs()

    # Work folder (needs to be first, so we can create chroots early)
    cfg = pmb.config.load(args)
    work, work_exists = ask_for_work_path(args)
    cfg["pmbootstrap"]["work"] = work

    # Update args and save config (so chroots and 'pmbootstrap log' work)
    pmb.helpers.args.update_work(args, work)
    pmb.config.save(args, cfg)

    # Migrate work dir if necessary
    pmb.helpers.other.migrate_work_folder(args)

    # Clone pmaports
    pmb.config.pmaports.init(args)

    # Choose release channel, possibly switch pmaports branch
    channel = ask_for_channel(args)
    pmb.config.pmaports.switch_to_channel_branch(args, channel)
    cfg["pmbootstrap"]["is_default_channel"] = "False"

    # Device
    device, device_exists, kernel, nonfree = ask_for_device(args)
    cfg["pmbootstrap"]["device"] = device
    cfg["pmbootstrap"]["kernel"] = kernel
    cfg["pmbootstrap"]["nonfree_firmware"] = str(nonfree["firmware"])
    cfg["pmbootstrap"]["nonfree_userland"] = str(nonfree["userland"])

    # Device keymap
    if device_exists:
        cfg["pmbootstrap"]["keymap"] = ask_for_keymaps(args, device)

    # Username
    cfg["pmbootstrap"]["user"] = pmb.helpers.cli.ask(args, "Username", None,
                                                     args.user, False,
                                                     "[a-z_][a-z0-9_-]*")
    # UI and various build options
    ui = ask_for_ui(args, device)
    cfg["pmbootstrap"]["ui"] = ui
    cfg["pmbootstrap"]["ui_extras"] = str(ask_for_ui_extras(args, ui))
    ask_for_additional_options(args, cfg)

    # Extra packages to be installed to rootfs
    logging.info("Additional packages that will be installed to rootfs."
                 " Specify them in a comma separated list (e.g.: vim,file)"
                 " or \"none\"")
    extra = pmb.helpers.cli.ask(args, "Extra packages", None,
                                args.extra_packages,
                                validation_regex=r"^([-.+\w]+)(,[-.+\w]+)*$")
    cfg["pmbootstrap"]["extra_packages"] = extra

    # Configure timezone info
    cfg["pmbootstrap"]["timezone"] = ask_for_timezone(args)

    # Locale
    cfg["pmbootstrap"]["locale"] = ask_for_locale(args)

    # Hostname
    cfg["pmbootstrap"]["hostname"] = ask_for_hostname(args, device)

    # SSH keys
    cfg["pmbootstrap"]["ssh_keys"] = str(ask_for_ssh_keys(args))

    # pmaports path (if users change it with: 'pmbootstrap --aports=... init')
    cfg["pmbootstrap"]["aports"] = args.aports

    # Build outdated packages in pmbootstrap install
    cfg["pmbootstrap"]["build_pkgs_on_install"] = str(ask_build_pkgs_on_install(args))

    # Save config
    pmb.config.save(args, cfg)

    # Zap existing chroots
    if (work_exists and device_exists and
            len(glob.glob(args.work + "/chroot_*")) and
            pmb.helpers.cli.confirm(args, "Zap existing chroots to apply configuration?", default=True)):
        setattr(args, "deviceinfo", pmb.parse.deviceinfo(args, device=device))

        # Do not zap any existing packages or cache_http directories
        pmb.chroot.zap(args, confirm=False)

    logging.info("WARNING: The chroots and git repositories in the work dir do"
                 " not get updated automatically.")
    logging.info("Run 'pmbootstrap status' once a day before working with"
                 " pmbootstrap to make sure that everything is up-to-date.")
    logging.info("Done!")
