from setuptools import setup

setup(name='gridviewer',
      version='1.0',
      description='Used to display microscope stacks and grids.',
      url='https://bitbucket.org/fabry_biophysics/gridviewer',
      author='Richard Gerum',
      author_email='richard.gerum@fau.de',
      license='MIT',
      packages=['gridviewer'],
      entry_points = {
              'console_scripts': ['gridviewer=gridviewer.GridViewerLauncher:main', 'gridviewerbooster=gridviewer.GridViewerBooster:main'],
              'gui_scripts': ['gridviewer_noconsole=gridviewer.GridViewerLauncher:main'],
          },
      install_requires=[
          'qtpy',
          'tifffile',
          'imageio',
          'natsort',
          'qimage2ndarray',
          'configparser'
      ],
      include_package_data=True,
      zip_safe=False)
