#-*-*- encoding: utf-8 -*-*-
from setuptools import setup

classifiers=[
    "Development Status :: 4 - Beta",
    "Environment :: Web Environment",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: BSD License",
    "Operating System :: OS Independent",
    "Programming Language :: Python",
    "Programming Language :: Python :: 2",
    "Programming Language :: Python :: 2.7",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.3",
    "Programming Language :: Python :: 3.4",
    "Programming Language :: Python :: 3.5",
    "Programming Language :: Python :: 3.6",
    "Topic :: Education",
    "Topic :: Internet :: WWW/HTTP",
    "Topic :: Software Development :: Libraries :: Application Frameworks",
]

cp_license="BSD 2-clause"

setup(name='weblablib',
      version='0.3',
      description="WebLab-Deusto library for creating unmanaged laboratories",
      classifiers=classifiers,
      author='WebLab-Deusto team',
      author_email='weblab@deusto.es',
      url='https://weblablib.readthedocs.io/en/stable/',
      license=cp_license,
      py_modules=['weblablib'],
      install_requires=['redis', 'flask>=0.12', 'six'],
     )
