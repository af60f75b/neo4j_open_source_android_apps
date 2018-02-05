"""Maintain a global logger instance."""
import logging
from typing import IO, Text
import neo4j


LOG_LEVEL = logging.WARNING
LOG_FORMAT = '%(asctime)s | [%(levelname)s] %(name)s: %(message)s'
LEVELS = [
    logging.NOTSET, logging.DEBUG, logging.INFO, logging.WARNING,
    logging.ERROR, logging.CRITICAL]


def compute_level(verbose: int, quiet: int) -> int:
    """Compute a log level based on input.

    Log level is based on LOG_LEVEL.

    :param int verbose:
        Number of levels to increase log level.
    :param int quiet:
        Number of levels to decrease log level.
    :returns int:
        New log level. Either of NOTSET, DEBUG, INFO, WARNING, ERROR, CRITICAL.
    """
    if verbose < 0 or quiet < 0:
        raise ValueError('Input must not be less than 0')
    default_index = LEVELS.index(LOG_LEVEL)
    index = min(len(LEVELS) - 1, max(0, default_index + quiet - verbose))
    return LEVELS[index]


def lower_level_for_libraries(min_level: int):
    """Decrease log level for libraries."""
    max_level = max(min_level, logging.WARNING)
    for package in [neo4j]:
        logger = logging.getLogger(package.__package__)
        logger.setLevel(max_level)


def configure_logger(name: Text, stream: IO[str], verbose: int, quiet: int):
    """Create handler for logging to an IO stream.

    :param Text name:
        Name of logger, e.g. __package__.
    :param IO[str] stream:
        Stream to log to, e.g. sys.stderr.
    :param int verbose:
        Number of levels to increase log level.
    :param int quiet:
        Number of levels to decrease log level.
    """
    log_level = compute_level(verbose, quiet)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.setLevel(log_level)

    lower_level_for_libraries(log_level)

    logger = logging.getLogger(name)
    logger.setLevel(handler.level)
    logger.addHandler(handler)

    logger.info('Log to %s. Level: %d', stream.name, log_level)
