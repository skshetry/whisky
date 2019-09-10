#!/usr/bin/env python
import pathlib

from setuptools import setup

from wsgi_server import __version__ as VERSION

# Package meta-data.
NAME = "whisky"
DESCRIPTION = "Multithreaded, WSGI-web server with zero dependencies."
URL = "https://github.com/skshetry/whisky"
AUTHOR = "skshetry"
REQUIRES_PYTHON = ">=3.6.0"


with pathlib.Path("README.md").open() as f:
    long_description = "\n" + f.read()

# Where the magic happens:
setup(
    name=NAME,
    version=VERSION,
    description=DESCRIPTION,
    long_description=long_description,
    long_description_content_type="text/markdown",
    author=AUTHOR,
    python_requires=REQUIRES_PYTHON,
    url=URL,
    py_modules=["wsgi_server"],
    entry_points={"console_scripts": ["whisky=wsgi_server:main"]},
    include_package_data=True,
    license="MIT",
    classifiers=[
        # Trove classifiers
        # Full list: https://pypi.python.org/pypi?%3Aaction=list_classifiers
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: PyPy",
    ],
)
