#!/usr/bin/env python

"""Setup script for the `executor` package."""

# Author: Peter Odding <peter@peterodding.com>
# Last Change: October 4, 2015
# URL: https://executor.readthedocs.org

# Standard library modules.
import codecs
import os
import re

# De-facto standard solution for Python packaging.
from setuptools import setup, find_packages

# Find the directory where the source distribution was unpacked.
source_directory = os.path.dirname(os.path.abspath(__file__))

# Find the current version.
module = os.path.join(source_directory, 'executor', '__init__.py')
for line in open(module, 'r'):
    match = re.match(r'^__version__\s*=\s*["\']([^"\']+)["\']$', line)
    if match:
        version_string = match.group(1)
        break
else:
    raise Exception("Failed to extract version from %s!" % module)

# Fill in the long description (for the benefit of PyPI)
# with the contents of README.rst (rendered by GitHub).
readme_file = os.path.join(source_directory, 'README.rst')
with codecs.open(readme_file, 'r', 'utf-8') as handle:
    readme_text = handle.read()

setup(name='executor',
      version=version_string,
      description='Programmer friendly subprocess wrapper',
      long_description=readme_text,
      url='https://executor.readthedocs.org',
      author='Peter Odding',
      author_email='peter@peterodding.com',
      packages=find_packages(),
      install_requires=[
          'humanfriendly >= 1.19',
          'property-manager >= 1.0',
      ],
      test_suite='executor.tests')
