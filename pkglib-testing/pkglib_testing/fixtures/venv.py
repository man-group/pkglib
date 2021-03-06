""" Python virtual environment fixtures
"""
import os
import subprocess
from distutils import sysconfig

from pytest import yield_fixture
from pkg_resources import working_set
from path import path
from pkglib_testing import CONFIG, coverage as cov

from .workspace import Workspace
from .. import util
from .util import requires_config


@requires_config(['virtualenv_executable'])
@yield_fixture(scope='function')
def virtualenv():
    """ Function-scoped virtualenv in a temporary workspace.
        Cleans up on exit.
    """
    with TmpVirtualEnv() as venv:
        yield venv


class PackageEntry(object):
    # TODO: base this off of Distribution or similar
    PACKAGE_TYPES = (ANY, DEV, SRC, REL) = ('ANY', 'DEV', 'SRC', 'REL')

    def __init__(self, name, version, source_path=None):
        self.name = name
        self.version = version
        self.source_path = source_path

    @property
    def issrc(self):
        return ("dev" in self.version and
                self.source_path is not None and
                not self.source_path.endswith(".egg"))

    @property
    def isrel(self):
        return not self.isdev

    @property
    def isdev(self):
        return ('dev' in self.version and
                (not self.source_path or self.source_path.endswith(".egg")))

    def match(self, package_type):
        if package_type is self.ANY:
                return True
        elif package_type is self.REL:
            if self.isrel:
                return True
        elif package_type is self.DEV:
            if self.isdev:
                return True
        elif package_type is self.SRC:
            if self.issrc:
                return True
        return False

class TmpVirtualEnv(Workspace):
    """
    Creates a virtualenv in a temporary workspace, cleans up on exit.

    Attributes
    ----------
    python : `str`
        path to the python exe
    virtualenv : `str`
        path to the virtualenv base dir
    env : 'list'
        environment variables used in creation of virtualenv

    """

    def __init__(self, env=None, workspace=None, name='.env', python=None):
        Workspace.__init__(self, workspace)
        self.virtualenv = self.workspace / name
        self.python = self.virtualenv / 'bin' / 'python'
        self.easy_install = self.virtualenv / "bin" / "easy_install"

        if env is None:
            self.env = dict(os.environ)
        else:
            self.env = dict(env)  # ensure we take a copy just in case there's some modification

        self.env['VIRTUAL_ENV'] = self.virtualenv
        self.env['PATH'] = os.path.dirname(self.python) + ((os.path.pathsep + self.env["PATH"])
                                                           if "PATH" in self.env else "")
        if 'PYTHONPATH' in self.env:
            del(self.env['PYTHONPATH'])

        virtualenv_cmd = CONFIG.virtualenv_executable
        self.run('%s -p %s %s --distribute' % (virtualenv_cmd,
                                               python or util.get_real_python_executable(),
                                               self.virtualenv))

    def run(self, *args, **kwargs):
        """
        Add our cleaned shell environment into any subprocess execution
        """
        if 'env' not in kwargs:
            kwargs['env'] = self.env
        return super(TmpVirtualEnv, self).run(*args, **kwargs)

    def run_with_coverage(self, *args, **kwargs):
        """
        Run a python script using coverage, run within this virtualenv.
        Assumes the coverage module is already installed.

        Parameters
        ----------
        args:
            Args passed into `pkglib_testing.pytest.coverage.run_with_coverage`
        kwargs:
            Keyword arguments to pass to `pkglib_testing.pytest.coverage.run_with_coverage`
        """
        if 'env' not in kwargs:
            kwargs['env'] = self.env
        coverage = [self.python, '%s/bin/coverage' % self.virtualenv]
        return cov.run_with_coverage(*args, coverage=coverage, **kwargs)

    def install_package(self, pkg_name, installer='pyinstall', build_egg=None):
        """
        Install a given package name. If it's already setup in the
        test runtime environment, it will use that.
        :param build_egg:  `bool`
            Only used when the package is installed as a source checkout, otherwise it
            runs the installer to get it from AHLPyPI
            True: builds an egg and installs it
            False: Runs 'python setup.py develop'
            None (default): installs the egg if available in dist/, otherwise develops it
        """
        installed = [p for p in working_set if p.project_name == pkg_name]
        if not installed or installed[0].location.endswith('.egg'):
            installer = os.path.join(self.virtualenv, 'bin', installer)
            if not self.debug:
                installer += ' -q'
            # Note we're running this as 'python easy_install foobar', instead of 'easy_install foobar'
            # This is to circumvent #! line length limits :(
            cmd = '%s %s %s' % (self.python, installer, pkg_name)
        else:
            pkg = installed[0]
            d = {'python': self.python,
                 'easy_install': self.easy_install,
                 'src_dir': pkg.location,
                 'name': pkg.project_name,
                 'version': pkg.version,
                 'pyversion': sysconfig.get_python_version(),
                 }

            d['egg_file'] = path(pkg.location) / 'dist' / ('%(name)s-%(version)s-py%(pyversion)s.egg' % d)
            if build_egg and not d['egg_file'].isfile():
                self.run('cd %(src_dir)s; %(python)s setup.py -q bdist_egg' % d, capture=True)

            if build_egg or (build_egg is None and d['egg_file'].isfile()):
                cmd = '%(python)s %(easy_install)s %(egg_file)s' % d
            else:
                cmd = 'cd %(src_dir)s; %(python)s setup.py -q develop' % d

        self.run(cmd, capture=True)

    def installed_packages(self, package_type=None):
        """
        Return a package dict with
            key = package name, value = version (or '')
        """
        if package_type is None:
            package_type = PackageEntry.ANY
        elif package_type not in PackageEntry.PACKAGE_TYPES:
            raise ValueError('invalid package_type parameter (%s)' % str(package_type))

        res = {}
        code = "from pkg_resources import working_set\n"\
               "for i in working_set: print(i.project_name + ' ' + i.version + ' ' + i.location)"
        lines = self.run('%s -c "%s"' % (self.python, code), capture=True).split('\n')
        for line in [i.strip() for i in lines if i.strip()]:
            name, version, location = line.split()
            res[name] = PackageEntry(name, version, location)
        return res

    def popen(self, cmd, **kwds):
        kwds = dict(kwds)
        kwds.setdefault("stdout", subprocess.PIPE)
        return subprocess.Popen(cmd, **kwds).stdout

    def dependencies(self, package_name, package_type=None):  # @UnusedVariable
        """
        Find the dependencies of a given package.

        Parameters
        ----------
        package_name: `str`
            Name of package
        package_type: `str`
            Filter results on package type

        Returns
        --------
        dependencies: `dict`
            Key is name, value is PackageEntries
        """
        if package_type is None:
            package_type = PackageEntry.ANY
        elif package_type not in (PackageEntry.DEV, PackageEntry.REL):
            raise ValueError('invalid package_type parameter for dependencies (%s)' % str(package_type))

        res = {}
        code = "from pkglib.setuptools.dependency import get_all_requirements; " \
               "for i in get_all_requirements(['%s']): " \
               "  print(i.project_name + ' ' + i.version + ' ' + i.location)"
        lines = self.run('%s -c "%s"' % (self.python, code), capture=True).split('\n')
        for line in [i.strip() for i in lines if i.strip()]:
            name, version, location = line.split()
            entry = PackageEntry(name, version, location)
            if entry.match(package_type):
                res[name] = entry
        return res
