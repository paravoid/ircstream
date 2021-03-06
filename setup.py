#!/usr/bin/env python3
"""Package configuration."""

import setuptools  # type: ignore


def get_long_description() -> str:
    """Fetch the long description from README.md."""
    with open("README.md", "r") as readme:
        return readme.read()


def get_version() -> str:
    """Fetch the version from the __version__ string in the code.

    To be replaced by importlib.metadata when we move to Python 3.8 (PEP 566).
    """
    with open("ircstream.py", "r") as code:
        for line in code.readlines():
            if line.startswith("__version__"):
                delim = '"' if '"' in line else "'"
                return line.split(delim)[1]
        raise RuntimeError("Unable to find version string.")


setuptools.setup(
    name="ircstream",
    version=get_version(),
    long_description=get_long_description(),
    long_description_content_type="text/markdown",
    py_modules=["ircstream"],
    maintainer="Faidon Liambotis",
    maintainer_email="faidon@wikimedia.org",
    description="MediaWiki RC->IRC gateway",
    url="https://github.com/wikimedia/ircstream",
    license="Apache2",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
        "Intended Audience :: System Administrators",
    ],
    keywords=["irc", "mediawiki", "wikimedia"],
    python_requires=">=3.7",
    # fmt: off
    install_requires=[
        "prometheus_client",
        "structlog",
    ],
    entry_points={
        "console_scripts": [
            "ircstream = ircstream:main",
        ],
    },
    # fmt: on
    zip_safe=False,
)
