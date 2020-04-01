from setuptools import setup

setup(name='leica_microscope',
      version='1.0',
      description='Used to talk to a Leice microscope.',
      url='',
      author='Richard Gerum',
      author_email='richard.gerum@fau.de',
      license='MIT',
      packages=['leica_microscope'],
      install_requires=[
            "pyserial",
            "tifffile",
            "lucam",
            "configparser",
      ],
      include_package_data=True,
      zip_safe=False)
