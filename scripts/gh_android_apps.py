#!/usr/bin/env python3
"""Collect data on Android apps on Github.

Combine information from Github and Google Play to find open source Android
apps. Commonly used meta data is parsed into a graph database.

Reads environment variable GITHUB_AUTH_TOKEN to use for authentication with
Github if available. Authenticated requests have higher rate limits.

This script executes several of the interdependent steps as sub-commands. Use
the --help option on a sub-command to learn more about it.
"""
import argparse
import importlib
import sys
from util import log


SUB_COMMANDS = [
    'store_in_neo4j',
    ]


def define_cmdline_interface():
    """Define parsers for main script and sub-commands."""
    # Arguments to main script
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        '--log', default=sys.stderr,
        type=argparse.FileType('w'),
        help='Log file. Default: stderr.')
    parser.add_argument(
        '-v', '--verbose', default=0, action='count',
        help='Increase log level. May be used several times.')
    parser.add_argument(
        '-q', '--quiet', default=0, action='count',
        help='Decrease log level. May be used several times.')

    subparsers = parser.add_subparsers()
    for command in SUB_COMMANDS:
        script = importlib.import_module('subcommands.{}'.format(command))
        command_parser = subparsers.add_parser(
            command, description=script.__doc__, help=script.__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
        script.define_cmdline_arguments(command_parser)

    return parser


if __name__ == '__main__':
    PARSER = define_cmdline_interface()
    ARGS = PARSER.parse_args()
    if 'func' in ARGS:
        log.configure_logger('', ARGS.log, ARGS.verbose, ARGS.quiet)
        ARGS.func(ARGS)
    else:
        PARSER.print_help()
