from __future__ import print_function
import os

import pytest

from pkglib_testing.util import PkgTemplate
from pkglib_testing.pytest.jenkins_server import jenkins_server  # @UnusedImport # NOQA
HERE = os.getcwd()


@pytest.mark.jenkins
def test_jenkins_create(pytestconfig, jenkins_server):
    """ Creates template, creates the jenkins job
    """
    name = 'acme.projecttemplate.test'
    try:
        with PkgTemplate(name=name) as pkg:
            pkg.install_package('pytest-cov')
            print(pkg.run_with_coverage(['%s/setup.py' % pkg.trunk_dir,
                                         'jenkins', '--vcs-url=foo',
                                         '--no-prompt',
                                         '--server', jenkins_server.uri,
                                         '--user', 'foo',
                                         '--password', 'bar'],
                                        pytestconfig, cd=HERE))
        info = jenkins_server.api.get_job_info(name)
        assert info['name'] == name
    finally:
        try:
            jenkins_server.api.delete_job(name)
        except:
            pass


@pytest.mark.jenkins
def test_jenkins_update(pytestconfig, jenkins_server):
    """ Creates template, creates the hudson job, and runs the command again
    to do an update
    """
    name = 'acme.projecttemplate.test'
    try:
        with PkgTemplate(name=name) as pkg:
            pkg.install_package('pytest-cov')

            jenkins_cmd = ['%s/setup.py' % pkg.trunk_dir, 'jenkins',
                           '--vcs-url=foo',
                           '--no-prompt', '--server', jenkins_server.uri,
                           '--user', 'foo', '--password', 'bar']

            print(pkg.run_with_coverage(jenkins_cmd, pytestconfig, cd=HERE))
            print(pkg.run_with_coverage(jenkins_cmd, pytestconfig, cd=HERE))

        info = jenkins_server.api.get_job_info(name)
        assert info['name'] == name
    finally:
        try:
            jenkins_server.api.delete_job(name)
        except:
            pass
