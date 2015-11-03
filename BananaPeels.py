#!/usr/bin/python

import argparse
import fnmatch
import glob
import os
import plistlib
import subprocess
import time

TEST_MANIFEST = "test_munki_client"
VMRUN_CMD     = "/Applications/VMware Fusion.app/Contents/Library/vmrun"
DL_CMD        = "sudo /usr/local/munki/managedsoftwareupdate"
INSTALL_CMD   = "sudo /usr/local/munki/managedsoftwareupdate --installonly"

# Defines object to handle tests for each SUT
class TestRunner:

    def __init__(self, repo_path, vmx_path, admin, admin_pw, pkg_filter=None):
        self.repo_path = repo_path
        self.repo_info = dict()
        self.vmx_path  = vmx_path
        self.admin     = admin
        self.admin_pw  = admin_pw
        self.results   = dict(runtime=0.0, run=0, failed=0, details=dict())
        self.auditRepo(pkg_filter)

    # Returns info for all pkginfos in specified repo.
    # If filter of pkginfo(s) is specified returns only
    # info for those specified in filter.
    def auditRepo(self, pkg_filter):
        repo_dict = dict()
        info_dir  = os.path.join(self.repo_path, "pkgsinfo")
        pkginfos  = []
        for root, dirnames, filenames in os.walk(info_dir):
            for filename in filenames:
                if filename.endswith(('.pkginfo', '.plist')):
                    pkginfos.append(os.path.join(root, filename))
        for pkginfo in pkginfos:
            sut = SUT(pkginfo)
            if sut.name is None or sut.version is None:
                print "%s is missing it's name or version" % pkginfo
                print "Skipping"
                continue
            name_vers = sut.name + '-' + str(sut.version)
            # If specific pkginfos requested for test ignore all others
            if pkg_filter is not None and name_vers not in pkg_filter:
                continue
            if repo_dict.get(name_vers) is None:
                repo_dict[name_vers] = sut
            else:
                print "There appears to be duplicate pkginfos for the specified name and version."
                print "The culprit pkginfos can be found here:"
                print sut.pkginfo
                print repo_dict[name_vers].pkginfo
        # Print when debugging
        # for key, value in repo_dict.iteritems():
        #     print key
        #     print value.pkginfo
        self.repo_info = repo_dict

    # Run tests for each SUT. Appends True / False passed key
    # as well as run details to dict entry for specified SUT.
    def runTests(self):
        start = time.time()
        for name, sut in self.repo_info.iteritems():
            print "Running test for %s, version %s" % (sut.name, str(sut.version))
            sut_name = sut.name + '-' + str(sut.version)
            self.startBaseVM()
            self.modifyManifest(sut_name)
            test, details = IntegrationTest(self.admin, self.admin_pw, self.vmx_path).run()
            self.results['run'] += 1
            if not test:
                self.results['failed'] += 1
                self.results['details'][sut_name] = details
        #self.modifyManifest()
        self.results['runtime'] = (time.time() - start)

    # Show run details for SUTs that fail tests
    def showDetails(self):
        print "Finished in %.4f seconds" % (self.results['runtime'])
        print "%i tests, %i failures" % (self.results['run'], self.results['failed'])
        if self.results['details']:
            for sut, details in self.results['details'].iteritems():
                print "%s failed!" % (sut)
                print details

    # Returns True if all SUT's passed, False otherwise
    def didPass(self):
        return self.results['failed'] == 0

    def modifyManifest(self, sut=None):
        manifest_path                = os.path.join(self.repo_path, "manifests", TEST_MANIFEST)
        manifest                     = plistlib.readPlist(manifest_path)
        manifest['managed_installs'] = []
        if sut is not None:
            manifest['managed_installs'].append(sut)
        plistlib.writePlist(manifest, manifest_path)

    # Ensures VMWare Fusion is running, resets VM to Base snapshot, and starts VM
    def startBaseVM(self):
        # Ensure VM is ON
        subprocess.call([VMRUN_CMD, "start", self.vmx_path])
        # Revert to Base snapshot
        subprocess.call([VMRUN_CMD, "revertToSnapshot", self.vmx_path, "Base"])
        # Need to start again after reverting
        subprocess.call([VMRUN_CMD, "start", self.vmx_path])

    def stopVM(self):
        # Stop VM
        subprocess.call([VMRUN_CMD, "stop", self.vmx_path])

# Defines testing methods for running against SUT
class IntegrationTest:

    def __init__(self, admin, admin_pw, vmx_path):
        self.admin    = admin
        self.admin_pw = admin_pw 
        self.vmx_path = vmx_path

    def downloadSUT(self):
        subprocess.check_call([VMRUN_CMD, "-T", "fusion", "-gu", self.admin, "-gp", self.admin_pw, "runProgramInGuest", self.vmx_path, "/bin/bash", "-c", DL_CMD])
        #subprocess.check_call([VMRUN_CMD, "-T", "fusion", "-gu", self.admin, "-gp", self.admin_pw, "runProgramInGuest", self.vmx_path, "/bin/bash", "-c", "/usr/bin/touch /Users/mactechs/Desktop/hello_world.txt"])

    def installSUT(self):
        subprocess.check_call([VMRUN_CMD, "-T", "fusion", "-gu", self.admin, "-gp", self.admin_pw, "runProgramInGuest", self.vmx_path, "/bin/bash", "-c", INSTALL_CMD])

    def run(self):
        try:
            self.downloadSUT()
        except Exception as e:
            return False, str(e)
        try:
            self.installSUT()
        except Exception as e:
            return False, str(e)
        return True, None

# Defines SUT object for testing
class SUT:

    def __init__(self, pkginfo):
        self.path       = pkginfo
        self.pkginfo    = self.getpkginfo(pkginfo)
        self.name       = self.pkginfo.get("name")
        self.version    = self.pkginfo.get("version")
        self.update_for = self.pkginfo.get("update_for")

    def getpkginfo(self, path):
        return plistlib.readPlist(path)

def main():
    parser = argparse.ArgumentParser(
        description='Command line tool for testing the download and install of Munki packages from a specified repo.',
    )
    parser.add_argument('--repo', metavar='PATH', type=str, nargs=1, required=True,
        help='Path to munki repo to test.',
    )
    parser.add_argument('--vmx', metavar='PATH', type=str, nargs=1, required=True,
        help='Path to vmx file for VM to use for testing.',
    )
    parser.add_argument('--user', metavar='NAME', type=str, nargs=1, required=True,
        help='Shortname of user configured admin account on VM.',
    )
    parser.add_argument('--password', metavar='PASSWORD', type=str, nargs=1, required=True,
        help='Password for admin account on VM',
    )
    parser.add_argument('--only', metavar='SomePkg-x.x.x', type=str, nargs='+', 
        help='Optionally specify name-vers of pkgs to test.',
    )
    args = parser.parse_args()
    pkg_filter = args.only if args.only else None
    testrunner = TestRunner(args.repo[0], args.vmx[0], args.user[0], args.password[0], pkg_filter)
    testrunner.runTests()
    testrunner.showDetails()

if __name__ == "__main__":
    main()
