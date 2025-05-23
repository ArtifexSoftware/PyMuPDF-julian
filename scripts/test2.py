#! /usr/bin/env python3

'''
Build/test script for PyMuPDF.

We default to running ourselves inside a venv.

Arguments are processed in the order they occur on the command line. So usually one
would specify (for example) `-B debug` before `-b` (build) before `-t` (test).

We fail with an error if there are trailing arguments that will have no effect
on any build or test commands.

Example commands:

    Build and test:
        -b -t
    
    Build and test debug build:
        -B debug -b -t
    
    Build and test a debug build with valgrind:
        -B debug -b -P valgrind -t
    
    Build wheel with cibuildwheel using local `mupdf/` directory:
        -m mupdf -W

Args:
    
    -h
    --help
        Show help and exit.
    -b
        Build PyMuPDF and install into current venv, using `pip install`.
    -B <build_type>
        Set build type of later `-b` commands; one of: 'release', 'debug'.
        Equivalent to `-e PYMUPDF_SETUP_MUPDF_BUILD_TYPE=<build_type>`.
    -e <name>=<value>
        Add to environment used in later build/test commands. Can be specified
        multiple times.
    -E <env_name>
        Read next arg(s) from environmental variable <env_name>. Does nothing
        if <env_name> is not set. Useful when running via Github action.
    -m <mupdf>
        Specify mupdf used by later `-b` args; sets PYMUPDF_SETUP_MUPDF_BUILD.
    -o <os_names>
        Control whether we do nothing on the current platform.
        Only run later commands if platform.system() is in comma-separated list
        <os_names>, or <os_names> is empty.
    -p <pytest_args>
        Extra pytest args for later `-t` commands, for example `-p '-k
        <testname>'`.
    -P <pytest_wrap>
        In later `-t` commands, run pytest under a wrapper command, one of:
            gdb
            helgrind
            valgrind
    --packages 0|1
        If 1 (the default), install system packages (with sudo) in later `-b`
        or `-t` commands.
    --sync-paths
        Must be first arg. Do not run anything, instead write required
        files/directories/checkouts to stdout. This is to help with automated
        running on remote machines.
    -t
        Run pytest tests using PyMuPDF in current venv (typically installed
        using an earlier `-b` or `-w` command.
    --venv 0|1
        Must be first args or immediately after `--sync-paths`; if 1 (the
        default) we re-run ourselves inside a venv if we are not already in a
        venv.
    --vs-upgrade 0|1
        If 1, upgrade Visual Studio files in later `-b` commands. Equivalent to
        `-e PYMUPDF_SETUP_MUPDF_VS_UPGRADE=0|1`.
    -w
        Build wheel in directory `wheelhouse` and install into current venv.
    -W
        Build and test wheel(s) using cibuildwheel. Wheels are placed in
        directory `wheelhouse`. We do not attempt to install wheels and so it
        is generally not useful to do `-W -t`.
        
        If CIBW_ARCHS is unset we set $CIBW_ARCHS_WINDOWS, $CIBW_ARCHS_MACOS
        and $CIBW_ARCHS_LINUX to auto64 if they are unset.
        
        Additionally, if running on Github ($GITHUB_ACTIONS=true) and
        $CIBW_ARCHS_LINUX is unset, we set $CIBW_ARCHS_LINUX to 'auto64
        aarch64' so that we build for aarch64 using emulation. This is required
        as of 2025-05-23 because there is no native aarch64 host available.
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
    Detects new files matching a glob pattern. Used to detect wheels created by
    pip.
    '''
    def __init__(self, glob_pattern):
        '''
        Finds current matches of <glob_pattern>.
        '''
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

    build_type = None
    env_extra = dict()
    install_packages = True
    pytest_args = None
    pytest_wrap = None
    sync_paths = False

    argv = sys.argv[1:]
    
    # Handle any initial --sync-paths and --venv args.
    #
    if len(argv) >= 1 and argv[0] == '--sync-paths':
        # Don't call pipcl.show_system(), don't run ourselves inside a venv,
        # don't run any builds or tests. We only output required files,
        # directories and git checkouts.
        sync_paths = True
        argv = argv[1:]
        print(g_root_dir)
    
    # Check ordering of args.
    if not sync_paths:
        for i in range(len(sys.argv)-1, -1, -1):
            if sys.argv[i] in ('-b', '-w', '-W', '-t'):
                if i < len(sys.argv)-1:
                    log(f'Error: trailing args after {sys.argv[i]!r} will have no effect:')
                    items = [shlex.quote(i) for i in sys.argv]
                    lens = [1+len(i) for i in items]
                    a = sum(lens[:i+1])
                    b = sum(lens[i+1:]) - 1
                    log(' '.join(items))
                    log(f'{" "*a}{"^"*b}')
                    sys.exit(1)
                break

    # Create/enter hard-coded venv if not already in a venv.
    use_venv = True
    if len(argv) >= 2 and argv[0] == '--venv':
        use_venv = int(argv[1])
        argv = argv[2:]
    if not sync_paths and use_venv and not venv_in():
        # Rerun ourselves inside a venv.
        e = venv_run(
                [sys.argv[0]] + argv,
                f'venv-pymupdf-{platform.python_version()}-{int.bit_length(sys.maxsize+1)}',
                )
        sys.exit(e)

    if not sync_paths:
        # Show system information.
        log(f'### Starting.')
        pipcl.show_system()
    
    # Handle args, strictly in order.
    #
    args = iter(argv)
    while 1:
        try:
            arg = next(args)
        except StopIteration:
            break
        
        if arg in ('-h', '--help'):
            if sync_paths:
                continue
            log(__doc__)
            return
        
        elif arg == '-b':
            if sync_paths:
                continue
            run(f'pip install -v ./{g_root_dir}', env_extra=env_extra)
        
        elif arg == '-B':
            build_type = next(args)
            env_extra['PYMUPDF_SETUP_BUILD_TYPE'] = build_type
        
        elif arg == '-e':
            n, v = next(args).split('=', 1)
            env_extra[n] = v
        
        elif arg == '-E':
            env_name = next(args)
            env_value = os.environ.get(env_name, '')
            args = shlex.split(env_value) + list(args)
            args = iter(args)
        
        elif arg == '-m':
            mupdf = next(args)
            if mupdf.startswith('git:'):
                env_extra['PYMUPDF_SETUP_MUPDF_BUILD'] = mupdf
            else:
                if sync_paths:
                    print(mupdf)
                env_extra['PYMUPDF_SETUP_MUPDF_BUILD'] = os.path.abspath(mupdf)
        
        elif arg == '-o':
            os_names = next(args)
            if os_names:
                if platform.system().lower() not in os_names.split(','):
                    if not sync_paths:
                        log(f'Not running because {platform.system().lower()=} not in {os_names=}')
                    return
        
        elif arg == '-p':
            pytest_args = next(args)
        
        elif arg == '-P':
            pytest_wrap = next(args)
        
        elif arg == '--packages':
            install_packages = int(next(args))
        
        elif arg == '-t':
            # Test.
            if sync_paths:
                continue
            run(f'pip install --upgrade pytest')
            run(f'pip install --upgrade {test_packages()}')
            if install_packages and pytest_wrap in ('valgrind', 'helgrind'):
                if platform.system() == 'Linux':
                    run(f'sudo apt update')
                    run(f'sudo apt install valgrind')
            command = ''
            if pytest_wrap is None:
                pass
            elif pytest_wrap == 'gdb':
                command = 'gdb --args'
            elif pytest_wrap == 'valgrind':
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
            elif pytest_wrap == 'helgrind':
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
            elif pytest_wrap == 'gdb':
                command = 'gdb --args'
            else:
                assert 0, f'Unrecognised {pytest_wrap=}'

            command += f' {pipcl.relpath(sys.executable)} -m pytest'
            if pytest_wrap in ('valgrind', 'helgrind'):
                # Show all output even if tests pass.
                command += f' -s'
            if pytest_args:
                command += f' {pytest_args}'
            command += f' {g_root_dir}'
            run(command, env_extra=env_extra)
                
        elif arg == '--vs-upgrade':
            env_extra['PYMUPDF_SETUP_MUPDF_VS_UPGRADE'] = next(args)
        
        elif arg == '-w':
            # Build and install wheel.
            if sync_paths:
                continue
            newer_files = NewFiles('wheelhouse/*.whl')
            run(f'pip wheel -w wheelhouse -v {g_root_dir}', env_extra=env_extra)
            wheel = newer_files.get_one()
            run(f'pip install {wheel}')
        
        elif arg == '-W':
            # Build wheel(s) with cibuildwheel.
            if sync_paths:
                continue
            # Build wheel(s) with cibuildwheel.
            #venv_ensure_local()
            run(f'pip install --upgrade cibuildwheel')

            # Need to get sot checkout here because (on linux at least) there
            # is no `ssh` command available inside cibuildwheel's docker. And
            # we put the sot checkout within PyMuPDF/ so that it is available
            # inside the docker.
            #
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
            if os.environ.get('GITHUB_ACTIONS') == 'true':
                CIBW_BUILD = os.environ.get('CIBW_BUILD', 'cp39* cp310* cp311* cp312* cp313*')
            else:
                v = platform.python_version_tuple()[:2]
                CIBW_BUILD = f'cp{"".join(v)}*'

            # Build for lowest (assumed first) Python version. Our second
            # invocation of cibuildwheel will then use this wheel instead of
            # building a wheel, and test with all Python versions.
            #
            log(f'py_limited_api: building for first Python version.')
            env_extra['CIBW_BUILD'] = CIBW_BUILD.split()[0]
            run(f'cd {g_root_dir} && cibuildwheel', env_extra=env_extra)

            # cibuildwheel automatically notices that first wheel built
            # supports later versions of Python so will build only for first
            # (lowest) Python and test it on all Python versions.
            #
            env_extra['CIBW_BUILD'] = CIBW_BUILD
            log(f'py_limited_api: building/testing for all Python versions {CIBW_BUILD=}.')
            run(f'cd {g_root_dir} && cibuildwheel', env_extra=env_extra)
            run(f'ls -ld {g_root_dir}/wheelhouse/*')
        
        else:
            assert 0, f'Unrecognised {arg=}'
                

if __name__ == '__main__':
    main()
