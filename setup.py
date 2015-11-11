import os
from setuptools import setup

# Utility function to read the README file.
# Used for the long_description.  It's nice, because now 1) we have a top level
# README file and 2) it's easier to type in the README file than to put a raw
# string in below ...
def read(fname):
    print os.path.join(os.path.dirname(__file__), fname)
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

setup(
    name = "dlt-tools",
    version = "0.1.dev",
    author = "Prakash",
    author_email = "prakraja@umail.iu.edu",
    description = ("DLT tools - basically a landsat listener and downloader"),
    license = "BSD",
    keywords = "dlt tools",
    url = "https://github.com/datalogistics/dlt-misc",
    packages=['tools'],
    package_data={'tools' : ['*']},
    long_description=read("README.txt"),
    include_package_data = True,
    install_requires=[
        "websocket-client>=0.34",
        "requests",
        "six>=1.10.0"
    ],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Topic :: Utilities",
        "License :: OSI Approved :: BSD License",
        ],
    entry_points = {
        'console_scripts': [
            'eodn_feed = tools.eodn_feed:main',
            'landsat_download = tools.downloader:main',
        ]
    }
)
    

