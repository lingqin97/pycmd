#!/usr/bin/env python

from __future__ import print_function
from __future__ import division
from __future__ import absolute_import

from distutils import sysconfig
from shutil import rmtree
import errno
import multiprocessing
import os
import os.path as p
import platform
import re
import shlex
import subprocess
import sys
import traceback

PY_MAJOR, PY_MINOR = sys.version_info[ 0 : 2 ]
if not ( ( PY_MAJOR == 2 and PY_MINOR >= 6 ) or
         ( PY_MAJOR == 3 and PY_MINOR >= 3 ) or
         PY_MAJOR > 3 ):
  sys.exit( 'ycmd requires Python >= 2.6 or >= 3.3; '
            'your version of Python is ' + sys.version )

DIR_OF_THIS_SCRIPT = p.dirname( p.abspath( __file__ ) )
DIR_OF_THIRD_PARTY = p.join( DIR_OF_THIS_SCRIPT, 'third_party' )

# for folder in os.listdir( DIR_OF_THIRD_PARTY ):
#   abs_folder_path = p.join( DIR_OF_THIRD_PARTY, folder )
#   if p.isdir( abs_folder_path ) and not os.listdir( abs_folder_path ):
#     sys.exit( 'Some folders in ' + DIR_OF_THIRD_PARTY + ' are empty; '
#               'you probably forgot to run:'
#               '\n\tgit submodule update --init --recursive\n\n' )

# sys.path.insert( 1, p.abspath( p.join( DIR_OF_THIRD_PARTY, 'argparse' ) ) )

import argparse

NO_DYNAMIC_PYTHON_ERROR = (
  'ERROR: found static Python library ({library}) but a dynamic one is '
  'required. You must use a Python compiled with the {flag} flag. '
  'If using pyenv, you need to run the command:\n'
  '  export PYTHON_CONFIGURE_OPTS="{flag}"\n'
  'before installing a Python version.' )
NO_PYTHON_LIBRARY_ERROR = 'ERROR: unable to find an appropriate Python library.'

# Regular expressions used to find static and dynamic Python libraries.
# Notes:
#  - Python 3 library name may have an 'm' suffix on Unix platforms, for
#    instance libpython3.3m.so;
#  - the linker name (the soname without the version) does not always
#    exist so we look for the versioned names too;
#  - on Windows, the .lib extension is used instead of the .dll one. See
#    http://xenophilia.org/winvunix.html to understand why.
STATIC_PYTHON_LIBRARY_REGEX = '^libpython{major}\.{minor}m?\.a$'
DYNAMIC_PYTHON_LIBRARY_REGEX = """
  ^(?:
  # Linux, BSD
  libpython{major}\.{minor}m?\.so(\.\d+)*|
  # OS X
  libpython{major}\.{minor}m?\.dylib|
  # Windows
  python{major}{minor}\.lib
  )$
"""


def OnMac():
  return platform.system() == 'Darwin'


def OnWindows():
  return platform.system() == 'Windows'


def OnTravisOrAppVeyor():
  return 'CI' in os.environ


# On Windows, distutils.spawn.find_executable only works for .exe files
# but .bat and .cmd files are also executables, so we use our own
# implementation.
def FindExecutable( executable ):
  # Executable extensions used on Windows
  WIN_EXECUTABLE_EXTS = [ '.exe', '.bat', '.cmd' ]

  paths = os.environ[ 'PATH' ].split( os.pathsep )
  base, extension = os.path.splitext( executable )

  if OnWindows() and extension.lower() not in WIN_EXECUTABLE_EXTS:
    extensions = WIN_EXECUTABLE_EXTS
  else:
    extensions = ['']

  for extension in extensions:
    executable_name = executable + extension
    if not os.path.isfile( executable_name ):
      for path in paths:
        executable_path = os.path.join(path, executable_name )
        if os.path.isfile( executable_path ):
          return executable_path
    else:
      return executable_name
  return None


def PathToFirstExistingExecutable( executable_name_list ):
  for executable_name in executable_name_list:
    path = FindExecutable( executable_name )
    if path:
      return path
  return None


def NumCores():
  ycm_cores = os.environ.get( 'YCM_CORES' )
  if ycm_cores:
    return int( ycm_cores )
  try:
    return multiprocessing.cpu_count()
  except NotImplementedError:
    return 1


# Shamelessly stolen from https://gist.github.com/edufelipe/1027906
def CheckOutput( *popen_args, **kwargs ):
  """Run command with arguments and return its output as a byte string.
  Backported from Python 2.7."""

  process = subprocess.Popen( stdout=subprocess.PIPE, *popen_args, **kwargs )
  output, unused_err = process.communicate()
  retcode = process.poll()
  if retcode:
    command = kwargs.get( 'args' )
    if command is None:
      command = popen_args[ 0 ]
    error = subprocess.CalledProcessError( retcode, command )
    error.output = output
    raise error
  return output


def CustomPythonCmakeArgs():
  # The CMake 'FindPythonLibs' Module does not work properly.
  # So we are forced to do its job for it.
  print( 'Searching Python {major}.{minor} libraries...'.format(
    major = PY_MAJOR, minor = PY_MINOR ) )

  python_library, python_include = ['/usr/lib/python2.7/config/libpython2.7.so', '/usr/include/python2.7']
  print([python_library, python_include])

  print( 'Found Python library: {0}'.format( python_library ) )
  print( 'Found Python headers folder: {0}'.format( python_include ) )

  return [
    '-DPYTHON_LIBRARY={0}'.format( python_library ),
    '-DPYTHON_INCLUDE_DIR={0}'.format( python_include )
  ]


def GetCmakeArgs( ):
  cmake_args = []

  # cmake_args.append( '-DUSE_CLANG_COMPLETER=ON' )
  cmake_args.append( '-DUSE_SYSTEM_LIBCLANG=ON' )
  cmake_args.append( '-DUSE_SYSTEM_BOOST=ON' )
  cmake_args.append( '-DUSE_PYTHON2=ON'  )

  extra_cmake_args = os.environ.get( 'EXTRA_CMAKE_ARGS', '' )
  # We use shlex split to properly parse quoted CMake arguments.
  cmake_args.extend( shlex.split( extra_cmake_args ) )
  return cmake_args


def BuildYcmdLib(  ):
  if not os.path.exists('ycm_build'):
    os.mkdir('ycm_build' )

  try:
    full_cmake_args = [ '-G', 'Unix Makefiles' ]
    full_cmake_args.extend( CustomPythonCmakeArgs() )
    full_cmake_args.extend( GetCmakeArgs(  ) )
    full_cmake_args.append( p.join( DIR_OF_THIS_SCRIPT, 'cpp' ) )

    print(full_cmake_args)
    print("\n\n\n\n\n")
    os.chdir( 'ycm_build' )
    try:
      subprocess.check_call( [ 'cmake' ] + full_cmake_args )

      build_target = ( 'ycm_core' )

      build_command = [ 'cmake', '--build', '.', '--target', build_target ]

      build_command.extend( [ '--', '-j', str( NumCores() ) ] )

      # subprocess.check_call( build_command )
    except subprocess.CalledProcessError:
      traceback.print_exc()
      sys.exit(
        '\n\nERROR: The build failed.\n\n'
        'NOTE: It is *highly* unlikely that this is a bug but rather\n'
        'that this is a problem with the configuration of your system\n'
        'or a missing dependency. Please carefully read CONTRIBUTING.md\n'
        "and if you're sure that it is a bug, please raise an issue on the\n"
        'issue tracker, including the entire output of this script\n'
        'and the invocation line used to run it.\n' )

  finally:
    os.chdir( DIR_OF_THIS_SCRIPT )
    # rmtree( build_dir, ignore_errors = OnTravisOrAppVeyor() )


def WritePythonUsedDuringBuild():
  path = p.join( DIR_OF_THIS_SCRIPT, 'PYTHON_USED_DURING_BUILDING' )
  with open( path, 'w' ) as f:
    f.write( sys.executable )


def Main():
  BuildYcmdLib(  )

  WritePythonUsedDuringBuild()


if __name__ == '__main__':
  Main()
