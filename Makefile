# Makefile for executor.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: November 8, 2015
# URL: https://github.com/xolox/python-executor

WORKON_HOME ?= $(HOME)/.virtualenvs
VIRTUAL_ENV ?= $(WORKON_HOME)/executor
PYTHON = "$(VIRTUAL_ENV)/bin/python"
ACTIVATE = . "$(VIRTUAL_ENV)/bin/activate"
MAKE := $(MAKE) --no-print-directory
SHELL = bash

default:
	@echo 'Makefile for executor'
	@echo
	@echo 'Usage:'
	@echo
	@echo '    make install    install the package in a virtual environment'
	@echo '    make reset      recreate the virtual environment'
	@echo '    make test       run the test suite'
	@echo '    make coverage   run the tests, report coverage'
	@echo '    make check      check the coding style'
	@echo '    make docs       update documentation using Sphinx'
	@echo '    make publish    publish changes to GitHub/PyPI'
	@echo '    make clean      cleanup all temporary files'
	@echo

install:
	@ $(MAKE) install_command PROGRAM=python COMMAND="virtualenv $(VIRTUAL_ENV)"
	@ $(MAKE) install_command PROGRAM=pip COMMAND="easy_install pip"
	@ $(MAKE) install_command PROGRAM=pip-accel COMMAND="pip install --quiet pip-accel"
	@ $(MAKE) is_installed &> /dev/null || $(MAKE) --no-print-directory editable

install_command:
	@ test -x "$(VIRTUAL_ENV)/bin/$(PROGRAM)" || $(MAKE) run_command COMMAND="$(COMMAND)"

is_installed:
	$(ACTIVATE) && $(PYTHON) -c "import executor, pkg_resources; pkg_resources.get_distribution('executor')"

editable:
	- $(ACTIVATE) && pip uninstall --quiet --yes executor &>/dev/null
	pip-accel install --quiet --editable "$(PWD)"

run_command:
	$(ACTIVATE) && $(COMMAND)

dependency:
	@ $(MAKE) install_command PROGRAM=$(PROGRAM) COMMAND="pip-accel install --quiet $(PACKAGE)"

reset:
	rm -Rf "$(VIRTUAL_ENV)"
	$(MAKE) clean

test: install
	@ $(MAKE) dependency PROGRAM=detox PACKAGE=detox
	@ if ! sudo -n true &> /dev/null; then sudo -p "Please enable password-less sudo under detox: " true; fi
	@ $(ACTIVATE) && time detox

coverage: install
	@ $(MAKE) dependency PROGRAM=coverage PACKAGE=coverage
	$(ACTIVATE) && coverage run setup.py test
	$(ACTIVATE) && coverage report
	$(ACTIVATE) && coverage html

check: install
	@ $(MAKE) dependency PROGRAM=flake8 PACKAGE=flake8-pep257
	$(ACTIVATE) && flake8

docs: install
	@ $(MAKE) dependency PROGRAM=sphinx-build PACKAGE=sphinx
	@ $(ACTIVATE) && cd docs && sphinx-build -b html -d build/doctrees . build/html

publish:
	git push origin && git push --tags origin
	$(MAKE) clean && $(PYTHON) setup.py sdist upload

clean:
	@- rm -Rf *.egg *.egg-info .cache .coverage .tox build dist docs/build htmlcov
	@- find -depth -type d -name __pycache__ -exec rm -Rf {} \;
	@- find -type f -name '*.pyc' -delete
	@ $(MAKE) install

.PHONY: default install install_command is_installed editable run_command dependency reset test coverage check docs publish clean
