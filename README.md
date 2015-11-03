# BananaPeels
A framework for testing the deployement of packages via Munki wrapped in a CLI tool. Requires VMWare Fusion.
Note: This is very early on in dev. Pull requests are welcome.

##Requires:
- VMWare Fusion
- Pre-made and configured OS X VM
- Configured Munki repo to serve packages
- test_munki_client manifest in manifests directory

##VM Configuration:
- Create an OS X VM with a test admin account (don't use a sensitive account name or password for this VM- the password must be specified in plaintext to communicate with vmrun)
- Stop Munki from attempting hourly runs in VM (we'll be running Munki manually and hourly runs can cause error when running tests)
```
sudo /bin/launchctl unload -w /Library/LaunchDaemons/com.googlecode.munki.managedsoftwareupdate-check.plist
```
- Install Munki and VMWare Tools to VM
- Configure VM client Munki to fetch from your Munki repo
- Configure VM client Munki to subscribe to test_munki_client manifest
- Add your admin account to sudoers file in VM
```
sudo visudo
# User privilege specification
...
root            ALL=(ALL) ALL
YOUR_ADMIN_USER ALL=(ALL) NOPASSWD: ALL
...
```
- Take snapshot of VM titled "Base"

##Details:
BananaPeels is a framework for testing the deployement of packages via Munki wrapped up in a CLI for ease-of-use. BananaPeels works by using a baseline OS X VM snapshot as a fixture to download and install specified packages to via Munki. Any failures or errors in the download or install process are logged and returned to the user at the conclusion of the sequence of tests.
Default behavior is to search the specified repo for all valid .pkginfo and .plist files and attempt to deploy the configured package for each to the VM test environment. If name-version pairs are provided via the optional "--only" argument then only packages found in the repo corresponding to those name-version pairs will be deployed. 

##Usage:
```
python BananaPeels.py -h
usage: BananaPeels.py [-h] --repo PATH --vmx PATH --user NAME --password
                      PASSWORD [--only SomePkg-x.x.x [SomePkg-x.x.x ...]]

Command line tool for testing the download and install of Munki packages from
a specified repo.

optional arguments:
  -h, --help            show this help message and exit
  --repo PATH           Path to munki repo to test.
  --vmx PATH            Path to vmx file for VM.
  --user NAME           Shortname for admin account on VM.
  --password PASSWORD   Password for admin account on VM
  --only SomePkg-x.x.x [SomePkg-x.x.x ...]
                        Optionally specify name-version of packages to test.
```
