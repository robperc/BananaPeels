#!/usr/bin/python

import argparse
import fnmatch
import glob
import os
import plistlib
import subprocess
import time
import random

from collections import OrderedDict
from distutils.version import LooseVersion

TEST_MANIFEST   = "test_munki_client"
VMRUN_CMD       = "/Applications/VMware Fusion.app/Contents/Library/vmrun"
DL_CMD          = "sudo /usr/local/munki/managedsoftwareupdate -v"
INSTALL_CMD     = "sudo /usr/local/munki/managedsoftwareupdate --installonly"
GUEST_ERROR_LOG = "/Library/Managed Installs/Logs/errors.log"
CHECK_FILE      = "/tmp/installcheck_bananas.log"
CHECK_CMD       = DL_CMD + " > " + CHECK_FILE
GREP_CMD        = "grep -c 'The following items will be installed or upgraded' " + CHECK_FILE

# Defines class for gathering PkgInfos
class PkgsInfoDict(object):
	"""Parses the pkginfos in the munki repo at the specified path into an ordered dictionary (name: [versions]).

	Attributes:
		repo_path (str): Path to munki repo to parse.
		repo_info (OrderedDict): Ordered dictionary containing pkginfos of input repo in {name: [versions]} form.

	"""

	def __init__(self, repo_path):
		self.repo_path = repo_path
		self.repo_info = self.generate()

	def generate(self):
		"""Parse pkginfos of munki repo into dictionary.

		Returns:
			Ordered dictionary containing pkginfos of input repo in {name: [versions]} form.
		"""
		repo_dict = dict()
		info_dir  = os.path.join(self.repo_path, "pkgsinfo")
		pkginfos  = []
		for root, dirnames, filenames in os.walk(info_dir):
			for filename in filenames:
				if filename.endswith(('.pkginfo', '.plist')):
					pkginfos.append(os.path.join(root, filename))
		for pkginfo in pkginfos:
			info = PkgInfo(pkginfo)
			if info.name is None or info.version is None:
				print "%s is missing it's name or version" % pkginfo
				print "Skipping"
				continue
			if repo_dict.get(info.name) is None:
				repo_dict[info.name] = OrderedDict()
			if repo_dict[info.name].get(info.version) is None:
				repo_dict[info.name][info.version] = info
			else:
				print "WARNING: there appears to be duplicate pkginfos for %s version %s." % (info.name, info.version)
				print ' - ' + info.path
				print ' - ' + repo_dict[info.name][info.version].path
				print
		return OrderedDict(sorted(repo_dict.items(),key=lambda t: t[0]))

	def filter(self, mode, filters=None):
		"""Filters repo_info dictionary for items matching specified filter
		
		Args:
			filters (Optional[list(str,...)]): List of pkginfo names to filter out of pkginfo dict.
											   Defaults to None.
		Returns:
			Ordered dictionary containing pkginfos of input repo in {name: [versions]} form.
		"""
		infos = list()
		# if mode is 'all' return all pkginfos in munki repo
		if mode == 'all':
			for name, versions in self.repo_info.iteritems():
			for version in versions.keys():
				infos.append(self.repo_info[name][version])
		# if mode is 'only' name-vers filters are specified then return 
		# pkginfos that conform to filter
		elif mode == 'only' and filters is not None:
			for fil in filters:
				if len(fil.split('-')) == 1:
					name = fil
					version = None
				elif len(fil.split('-')) == 2:
					name, version = fil.split('-')
				else:
					continue
				if self.repo_info.get(name) is not None:
					if self.repo_info[name].get(version) is None:
						version = sorted(self.repo_info[name].keys(), key=LooseVersion)[-1]
					infos.append(self.repo_info[name][version])
		# if no mode specified or only mode specified with no filters
		# then only return latest
		else:
			for name, versions in self.repo_info.iteritems():
				latest = sorted(versions.keys(), key=LooseVersion)[-1]
				infos.append(self.repo_info[name][latest])
		return infos

	def __str__(self):
		ret_str = """"""
		for a, b in self.repo_info.iteritems():
			ret_str += a + "\n"
			for c in b.keys():
				ret_str += ' - ' + c + '\n'
		return ret_str

# Handles the running of the tests for the specified pkginfos it is provided
class TestRunner(object):

	def __init__(self, repo_path, suts, vmx_path, snapshot, admin, admin_pw):
		self.repo_path = repo_path
		self.suts      = list(suts)
		self.vmx_path  = vmx_path
		self.snapshot  = snapshot
		self.admin     = admin
		self.admin_pw  = admin_pw
		self.results   = dict(runtime=0.0, run=0, failed=0, details=dict())

	# Run tests for each SUT. Appends True / False passed key
	# as well as run details to dict entry for specified SUT.
	def runTests(self):
		start = time.time()
		for sut in self.suts:
			print "Running test for %s, version %s" % (sut.name, str(sut.version))
			sut_name = sut.name + '-' + str(sut.version)
			self.startVM()
			self.modifyManifest(sut_name)
			time.sleep(3) # allow network interfaces to "wake up"
			# Right now only looks at first installs item
			# Need to un-shittify this
			if sut.installs_app is not None:
				path = sut.installs_app
				test, details = AppInstallTest(self.admin, self.admin_pw, self.vmx_path, self.snapshot, path).run()
			else:
				test, details = BaseTest(self.admin, self.admin_pw, self.vmx_path).run()
			self.results['run'] += 1
			if not test:
				self.results['failed'] += 1
				self.results['details'][sut_name] = details
		self.modifyManifest()
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

	# Ensures VMWare Fusion is running, resets VM to specified snapshot, and starts VM
	def startVM(self):
		# Ensure VM is ON
		subprocess.call([VMRUN_CMD, "start", self.vmx_path])
		# Revert to snapshot
		subprocess.call([VMRUN_CMD, "revertToSnapshot", self.vmx_path, self.snapshot])
		# Need to start again after reverting
		subprocess.call([VMRUN_CMD, "start", self.vmx_path])

	def stopVM(self):
		# Stop VM
		subprocess.call([VMRUN_CMD, "stop", self.vmx_path])

# Defines testing methods for running against SUT
class BaseTest(object):

	def __init__(self, admin, admin_pw, vmx_path):
		self.admin    = admin
		self.admin_pw = admin_pw 
		self.vmx_path = vmx_path

	# Prompts Munki to check for updates on guest VM. Throws exception if exit code is not 0
	def downloadSUT(self):
		subprocess.check_call([VMRUN_CMD, "-T", "fusion", "-gu", self.admin, "-gp", self.admin_pw, "runProgramInGuest", self.vmx_path, "/bin/bash", "-c", DL_CMD])
	
	# Prompts Munki to install updates on guest VM. Throws exception if exit code is not 0.
	def installSUT(self):
		subprocess.check_call([VMRUN_CMD, "-T", "fusion", "-gu", self.admin, "-gp", self.admin_pw, "runProgramInGuest", self.vmx_path, "/bin/bash", "-c", INSTALL_CMD])

	# Checks to ensure SUT and it's dependencies all installcheck properly.
	# Returns True if installchecks find SUT and dependencies, False otherwise.
	def installCheckSUT(self):
		subprocess.call([VMRUN_CMD, "-T", "fusion", "-gu", self.admin, "-gp", self.admin_pw, "runProgramInGuest", self.vmx_path, "/bin/bash", "-c", CHECK_CMD])
		subprocess.call([VMRUN_CMD, "-T", "fusion", "-gu", self.admin, "-gp", self.admin_pw, "copyFileFromGuestToHost", self.vmx_path, CHECK_FILE, "/tmp/installcheck_peels.log"])
		p = subprocess.Popen(["grep", "-c", "The following items will be installed or upgraded", "/tmp/installcheck_peels.log"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		out, err = p.communicate()
		return int(out) == 0

	# Copies Munki error log from guest VM to host and returns most recently appended line.
	def getError(self):
		subprocess.call([VMRUN_CMD, "-T", "fusion", "-gu", self.admin, "-gp", self.admin_pw, "copyFileFromGuestToHost", self.vmx_path, GUEST_ERROR_LOG, "/tmp/errors_peels.log"])
		p = subprocess.Popen(["tail", "-n1", "/tmp/errors_peels.log"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		out, err = p.communicate()
		out = str(out.split('ERROR: ')[1])
		return out

	# Runs test methods in proper order. If encounters exception in any of the test methods
	# then returns test failure and the log message corresponding to the error that caused
	# the exception.
	def run(self):
		try:
			self.downloadSUT()
		except Exception as e:
			return False, self.getError()
		try:
			self.installSUT()
		except Exception as e:
			return False, self.getError()
		if not self.installCheckSUT():
			return False, "Confirm installcheck is configured properly."
		return True, None

class AppInstallTest(BaseTest):

	def __init__(self, admin, admin_pw, vmx_path, snapshot, app_path):
		self.admin    = admin
		self.admin_pw = admin_pw 
		self.vmx_path = vmx_path
		self.snapshot = snapshot
		self.app_path = app_path

	def appDoesOpen(self):
		exit_code = subprocess.call([VMRUN_CMD, "-T", "fusion", "-gu", self.admin, "-gp", self.admin_pw, "runProgramInGuest", self.vmx_path, "/bin/bash", "-c", "/usr/bin/open " + self.app_path.replace(" ", "\ ")])
		return int(exit_code) == 0

	# Runs test methods in proper order. If encounters exception in any of the test methods
	# then returns test failure and the log message corresponding to the error that caused
	# the exception.
	def run(self):
		try:
			self.downloadSUT()
		except Exception as e:
			return False, self.getError()
		try:
			self.installSUT()
		except Exception as e:
			return False, self.getError()
		if not self.installCheckSUT():
			return False, "Confirm installcheck is configured properly."
		if not self.appDoesOpen():
			return False, "App failed to open."
		return True, None

# Defines PkgInfo object
class PkgInfo(object):

	def __init__(self, pkginfo):
		self.path         = pkginfo
		self.pkginfo      = self.getpkginfo(pkginfo)
		self.name         = self.pkginfo.get("name")
		self.version      = self.pkginfo.get("version")
		self.update_for   = self.pkginfo.get("update_for")
		self.installs_app = self.getAppInstall()

	# Read specified pkginfo or plist into a python-parseable dictionary
	def getpkginfo(self, path):
		return plistlib.readPlist(path)

	# If pkginfo has an application item in its install array return the path to the first one found
	# Otherwise return None
	def getAppInstall(self):
		installs = self.pkginfo.get("installs")
		if installs is not None:
			for install in installs:
				if install.get("type") == 'application':
					return install["path"]
		return None


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
	parser.add_argument('--snapshot', metavar='TITLE', type=str, nargs=1, required=True,
		help='Title of VM snapshot to use for testing.',
	)
	parser.add_argument('--user', metavar='NAME', type=str, nargs=1, required=True,
		help='Shortname for admin account on VM.',
	)
	parser.add_argument('--password', metavar='PASSWORD', type=str, nargs=1, required=True,
		help='Password for admin account on VM.',
	)
	parser.add_argument('--only', metavar='SomePkg-x.x.x', type=str, nargs='+', 
		help='Optionally specify name-version of pkgs to test. If no version specified defaults to latest. Packages specified by only will be tested individually.',
	)
	args = parser.parse_args()
	info = PkgsInfoDict(args.repo[0])
	if args.only:
		SUTs = info.filter('only', args.only)
	else:
		SUTs = info.filter('all')
	testrunner = TestRunner(args.repo[0], SUTs, args.vmx[0], args.snapshot[0], args.user[0], args.password[0])
	testrunner.runTests()
	testrunner.showDetails()

if __name__ == "__main__":
	main()
