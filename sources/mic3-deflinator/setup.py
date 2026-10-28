from setuptools import setup

setup(name='deflinator',
      version='1.0',
      description='To record the micro tissue devices',
      url='',
      author='Richard Gerum',
      author_email='richard.gerum@fau.de',
      packages=['deflinator'],
      install_requires=[
            "pyserial",
            "clickpoints",
      ],
      include_package_data=True,
      zip_safe=False)
