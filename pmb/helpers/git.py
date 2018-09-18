"""
Copyright 2018 Oliver Smith

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
import logging
import os
import shutil
import tempfile

import pmb.build
import pmb.chroot.apk
import pmb.config
import pmb.helpers.run


def clone_outside(args, options, name_repo, name_temp, chown_to_user):
    """
    Use the host system's git program as fallback for cloning a git repository.

    :param options: list of git options, e.g. ["--depth=1"] or []
    :param name_repo: the repositories name from pmb.config.git_repos
    :param name_temp: the temporary name to which the repo will be cloned
    :param chown_to_user: change ownership to the host system's user
    """
    logging.info("NOTE: failed to clone with git inside Alpine's chroot. This"
                 " may happen with some host kernels (pmbootstrap#1662)."
                 " Trying again with the host system's git binary.")

    # Make sure we have git
    if not shutil.which("git"):
        logging.info("Please install 'git' on your host system's Linux"
                     " distribution with its package manager and try again.")
        raise RuntimeError("Failed to clone with git inside Alpine's chroot,"
                           " and git is not installed in the host system.")

    # Clone to temporary folder
    tempdir = tempfile.mkdtemp(prefix="pmbootstrap_git_clone_temp")
    url = pmb.config.git_repos[name_repo]
    pmb.helpers.run.user(args, ["git", "-C", tempdir] + options + ["clone",
                         url, name_temp], output="stdout")
    # Move to pmaports folder
    pmb.helpers.run.root(args, ["mv", tempdir + "/" + name_temp, args.work +
                                "/cache_git/"])

    # Chown to the chroot's pmos user
    if not chown_to_user:
        pmb.chroot.root(args, ["chown", "-R", "pmos:users", "/home/pmos/git/" +
                               name_temp])


def clone(args, name_repo, shallow=True, chown_to_user=False):
    """
    Clone a git repository from the config to $work/cache_git using the git
    program from the native chroot.

    :param name_repo: the repositories name from pmb.config.git_repos
    :param shallow: only clone the latest revision, not the entire git history
                    (less traffic)
    :param chown_to_user: change ownership to the host system's user
    """
    # Check for repo name in the config
    if name_repo not in pmb.config.git_repos:
        raise ValueError("No git repository configured for " + name_repo)

    # Skip if already checked out
    if os.path.exists(args.work + "/cache_git/" + name_repo):
        return

    # Check out to temp folder
    name_temp = name_repo + ".temp"
    if not os.path.exists(args.work + "/cache_git/" + name_temp):
        # Set up chroot and install git
        pmb.chroot.apk.install(args, ["git"])
        logging.info("(native) git clone " + pmb.config.git_repos[name_repo])

        # git options
        options = []
        if shallow:
            options += ["--depth=1"]

        # Run the command
        pmb.chroot.user(args, ["git", "clone"] + options +
                              [pmb.config.git_repos[name_repo], name_temp],
                        working_dir="/home/pmos/git/", check=False,
                        output="stdout")
        if not os.path.exists(args.work + "/cache_git/" + name_temp):
            clone_outside(args, options, name_repo, name_temp, chown_to_user)

    # Chown to user's UID and GID
    if chown_to_user:
        uid_gid = "{}:{}".format(os.getuid(), os.getgid())
        pmb.helpers.run.root(args, ["chown", "-R", uid_gid, args.work +
                                    "/cache_git/" + name_temp])

    # Rename the temp folder
    pmb.helpers.run.root(args, ["mv", name_temp, name_repo],
                         args.work + "/cache_git")


def rev_parse(args, revision="HEAD"):
    rev = pmb.helpers.run.user(args, ["git", "rev-parse", revision],
                               args.aports, output_return=True, check=False)
    if rev is None:
        logging.warning("WARNING: Failed to determine revision of git repository at " + args.aports)
        return ""
    return rev.rstrip()
