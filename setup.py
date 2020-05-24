#-*-*- encoding: utf-8 -*-*-
from setuptools import setup
from collections import OrderedDict

classifiers=[
    "Development Status :: 4 - Beta",
    "Environment :: Web Environment",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: GNU Affero General Public License v3",
    "Operating System :: OS Independent",
    "Programming Language :: Python",
    "Programming Language :: Python :: 2",
    "Programming Language :: Python :: 2.7",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.6",
    "Programming Language :: Python :: 3.7",
    "Topic :: Education",
    "Topic :: Internet :: WWW/HTTP",
    "Topic :: Software Development :: Libraries :: Application Frameworks",
]

cp_license="GNU AGPL v3"

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(name='weblablib',
      version='0.5.6',
      description="WebLab-Deusto library for creating unmanaged laboratories",
      long_description=long_description,
      long_description_content_type="text/markdown",
      project_urls=OrderedDict((
            ('Documentation', 'https://developers.labsland.com/weblablib/en/stable/'),
            ('Code', 'https://github.com/weblabdeusto/weblablib'),
            ('Issue tracker', 'https://github.com/weblabdeusto/weblablib/issues'),
      )),
      classifiers=classifiers,
      zip_safe=False,
      author='LabsLand',
      author_email='dev@labsland.com',
      url='https://developers.labsland.com/weblablib/',
      license=cp_license,
      packages=['weblablib', 'weblablib.backends'],
      install_requires=['redis', 'flask', 'six', 'requests'],
     )
