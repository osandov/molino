from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext
import os.path
import subprocess


def out_of_date(dependency, target):
    dependency_mtime = os.path.getmtime(dependency)
    try:
        target_mtime = os.path.getmtime(target)
    except OSError:
        return True
    return dependency_mtime >= target_mtime


class my_build_ext(build_ext):
    def run(self):
        script_path = 'imap4/generate_parser_tokens.py'
        module_path = 'imap4/constants.py'
        tokens_path = 'imap4/parser/tokens.c'
        header_path = 'imap4/parser/tokens.h'
        if (out_of_date(script_path, module_path) or
            out_of_date(script_path, tokens_path) or
            out_of_date(script_path, header_path)):
            subprocess.check_call([script_path, 'imap4'])
        super().run()


imap_parser_module = Extension('imap4.parser', sources=[
    'imap4/parser/module.c',
    'imap4/parser/parser.c',
    'imap4/parser/scanner.c',
    'imap4/parser/tokens.c',
    'imap4/parser/types.c',
])


setup(name='molino',
      version=1.0,
      description='Email client',
      entry_points={
          'console_scripts': ['molino=molino.__main__:main'],
      },
      cmdclass={'build_ext': my_build_ext},
      ext_modules=[imap_parser_module],
      test_suite='tests',
)
