from setuptools import setup

setup(name='microscopehandler',
      version='1.0',
      description='Used to talk to a Leice microscope and a Hamamatsu Camera.',
      url='https://bitbucket.org/fabry_biophysics/microscopehandler',
      author='Richard Gerum',
      author_email='richard.gerum@fau.de',
      license='MIT',
      packages=['microscopehandler', 'microscopehandler.Flask', 'microscopehandler.includes'],
      entry_points = {
              'console_scripts': ['camera_server=microscopehandler.CameraServer:main',
                                  'microscope_server=microscopehandler.MicroscopeServer:main',
                                  'microscope_console=microscopehandler.MicroscopeConsole:main',
                                  'memmap_clear=microscopehandler.CleanMemmaps:main'],
              'gui_scripts': ['camera_server_noconsole=microscopehandler.CameraServer:main',
                              'microscope_server_noconsole=microscopehandler.MicroscopeServer:main',
                              'microscope_memmap=microscopehandler.MicroscopeMemmapViewer:main',
                              'camera_memmap=microscopehandler.CameraMemmapViewer:main'],
          },
      install_requires=[
          'qtpy',
          'tifffile',
          'imageio',
          'natsort',
          'qimage2ndarray',
          'configparser',
          'pyserial'
      ],
      include_package_data=True,
      zip_safe=False)
