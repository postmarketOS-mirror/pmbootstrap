# Copyright 2021 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import pytest
import sys

import pmb_test
import pmb_test.const
import pmb.parse._apkbuild


@pytest.fixture
def args(tmpdir, request):
    import pmb.parse
    sys.argv = ["pmbootstrap.py", "init"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(args.logfd.close)
    return args


def test_subpackages(args):
    testdata = pmb_test.const.testdata
    path = testdata + "/apkbuild/APKBUILD.subpackages"
    apkbuild = pmb.parse.apkbuild(args, path, check_pkgname=False)

    subpkg = apkbuild["subpackages"]["simple"]
    assert subpkg["pkgdesc"] == ""
    # Inherited from parent package
    assert subpkg["depends"] == ["postmarketos-base"]

    subpkg = apkbuild["subpackages"]["custom"]
    assert subpkg["pkgdesc"] == "This is one of the custom subpackages"
    assert subpkg["depends"] == ["postmarketos-base", "glibc"]

    # Successful extraction
    path = (testdata + "/init_questions_device/aports/device/testing/"
            "device-nonfree-firmware/APKBUILD")
    apkbuild = pmb.parse.apkbuild(args, path)
    subpkg = apkbuild["subpackages"]["device-nonfree-firmware-nonfree-firmware"]
    assert subpkg["pkgdesc"] == "firmware description"

    # Can't find the pkgdesc in the function
    path = testdata + "/apkbuild/APKBUILD.missing-pkgdesc-in-subpackage"
    apkbuild = pmb.parse.apkbuild(args, path, check_pkgname=False)
    subpkg = apkbuild["subpackages"]["missing-pkgdesc-in-subpackage-subpackage"]
    assert subpkg["pkgdesc"] == ""

    # Can't find the function
    assert apkbuild["subpackages"]["invalid-function"] is None


def test_kernels(args):
    # Kernel hardcoded in depends
    args.aports = pmb_test.const.testdata + "/init_questions_device/aports"
    func = pmb.parse._apkbuild.kernels
    device = "lg-mako"
    assert func(args, device) is None

    # Upstream and downstream kernel
    device = "sony-amami"
    ret = {"downstream": "Downstream description",
           "mainline": "Mainline description"}
    assert func(args, device) == ret

    # Long kernel name (e.g. two different mainline kernels)
    device = "wileyfox-crackling"
    ret = {"mainline": "Mainline kernel (no modem)",
           "mainline-modem": "Mainline kernel (with modem)",
           "downstream": "Downstream kernel"}
    assert func(args, device) == ret


def test_depends_in_depends(args):
    path = pmb_test.const.testdata + "/apkbuild/APKBUILD.depends-in-depends"
    apkbuild = pmb.parse.apkbuild(args, path, check_pkgname=False)
    assert apkbuild["depends"] == ["first", "second", "third"]


def test_parse_attributes():
    # Convenience function for calling the function with a block of text
    def func(attribute, block):
        lines = block.split("\n")
        for i in range(0, len(lines)):
            lines[i] += "\n"
        i = 0
        path = "(testcase in " + __file__ + ")"
        print("=== parsing attribute '" + attribute + "' in test block:")
        print(block)
        print("===")
        return pmb.parse._apkbuild.parse_attribute(attribute, lines, i, path)

    assert func("depends", "pkgname='test'") == (False, None, 0)

    assert func("pkgname", 'pkgname="test"') == (True, "test", 0)

    assert func("pkgname", "pkgname='test'") == (True, "test", 0)

    assert func("pkgname", "pkgname=test") == (True, "test", 0)

    assert func("pkgname", 'pkgname="test\n"') == (True, "test", 1)

    assert func("pkgname", 'pkgname="\ntest\n"') == (True, "test", 2)

    assert func("pkgname", 'pkgname="test" # random comment\npkgrel=3') == \
        (True, "test", 0)

    assert func("depends", "depends='\nfirst\nsecond\nthird\n'#") == \
        (True, "first second third", 4)

    assert func("depends", 'depends="\nfirst\n\tsecond third"') == \
        (True, "first second third", 2)

    assert func("depends", 'depends=') == (True, "", 0)

    with pytest.raises(RuntimeError) as e:
        func("depends", 'depends="\nmissing\nend\nquote\nsign')
    assert str(e.value).startswith("Can't find closing")

    with pytest.raises(RuntimeError) as e:
        func("depends", 'depends="')
    assert str(e.value).startswith("Can't find closing")


def test_variable_replacements(args):
    path = pmb_test.const.testdata + "/apkbuild/APKBUILD.variable-replacements"
    apkbuild = pmb.parse.apkbuild(args, path, check_pkgname=False)
    assert apkbuild["pkgdesc"] == "this should not affect variable replacement"
    assert apkbuild["url"] == "replacements variable string-replacements"
    assert list(apkbuild["subpackages"].keys()) == ["replacements", "test"]

    assert apkbuild["subpackages"]["replacements"] is None
    test_subpkg = apkbuild["subpackages"]["test"]
    assert test_subpkg["pkgdesc"] == "this should not affect variable replacement"


def test_parse_maintainers(args):
    path = pmb_test.const.testdata + "/apkbuild/APKBUILD.lint"
    maintainers = [
        "Oliver Smith <ollieparanoid@postmarketos.org>",
        "Hello World <hello@world>"
    ]

    assert pmb.parse._apkbuild.maintainers(path) == maintainers


def test_parse_unmaintained(args):
    path = pmb_test.const.testdata + "/apkbuild/APKBUILD.missing-pkgdesc-in-subpackage"
    assert pmb.parse._apkbuild.unmaintained(path) == "This is broken!"
