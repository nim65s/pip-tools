# coding: utf-8
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import sys
import pip

# Make sure we're using a reasonably modern version of pip  # isort:skip
if not tuple(int(digit) for digit in pip.__version__.split('.')[:2]) >= (6, 1):
    print('pip-compile requires at least version 6.1 of pip ({} found), '
          'perhaps run `pip install --upgrade pip`?'.format(pip.__version__))
    sys.exit(4)

from itertools import chain, cycle
from os.path import basename

import click
from pip.req import parse_requirements

from ..exceptions import PipToolsError
from ..logging import log
from ..repositories import PyPIRepository
from ..resolver import Resolver
from ..utils import format_requirement

DEFAULT_REQUIREMENTS_FILE = 'requirements.in'

@click.command()
@click.option('-v', '--verbose', is_flag=True, help="Show more output")
@click.option('--dry-run', is_flag=True, help="Only show what would happen, don't change anything")
@click.option('-p', '--pre', is_flag=True, help="Allow resolving to prereleases (default is not)")
@click.option('-r', '--rebuild', is_flag=True, help="Clear any caches upfront, rebuild from scratch")
@click.option('-f', '--find-links', multiple=True, help="Look for archives in this directory or on this HTML page")
@click.option('-i', '--index-url', help="Change index URL (defaults to PyPI)")
@click.option('--extra-index-url', multiple=True, help="Add additional index URL to search")
@click.option('--no-header', is_flag=True, help="Disable the header comment in autogenerated file")
@click.option('-a', '--annotate', is_flag=True,
              help="Annotate results, indicating where dependencies come from")
@click.argument('src_file', required=False, type=click.Path(exists=True), default=DEFAULT_REQUIREMENTS_FILE)
def cli(verbose, dry_run, pre, rebuild, find_links, index_url,
        extra_index_url, no_header, annotate, src_file):
    """Compiles requirements.txt from requirements.in specs."""
    log.verbose = verbose

    if not src_file:
        log.warning('No input files to process.')
        sys.exit(2)

    ###
    # Setup
    ###
    repository = PyPIRepository()

    # Configure the finder
    if index_url:
        repository.finder.index_urls = [index_url]
    repository.finder.index_urls.extend(extra_index_url)
    repository.finder.find_links.extend(find_links)

    log.debug('Using indexes:')
    for index_url in repository.finder.index_urls:
        log.debug('  {}'.format(index_url))

    if repository.finder.find_links:
        log.debug('')
        log.debug('Configuration:')
        for find_link in repository.finder.find_links:
            log.debug('  -f {}'.format(find_link))

    ###
    # Parsing/collecting initial requirements
    ###
    constraints = []
    for line in parse_requirements(src_file, finder=repository.finder, session=repository.session):
        constraints.append(line)

    try:
        resolver = Resolver(constraints, repository, prereleases=pre, clear_caches=rebuild)
        results = resolver.resolve()
    except PipToolsError as e:
        log.error(str(e))
        sys.exit(2)

    # Format the results for outputting
    log.debug('')
    formatted_results = sorted(results, key=lambda r: (not r.editable, str(r.req).lower()))

    # In verbose mode, we format the results in blue
    blue = 'blue' if verbose else None

    if not no_header:
        log.info('#', fg=blue)
        log.info('# This file is autogenerated by pip-compile', fg=blue)
        log.info('# Make changes in {}, then run this to update:'.format(basename(src_file)), fg=blue)
        log.info('#', fg=blue)
        log.info('#    pip-compile {}'.format(basename(src_file)), fg=blue)
        log.info('#', fg=blue)
    for directive, index_url in zip(chain(['--index-url'], cycle(['--extra-index-url'])),
                                    repository.finder.index_urls):
        if index_url == repository.DEFAULT_INDEX_URL:
            continue
        log.info('{} {}'.format(directive, repository.finder.index_urls[0]), fg=blue)

    if annotate:
        # Compute reverse dependency annotations statically, from the
        # dependency cache that the resolver has populated by now.
        #
        # TODO (1a): reverse deps for any editable package are lost
        #            what SHOULD happen is that they are cached in memory, just
        #            not persisted to disk!
        #
        # TODO (1b): perhaps it's easiest if the dependency cache has an API
        #            that could take InstallRequirements directly, like:
        #
        #                cache.set(ireq, ...)
        #
        #            then, when ireq is editable, it would store in
        #
        #              editables[egg_name][link_without_fragment] = deps
        #              editables['pip-tools']['git+...ols.git@future'] = {'click>=3.0', 'six'}
        #
        #            otherwise:
        #
        #              self[as_name_version_tuple(ireq)] = {'click>=3.0', 'six'}
        #
        # TODO (2): consider dropping annotations for top-level packages, e.g.
        #           when both django and django-debug-toolbar are top-level
        #           requirements, django gets this stupid annotation:
        #
        #             django-debug-toolbar==1.3.0
        #             django==1.8    # via django-debug-toolbar
        #
        rev_deps = resolver.reverse_dependencies(results)
    for result in formatted_results:
        annotation = None
        if annotate:
            annotation = ', '.join(sorted(rev_deps.get(result.name, [])))
            if annotation:
                annotation = 'via ' + annotation
        log.info(format_requirement(result, annotation=annotation), fg=blue)

    if dry_run:
        log.warning('Dry-run, so nothing updated.')
