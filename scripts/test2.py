#! /usr/bin/env python3

'''
Build/test script for PyMuPDF.

We automatically use an internal Python venv.
* Builds install into this venv.
* Tests use whatever PyMuPDF is installed in the venv.

Example args.
    -b -t
        Build and test.
    -B debug -b -t
        Build and test debug build.
    -B debug -b -T valgrind -t
        Build and test a debug build with valgrind.
    -m mupdf -W
        Build wheel with cibuildwheel using local `mupdf/` directory.
    -i pymupdf==1.25.5 -t
        Test PyMuPDF-1.25.5 from pypi.org.

Arg details.
    -a <env_name>
        Read next space-separated arg(s) from environmental variable
        <env_name>.
        * Does nothing if <env_name> is not set.
        * Useful when running via Github action.
    -b
        Build PyMuPDF and install into current venv, using `pip install`.
    -B <build_type>
        Set build type for -b and -w build/install commands.
        * <build_type> must be one of: 'release', 'debug'.
        * Equivalent to `-e PYMUPDF_SETUP_MUPDF_BUILD_TYPE=<build_type>`.
    -e <name>=<value>
        Add to environment used in build and test commands. Can be specified
        multiple times.
    -h
    --help
        Show help and exit.
    -i <pymupdf>
        Install PyMuPDF directly using pip by running:
            pip install --force-reinstall <pymupdf>
        * For example `-i pymupdf==1.25.5` will install PyMuPDF-1.25.5 from
          pypi.org.
    -m <mupdf>
        Specify the mupdf to used by -b, -w and -W build commands.
        * If starts with `git:`, specifies Git location to clone.
        * Otherwise should be local directory.
        * Sets $PYMUPDF_SETUP_MUPDF_BUILD.
        * See setup.py's documentation of PYMUPDF_SETUP_MUPDF_BUILD for
          details.
    -M 0|1
        Whether to build MuPDF specified by -m. Default is 1.
        * Equivalent to `-e PYMUPDF_SETUP_MUPDF_REBUILD=0|1`.
    -o <os_names>
        Control whether we do nothing on the current platform.
        * <os_names> is a comma-separated list of names.
        * If <os_names> is empty (the default), we always run normally.
        * Otherwise we only run if an item in <os_names> matches (case
          insensitive) platform.system().
        * For example `-o linux,darwin` will do nothing unless on Linux or
          MacOS.
    -p <pytest_args>
        Extra pytest args for -t tests, for example `-p '-k test_foo'` to run
        only `test_foo()`.
    --packages 0|1
        If 1 (the default), install required system packages (with sudo) in
        build and test commands.
    --sync-paths
        Do not run anything, instead write required files/directories/checkouts
        to stdout, one per line. This is to help with automated running on
        remote machines.
    -t
        Run pytest tests using the PyMuPDF in the venv (typically installed by
        an earlier -b or -w command).
    -T <test_wrap>
        In -t test commands, run pytest under a wrapper command, one of:
            gdb
            helgrind
            valgrind
    -v 0|1
        If 1 (the default) and we are not already in a venv, we create a venv
        and rerun ourselves inside it.
        * The venv is called `venv-pymupdf-<version>-<wordsize>`.
    --vs-upgrade 0|1
        If 1, upgrade Visual Studio files when building MuPDF. Equivalent to
        `-e PYMUPDF_SETUP_MUPDF_VS_UPGRADE=0|1`.
    -w
        Build a PyMuPDF wheel in directory `wheelhouse` using pip, and install
        into current venv.
    -W
        Build and test PyMuPDF wheel(s) using cibuildwheel. Wheels are placed
        in directory `wheelhouse`.
        * We do not attempt to install wheels.
        * So it is generally not useful to do `-W -t`.
        
        If CIBW_BUILD is unset, we set it as follows:
        * On Github we build and test all supported Python versions.
        * Otherwise we build and test the current Python version only.
        
        If CIBW_ARCHS is unset we set $CIBW_ARCHS_WINDOWS, $CIBW_ARCHS_MACOS
        and $CIBW_ARCHS_LINUX to auto64 if they are unset.
        
        Additionally, if running on Github ($GITHUB_ACTIONS=true) and
        $CIBW_ARCHS_LINUX is unset, we set $CIBW_ARCHS_LINUX to 'auto64
        aarch64' so that we build for aarch64 using emulation. This is required
        as of 2025-05-23 because there is no native aarch64 host available.

Ordering of args.
* First all non-build/test args are processed in the order given.
* Some non-build/test args are cumulative, others will overwrite earlier
  settings.
* Second we execute build/test args (-b, -t, -w, -W) in the order specified.
* Usually -t (test) would be specified after -b (build and install) or -w
  (build and install wheel).

Extra support for use in a Github action.
* We allow extra command-line args to be read from environment variables.
* See the -a arg above.
* This allows complex command lines to be specified as a single string,
  allowing a workaround for Github's 10-arg workflow parameter limit.
'''

import os
import platform
import shlex
import subprocess
import sys


g_root_dir_abs = os.path.abspath(f'{__file__}/../..')

try:
    sys.path.insert(0, g_root_dir_abs)
    import pipcl
finally:
    del sys.path[0]

g_root_dir = pipcl.relpath(g_root_dir_abs)

log = pipcl.log0
run = pipcl.run


def venv_in(path=None):
    '''
    If path is None, returns true if we are in a venv. Otherwise returns true
    only if we are in venv <path>.
    '''
    if path:
        return os.path.abspath(sys.prefix) == os.path.abspath(path)
    else:
        return sys.prefix != sys.base_prefix


def venv_run(args, path, recreate=True):
    '''
    Runs command inside venv and returns termination code.
    
    Args:
        args:
            List of args.
        path:
            Name of venv.
        recreate:
            If false we do not run `<sys.executable> -m venv <path>` if <path>
            already exists. This avoids a delay in the common case where <path>
            is already set up, but fails if <path> exists but does not contain
            a valid venv.
    '''
    if recreate or not os.path.isdir(path):
        run(f'{sys.executable} -m venv {path}')
    if platform.system() == 'Windows':
        command = f'{path}\\Scripts\\activate'
    else:
        command = f'. {path}/bin/activate'
    command += f' && python {shlex.join(args)}'
    e = run(command, check=0)
    return e


class NewFiles:
    '''
    Detects new files matching a glob pattern. Used to detect wheel created by
    pip.
    '''
    def __init__(self, glob_pattern):
        # Find current matches of <glob_pattern>.
        self.glob_pattern = glob_pattern
        self.items0 = set(glob.glob(self.glob_pattern))
    def get(self):
        '''
        Returns lst of new matches of <glob_pattern>.
        '''
        items = set(glob.glob(self.glob_pattern))
        return list(items - self.items0)
    def get_one(self):
        '''
        Returns new match of <glob_pattern>, asserting that there is exactly
        one.
        '''
        ret = self.get()
        assert len(ret) == 1
        return ret[0]


def test_packages():
    '''
    Returns space-separated list of pypi.org packages required by PyMuPDF
    pytests.
    '''
    ret = 'pytest fontTools pymupdf-fonts flake8 pylint codespell'
    if platform.system() == 'Windows' and pipcl.cpu_bits() == 32:
        # No pillow wheel available, and doesn't build easily.
        pass
    else:
        ret += ' pillow'
    if platform.system().startswith('MSYS_NT-'):
        # psutil not available on msys2.
        pass
    else:
        ret += ' psutil'
    return ret


def main():

    # Set default state.
    #
    commands = list()
    build_type = None
    env_extra = dict()
    packages = True
    mupdf = None
    os_names = list()
    pytest_args = None
    test_wrap = None
    show_help = False
    sync_paths = False
    venv = True

    # Parse args and update the above state.
    #
    args = iter(sys.argv[1:])
    while 1:
        try:
            arg = next(args)
        except StopIteration:
            break
        
        if 0:
            pass
        
        elif arg == '-a':
            _name = next(args)
            _value = os.environ.get(_name, '')
            _args = shlex.split(_value) + list(args)
            args = iter(_args)
        
        elif arg == '-b':
            commands.append(arg)
        
        elif arg == '-B':
            env_extra['PYMUPDF_SETUP_BUILD_TYPE'] = next(args)
        
        elif arg == '-e':
            _nv = next(args)
            assert '=' in _nv, f'-e <name>=<value> does not contain "=": {_nv!r}'
            try:
                _name, _value = _nv.split('=', 1)
            except Exception as e:
                raise Exception(f'Unable to parse into <name>=<value>: {_nv!r}') from e
            env_extra[_name] = _value
        
        elif arg in ('-h', '--help'):
            show_help = True
        
        elif arg == '-i':
            _pymupdf = next(args)
            commands.append(f'-i{_pymupdf}')
        
        elif arg == '-m':
            mupdf = next(args)
            if mupdf.startswith('git:'):
                env_extra['PYMUPDF_SETUP_MUPDF_BUILD'] = mupdf
            else:
                assert os.path.isdir(mupdf), f'Not a directory: {mupdf=}'
                env_extra['PYMUPDF_SETUP_MUPDF_BUILD'] = os.path.abspath(mupdf)
        
        elif arg == '-M':
            _b = next(args)
            env_extra['PYMUPDF_SETUP_MUPDF_REBUILD'] = _b
        
        elif arg == '-o':
            os_names += next(args).split(',')
        
        elif arg == '-p':
            pytest_args = next(args)
        
        elif arg == '-T':
            test_wrap = next(args)
        
        elif arg == '--packages':
            packages = int(next(args))
        
        elif arg == '--sync-paths':
            sync_paths = True
        
        elif arg == '-v':
            venv = next(args)
                
        elif arg in ('-t', '-w', '-W'):
            commands.append(arg)
        
        else:
            assert 0, f'Unrecognised {arg=}. Run with `-h` to show help.'

    # Handle special args --sync-paths, -h, -v, -o first.
    #
    if sync_paths:
        # Just print required files, directories and checkouts.
        if show_help:
            return
        print(g_root_dir)
        if mupdf and not mupdf.startswith('git:'):
            print(mupdf)
        return

    if show_help:
        print(__doc__)
        return
    
    if os_names:
        if platform.system().lower() not in os_names:
            log(f'Not running because {platform.system().lower()=} not in {os_names=}')
            return
    
    if commands:
        if venv:
            # Rerun ourselves inside a venv if not already in a venv.
            if not venv_in():
                e = venv_run(
                        sys.argv,
                        f'venv-pymupdf-{platform.python_version()}-{int.bit_length(sys.maxsize+1)}',
                        )
                sys.exit(e)
    else:
        log(f'Warning, no commands specified so nothing to do.')
    
    log(f'env_extra ({len(env_extra)}):')
    for n in sorted(env_extra.keys()):
        v = env_extra[n]
        log(f'    {n}: {v!r}')
    
    # Handle commands.
    #
    have_installed = False
    for command in commands:
        
        if command == '-b':
            # Build and install with pip.
            run(f'pip install -v ./{g_root_dir}', env_extra=env_extra)
            have_installed = True
        
        elif command.startswith('-i'):
            _pymupdf = command[2:]
            run(f'pip install --force-reinstall {_pymupdf}')
            have_installed = True
        
        elif command == '-t':
            # Test.
            if not have_installed:
                log(f'## Warning: have not built/installed PyMuPDF; testing whatever is already installed.')
            run(f'pip install --upgrade pytest')
            run(f'pip install --upgrade {test_packages()}')
            if packages and test_wrap in ('valgrind', 'helgrind'):
                if platform.system() == 'Linux':
                    run(f'sudo apt update')
                    run(f'sudo apt install valgrind')
            command = ''
            if test_wrap is None:
                pass
            elif test_wrap == 'gdb':
                command = 'gdb --args'
            elif test_wrap == 'valgrind':
                env_extra['PYMUPDF_RUNNING_ON_VALGRIND'] = '1'
                env_extra['PYTHONMALLOC'] = 'malloc'
                command = (
                        f'valgrind'
                        f' --suppressions={g_root_dir_abs}/valgrind.supp'
                        f' --trace-children=yes'
                        f' --num-callers=20'
                        f' --error-exitcode=100'
                        f' --errors-for-leak-kinds=none'
                        f' --fullpath-after='
                        )
            elif test_wrap == 'helgrind':
                env_extra['PYMUPDF_RUNNING_ON_VALGRIND'] = '1'
                env_extra['PYTHONMALLOC'] = 'malloc'
                command = (
                        f'valgrind'
                        f' --tool=helgrind'
                        f' --trace-children=yes'
                        f' --num-callers=20'
                        f' --error-exitcode=100'
                        f' --fullpath-after='
                        )
            elif test_wrap == 'gdb':
                command = 'gdb --args'
            else:
                assert 0, f'Unrecognised {test_wrap=}'

            command += f' {pipcl.relpath(sys.executable)} -m pytest'
            if test_wrap in ('valgrind', 'helgrind'):
                # Show all output even if tests pass.
                command += f' -s'
            if pytest_args:
                command += f' {pytest_args}'
            command += f' {g_root_dir}'
            run(command, env_extra=env_extra)
                
        elif command == '-w':
            # Build and install wheel.
            newer_files = NewFiles('wheelhouse/*.whl')
            run(f'pip wheel -w wheelhouse -v {g_root_dir}', env_extra=env_extra)
            wheel = newer_files.get_one()
            run(f'pip install {wheel}')
            have_installed = True
        
        elif command == '-W':
            # Build wheel(s) with cibuildwheel.
            run(f'pip install --upgrade cibuildwheel')

            # Some general flags.
            env_extra['CIBW_BUILD_VERBOSITY'] = '1'
            env_extra['CIBW_SKIP'] = 'pp* *i686 cp36* cp37* *musllinux* *-win32 *-aarch64'

            # Set what wheels to build, if not already specified.
            if os.environ.get('CIBW_ARCHS') is None:
                if os.environ.get('CIBW_ARCHS_WINDOWS') is None:
                    env_extra['CIBW_ARCHS_WINDOWS'] = 'auto64'

                if os.environ.get('CIBW_ARCHS_MACOS') is None:
                    env_extra['CIBW_ARCHS_MACOS'] = 'auto64'

                if os.environ.get('CIBW_ARCHS_LINUX') is None:
                    env_extra['CIBW_ARCHS_LINUX'] = 'auto64'
                    if os.environ.get('GITHUB_ACTIONS') == 'true':
                        # Special case to use emulation/cross-compilation of
                        # aarch64 on Linux.
                        env_extra['CIBW_ARCHS_LINUX'] += ' aarch64'

            # Tell cibuildwheel not to use `auditwheel` on Linux and MacOS,
            # because it cannot cope with us deliberately having required
            # libraries in different wheel - specifically in the PyMuPDF wheel.
            #
            # We cannot use a subset of auditwheel's functionality
            # with `auditwheel addtag` because it says `No tags
            # to be added` and terminates with non-zero. See:
            # https://github.com/pypa/auditwheel/issues/439.
            #
            env_extra['CIBW_REPAIR_WHEEL_COMMAND_LINUX'] = ''
            env_extra['CIBW_REPAIR_WHEEL_COMMAND_MACOS'] = ''

            # Tell cibuildwheel how to test.
            env_extra['CIBW_TEST_COMMAND'] = f'python {{project}}/scripts/test2.py -t'

            # Specify python versions.
            CIBW_BUILD = os.environ.get('CIBW_BUILD')
            if CIBW_BUILD is None:
                if os.environ.get('GITHUB_ACTIONS') == 'true':
                    # Build/test all supported Python versions.
                    CIBW_BUILD = os.environ.get('CIBW_BUILD', 'cp39* cp310* cp311* cp312* cp313*')
                else:
                    # Build/test current Python only.
                    v = platform.python_version_tuple()[:2]
                    CIBW_BUILD = f'cp{"".join(v)}*'

            # Build for lowest (assumed first) Python version.
            #
            log(f'py_limited_api: building for first Python version.')
            env_extra['CIBW_BUILD'] = CIBW_BUILD.split()[0]
            run(f'cd {g_root_dir} && cibuildwheel', env_extra=env_extra)

            # Tell cibuildwheel to build and test all specified Python
            # verisons; it will notice that the wheel we built above supports
            # all versions of Python, so will not actually do any builds here.
            #
            env_extra['CIBW_BUILD'] = CIBW_BUILD
            log(f'py_limited_api: building/testing for all Python versions {CIBW_BUILD=}.')
            run(f'cd {g_root_dir} && cibuildwheel', env_extra=env_extra)
            run(f'ls -ld {g_root_dir}/wheelhouse/*')
        
        else:
            assert 0, f'Unrecognised {command=}'
                

if __name__ == '__main__':
    main()
