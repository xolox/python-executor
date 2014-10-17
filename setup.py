#!/usr/bin/env python

# Setup script for the `executor' package.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: October 17, 2014
# URL: https://executor.readthedocs.org

import os, sys
from setuptools import setup, find_packages

# Find the directory where the source distribution was unpacked.
source_directory = os.path.dirname(os.path.abspath(__file__))

# Add the directory with the source distribution to the search path.
sys.path.append(source_directory)

# Import the module to find the version number (this is safe because we don't
# have any external dependencies).
from executor import __version__ as version_string

# Fill in the long description (for the benefit of PyPi)
# with the contents of README.rst (rendered by GitHub).
readme_file = os.path.join(source_directory, 'README.rst')
readme_text = open(readme_file, 'r').read()

setup(name='executor',
      version=version_string,
      description='Programmer friendly subprocess wrapper',
      long_description=readme_text,
      url='https://executor.readthedocs.org',
      author='Peter Odding',
      author_email='peter@peterodding.com',
      packages=find_packages(),
      test_suite='executor.tests')
