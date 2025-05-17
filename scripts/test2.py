#! /usr/bin/env python3

'''
Build/test script for PyMuPDF.

We always run ourselves inside a venv.

Arguments are processed in the order they occur on the command line. So usually one
would specify (for example) `-b` (build) before `-t` (test).

Example commands:

    Build and test:
        -b -t
    
    Build and test debug build:
        -B debug -b -t
    
    Build and test a debug build with valgrind:
        -B debug -b -P valgrind -t
    
    Build wheel with cibuildwheel:
        -W
    
Args:

    -h
    --help
        Show help and exit.
    -b
        Build and install.
    -B <build_type>
        Set build type, one of: 'release', 'debug'.
        Equivalent to `-e PYMUPDF_SETUP_MUPDF_BUILD_TYPE=<build_type>`.
    -e <name>=<value>
        Add to environment used in later build/test commands. Can be specified
        multiple times.
    -E <env_name>
        Read next arg(s) from environmental variable <env_name>. Does nothing
        if <env_name> is not set.
    -m <mupdf>
        Specify mupdf, sets PYMUPDF_SETUP_MUPDF_BUILD.
    -o <os-names>
        Only run if platform.system() is in comma-separated list <os-names>, or
        <os-names> is empty.
    -p <pytest_args>
        Extra pytest args, for example `-p '-k <testname>'`.
    -P <pytest_wrap>
        Run pytest under a wrapper command, one of:
            gdb
            helgrind
            valgrind
    --sync-paths
        Do not run anything, instead write required files/directories/checkouts
        to stdout. This is to allow automated running on remote machines.
    -t
        Run pytest tests.
    --venv 0|1
        Must be first args; if 1 (the default) we re-run outselves inside a
        venv if we are not already in a venv.
    --vs-upgrade 0|1
        Equivalent to `-e PYMUPDF_SETUP_MUPDF_VS_UPGRADE=0|1`.
        
        If 1, upgrade Visual Studio files.
    -w
        Build wheel in directory `wheelhouse` and install.
    -W
        Build and test wheel(s) using cibuildwheel. Wheels are placed in
        directory `wheelhouse`.
        
        If CIBW_ARCHS is unset we set $CIBW_ARCHS_WINDOWS, $CIBW_ARCHS_MACOS
        and $CIBW_ARCHS_LINUX to auto64 if they are unset.
        
        Additionally, if running on Github ($GITHUB_ACTIONS=true) and
        $CIBW_ARCHS_LINUX is unset, we set $CIBW_ARCHS_LINUX to 'auto64
        aarch64' so that we build for aarch64 using emulation. This is required
        because there is no native aarch64 host available.
'''

import os
import platform
import shlex
import subprocess
import sys

def relpath(path, start=None):
    try:
        return os.path.relpath(path, start)
    except Exception:
        assert platform.system() == 'Windows'
        return os.path.abspath(path)


g_root_dir = relpath(os.path.abspath(f'{__file__}/../..'))

try:
    sys.path.insert(0, g_root_dir)
    import pipcl
finally:
    del sys.path[0]


log = pipcl.log0
run = pipcl.run


if 1:
    # For debugging.
    log(f'### Starting.')
    
    log(f'{__file__=}')
    log(f'{__name__=}')
    log(f'{os.getcwd()=}')
    log(f'{platform.machine()=}')
    log(f'{platform.platform()=}')
    log(f'{platform.python_version()=}')
    log(f'{platform.system()=}')
    log(f'{platform.uname()=}')
    log(f'{sys.executable=}')
    log(f'{sys.version=}')
    log(f'{sys.version_info=}')
    log(f'{list(sys.version_info)=}')
    
    log(f'CPU bits: {32 if sys.maxsize == 2**31 - 1 else 64} {sys.maxsize=}')
    log(f'getconf ARG_MAX: {pipcl.run("getconf ARG_MAX", capture=1, check=0, verbose=0)!r}')
    
    log(f'sys.argv ({len(sys.argv)}):')
    for i, arg in enumerate(sys.argv):
        log(f'    {i}: {arg!r}')
    
    log(f'os.environ ({len(os.environ)}):')
    for k in sorted( os.environ.keys()):
        v = os.environ[ k]
        log( f'    {k}: {v!r}')

    
def venv_in(path=None):
    '''
    If path is None, returns true if we are in a venv. Otherwise returns true
    only is we are in venv <path>.
    '''
    if path:
        #log(f'{os.path.abspath(sys.prefix)=} {os.path.abspath(path)=}')
        return os.path.abspath(sys.prefix) == os.path.abspath(path)
    else:
        #log(f'{sys.prefix=} {sys.base_prefix=}')
        return sys.prefix != sys.base_prefix


def venv_ensure(args=None, path='venv-pymupdf'):
    '''
    If not running in venv <path>, creates it and re-run ourselves inside using
    exec.
    '''
    if args is None:
        args = sys.argv
    if not venv_in(path):
        if 0 and os.path.exists(path):
            pass
        else:
            log(f'{sys.executable=}')
            run(f'{sys.executable} -m venv {path}')
        # Would like to use os.execv() here, but on non-Windows i think this
        # would need us to know what the shell is.
        if platform.system() == 'Windows':
            command = f'{path}\\Scripts\\activate'
        else:
            command = f'. {path}/bin/activate'
        command += f' && python {shlex.join(args)}'
        e = run(command, check=0)
        sys.exit(e)
        #cp = subprocess.run(command, shell=1, check=0)
        #sys.exit(cp.returncode)


class NewFiles:
    '''
    Detects new files matching a glob pattern.
    '''
    def __init__(self, glob_pattern):
        self.pattern = glob_pattern
        self.items0 = set(glob.glob(self.pattern))
    def get(self):
        items = set(glob.glob(self.pattern))
        return list(items - self.items0)
    def get_one(self):
        ret = self.get()
        assert len(ret) == 1
        return ret[0]


def test_packages():
    '''
    Returns space-separated list of pypi.org packages required by PyMuPDF
    pytests.
    '''
    ret = 'pytest fontTools pymupdf-fonts flake8 pylint codespell'
    if platform.system() == 'Windows' and cpu_bits() == 32:
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

    # Create/enter hard-coded venv if not already in.
    #
    if sys.argv[1:2][0] in ('-h', '--help', '--sync-paths'):
        pass
    elif sys.argv[1:3] == ['--venv', '0']:
        pass
    else:
        venv_ensure()
    
    build_type = None
    env_extra = dict()
    install_packages = True
    pytest_args = None
    pytest_wrap = None
    sync_paths = False
    
    args = iter(sys.argv[1:])
    while 1:
        try:
            arg = next(args)
        except StopIteration:
            break
        
        if arg in ('-h', '--help'):
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
            if not mupdf.startswith('git:'):
                mupdf = os.path.abspath(mupdf)
                if sync_paths:
                    print(mupdf)
            env_extra['PYMUPDF_SETUP_MUPDF_BUILD'] = mupdf
        
        elif arg == '-o':
            os_names = next(args)
            if os_names and not sync_paths:
                if platform.system().lower() not in os_names.split(','):
                    log(f'Not running because {platform.system().lower()=} not in {os_names=}')
                    return
        
        elif arg == '-p':
            pytest_args = next(args)
        
        elif arg == '-P':
            pytest_wrap = next(args)
        
        elif arg == '--packages':
            install_packages = int(next(args))
        
        elif arg == '--sync-paths':
            sync_paths = True
            print(g_root_dir)
        
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
                        f' --suppressions={g_root_dir}/valgrind.supp'
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

            command += f' {relpath(sys.executable)} -m pytest'
            if pytest_wrap in ('valgrind', 'helgrind'):
                # Show all output even if tests pass.
                command += f' -s'
            if pytest_args:
                command += f' {pytest_args}'
            command += f' {g_root_dir}'
            run(command, env_extra=env_extra)
                
        elif arg == '--venv':
            use_venv = int(next(args)) 
        
        elif arg == '--vs-upgrade':
            env_extra['PYMUPDF_SETUP_MUPDF_VS_UPGRADE'] = next(args)
        
        elif arg == '-w':
            # Build and install wheel.
            if sync_paths:
                continue
            newer_files = NewerFiles('wheelhouse/*.whl')
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
