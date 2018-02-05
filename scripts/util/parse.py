"""Parse intermediary files for further processing."""

import csv
from datetime import datetime
import glob
import json
import logging
import os
import re
from typing import \
    Dict, \
    Generator, \
    IO, \
    List, \
    Mapping, \
    Sequence, \
    Set, \
    Text, \
    Tuple, \
    Union


__log__ = logging.getLogger(__name__)

ParsedJSON = Union[  # pylint: disable=C0103
    Mapping[Text, 'ParsedJSON'], Sequence['ParsedJSON'], Text, int, float,
    bool, None]

TIME_FORMAT = '%Y-%m-%dT%H:%M:%S%z'
TIMESTAMP_PATTERN = re.compile(
    r'(\d+-\d+-\d+T\d+:\d+:\d+)\.?\d*([-\+Z])((\d+):(\d+))?')
GITLAB_KEYS = ['clone_project_name', 'clone_project_id']


def parse_package_to_repos_file(input_file: IO[str]) -> Dict[str, List[str]]:
    """Parse CSV file mapping package names to repositories.

    :param IO[str] input_file: CSV file to parse.
        The file needs to contain a column `package` and a column
        `all_repos`. `all_repos` contains a comma separated string of
        Github repositories that include an AndroidManifest.xml file for
        package name in column `package`.
    :returns Dict[str, List[str]]: A mapping from package name to
        list of repository names.
    """
    return {
        row['package']: row['all_repos'].split(',')
        for row in csv.DictReader(input_file)
        }


def parse_package_details(details_dir: str) -> Generator[
        Tuple[str, ParsedJSON], None, None]:
    """Parse all JSON files in details_dir.

    Filenames need to have .json extension. Filename without extension is
    assumed to be package name for details contained in file.

    :param str details_dir: Directory to include JSON files from.
    :returns Generator[Tuple[str, ParsedJSON]]: Generator over tuples of
        package name and parsed JSON.
    """
    for path in glob.iglob('{}/*.json'.format(details_dir)):
        if os.path.isfile(path):
            with open(path, 'r') as details_file:
                filename = os.path.basename(path)
                package_name = os.path.splitext(filename)[0]
                package_details = json.load(details_file)
                yield package_name, package_details


def invert_mapping(packages: Mapping[str, Sequence[str]]) -> Dict[
        str, Set[str]]:
    """Create mapping from repositories to package names.

    :param Mapping[str, Sequence[str]] packages: Mapping of package names to
        a list of repositories.
    :returns Dict[str, Set[str]]: Mapping of repositories to set of package
        names.
    """
    result = {}
    for package, repos in packages.items():
        for repo in repos:
            result.setdefault(repo, set()).add(package)
    return result


def parse_repo_to_package_file(input_file: IO[str]) -> Dict[str, Set[str]]:
    """Parse CSV file mapping a repository name to a package name.

    :param IO[str] input_file:
        CSV file to parse. First column of the file needs to contain package
        names. The second column contains the corresponding repository name.
    :returns Dict[str, Set[str]]:
        A mapping from repository name to set of package names in that
        repository.
    """
    result = {}
    for row in csv.reader(input_file):
        result.setdefault(row[1], set()).add(row[0])
    return result


def describe_in_app_purchases(meta_data: ParsedJSON) -> str:
    """Find description of in-app purchases.

    :param dict meta_data:
        Meta data of Google Play Store page parses from JSON.
    :returns str:
        Description of in-app purchases if it exists, otherwise None.
    """
    product_details_sections = meta_data.get('productDetails', {}).get(
        'section', [])
    for section in product_details_sections:
        if section['title'] == 'In-app purchases':
            return section['description'][0]['description']
    return None


def parse_upload_date(app_details: ParsedJSON) -> float:
    """Parse upload date to POSIX timestamp

    :param dict app_details:
        App details section of meta data of Google Play Store page parses
        from JSON.
    :returns float:
        POSIX timestampt of upload date.
    """
    upload_date_string = app_details.get('uploadDate')
    if upload_date_string:
        return int(datetime.strptime(
            upload_date_string, '%b %d, %Y').timestamp())
    return None


def parse_google_play_info(package_name: str, play_details_dir: str) -> dict:
    """Select and format data from json_file to store in node.

    :param str package_name:
        Package name.
    :param str play_details_dir:
        Name of directory to include JSON files from. Filenames in this
        directory need to have .json extension. Filename without extension is
        assumed to be package name for details contained in file.
    :returns dict:
        Properties of a node represinting the Google Play page of an app.
    """
    def _parse_json_file(prefix: str) -> Tuple[dict, float]:
        """Return parsed JSON and mdate

        Uses prefix and package_name (from outer scope) to build path.
        """
        json_file_name = '{}.json'.format(package_name)
        json_file_path = os.path.join(prefix, json_file_name)
        if not os.path.exists(json_file_path):
            __log__.warning('Cannot read file: %s.', json_file_path)
            return {}, None
        with open(json_file_path) as json_file:
            return json.load(json_file), int(os.stat(json_file_path).st_mtime)

    meta_data, mtime = _parse_json_file(play_details_dir)
    category_data, category_mtime = _parse_json_file(os.path.join(
        play_details_dir, 'categories'))
    if not meta_data and not category_data:
        return None
    if not meta_data:
        meta_data = {'docId': package_name}
        mtime = category_mtime
    offer = meta_data.get('offer', [])
    if offer:
        formatted_amount = offer[0].get('formattedAmount')
        currency_code = offer[0].get('currencyCode')
    else:
        formatted_amount = None
        currency_code = None
    details = meta_data.get('details', {})
    app_details = details.get('appDetails', {})
    if category_data:
        categories = app_details.setdefault('appCategory', [])
        categories.append(category_data['appCategory'])
    aggregate_rating = meta_data.get('aggregateRating')
    if not aggregate_rating:
        aggregate_rating = {}

    return {
        'docId': meta_data.get('docId'),
        'uri': meta_data.get('shareUrl'),
        'snapshotTimestamp': mtime,
        'title': meta_data.get('title'),
        'appCategory': app_details.get('appCategory'),
        'promotionalDescription': meta_data.get('promotionalDescription'),
        'descriptionHtml': meta_data.get('descriptionHtml'),
        'translatedDescriptionHtml': meta_data.get('translatedDescriptionHtml'),
        'versionCode': app_details.get('versionCode'),
        'versionString': app_details.get('versionString'),
        'uploadDate': parse_upload_date(app_details),
        'formattedAmount': formatted_amount,
        'currencyCode': currency_code,
        'in-app purchases': describe_in_app_purchases(meta_data),
        'installNotes': app_details.get('installNotes'),
        'starRating': aggregate_rating.get('starRating'),
        'numDownloads': app_details.get('numDownloads'),
        'developerName': app_details.get('developerName'),
        'developerEmail': app_details.get('developerEmail'),
        'developerWebsite': app_details.get('developerWebsite'),
        'targetSdkVersion': app_details.get('targetSdkVersion'),
        'permissions':  app_details.get('permission')
        }


def get_latest_repo_name(meta_data: dict) -> Tuple[str, str]:
    """Determine the most recently used repository name.

    :param dict meta_data:
        Dictionary containing repository meta data. Needs to include
        `full_name`, `renamed_to` and `not_found`.
    :returns Tuple[str, str]:
        Tuple of original repository name and latest known repository
        name if available, otherwise None.
    """
    original_repo = meta_data['full_name']
    renamed_to = meta_data['renamed_to']
    not_found = meta_data['not_found'] == 'TRUE'
    if renamed_to:
        return original_repo, renamed_to
    elif not not_found:
        return original_repo, original_repo
    return original_repo, None


def parse_iso8601(timestamp: str) -> int:
    """Parse an ISO 8601 timestamp.

    Discards fractions of seconds if they are present.

    built-in datetime.strptime has no way of correctly parsing ISO 8601
    timestamps with timezone information.

    Example:
    >>> parse_iso8601('2015-03-27T19:25:23.000-08:00')
    1427513123
    >>> parse_iso8601('2014-02-27T15:05:06+01:00')
    1393509906
    >>> parse_iso8601('2008-09-03T20:56:35.450686Z')
    1220475395

    :param str timestamp:
        ISO 8601 formatted timestamp with timezone offset. Can but need not
        include milliseconds which get discared if present.
    :returns int:
        POSIX timestamp. Seconds since the epoch.
    :raises ValueError:
        if timestamp is malformed.
    """
    def _raise():
        raise ValueError(
            'Cannot parse malformed timestamp: {}'.format(timestamp))

    match = TIMESTAMP_PATTERN.match(timestamp)
    if match:
        naive, sign, offset, hours, minutes = match.groups()
    else:
        _raise()

    if sign == 'Z' and not offset:
        sign = '+'
        offset = '0000'
    elif sign in ['+', '-'] and offset:
        offset = hours + minutes
    else:
        _raise()

    date_time = datetime.strptime(naive + sign + offset, TIME_FORMAT)
    return int(date_time.timestamp())


def read_gitlab_import_results(gitlab_import_file: IO[str]):
    """Read CSV output from gitlab import.

     github_*.csv contains duplicate rows.
     Luca's script couldn't handle that and failed (because only one
     page of repositories was grepped) on the second row.
     Thus, duplicates still exist when parsing here, but the second
     entry for the same github repo does not contain gitlab info.
     Because we read everything into a dict, only information from the
     second row is stored.
     """
    gitlab_import = {}
    for row in csv.DictReader(gitlab_import_file):
        existing = gitlab_import.get(row['id'])
        if (
                row['clone_status'] != 'Success' and existing
                and existing['clone_status'] == 'Success'):
            __log__.info(
                'Skip repo %s: It has been read with status "Success" '
                'before and has status "%s" now.',
                row['id'], row['clone_status'])
            continue

        # Turn URL into path name of repository
        row['clone_project_path'] = os.path.basename(row['clone_project_url'])
        del row['clone_project_url']

        # Fixme: Which one is the better to store if neither of them is
        # 'Success'?
        if existing:
            for key in row:
                if existing[key] != row[key]:
                    __log__.error(
                        'Different value for key "%s" for repo %s. None is '
                        '"Success":\nold %s\nnew %s',
                        key, row['id'], existing, row)

        # Store the newer one. That might overwrite data if the new row
        # includes less data. We need to manually inspect these cases from the
        # logs.
        gitlab_import[row['id']] = row

    return gitlab_import


def consolidate_data(
        original_file: IO[str], gitlab_import_file: IO[str],
        mirrored_repos_file: IO[str], renamed_repos: Dict[str, dict],
        packages_by_repo: Dict[str, Set[str]]) -> Generator[dict, None, None]:
    """Combine information about repositories and packages

    :param IO[str] original_file:
        CSV file as created by subcommand 'get_repo_data' and augmented by
        subcommand 'add_gradle_info'. This original file is necessary because
        later versions have non ASCII characters wrongly encoded.
    :param IO[str] gitlab_import_file:
        CSV file generated by external script to import GitHub repositories to
        a local Gitlab instance. This file has the same content as
        'original_file' with some additional columns. Unfortunately, there is
        an encoding issue.
    :param IO[str] mirrored_repos_file:
        CSV file generated by subcommand 'mirror_empty_repos'. This file
        contains updated information on the snapshot repository in Gitlab.
    :param Dict[str, dict] renamed_repos:
        Mapping from GitHub IDs of repositories to repo and package data of
        repositories that have been renamed.
    :param Dict[str, Set[str]] packages_by_repo:
        A mapping from repository name to set of package names in that
        repository.
    :returns Generator[dict, None, None]:
        a generator of consolidated data rows.
    """

    def _correct_gitlab_data(row: dict, repo_names: Set[str]):
        found = False
        for name in repo_names:
            if name in mirrored_repos:
                new = mirrored_repos[name]
                clone_id = row.get('clone_project_id')
                if found and clone_id != row['clone_project_id']:
                    __log__.warning(
                        'Repository %s has a clone already. New: %s. Old: %s',
                        name, new, row)
                    continue
                for key in GITLAB_KEYS + ['clone_project_path']:
                    row[key] = new[key]
                row['clone_status'] = 'Success'
                found = True

    _used_repos = set()
    _used_packages = set()

    def _find_packages(github_id: str, repo_names: Set[str]) -> str:
        """Find packages for any of the repo_names.

        :param str github_id:
            ID of repository on GitHub.
        :param Set[str] repo_names:
            List of known names of repo.
        :returns str:
            Comma separated list of package names in this repository.
        """
        packages = set()
        for name in repo_names:
            if name in _used_packages:
                __log__.info('Repository has been used before: %s', name)
            if name in packages_by_repo:
                packages.update(packages_by_repo[name])
                _used_repos.add(name)
        if not packages and github_id in renamed_repos:
            packages_str = renamed_repos[github_id]['packages']
            if packages_str:  # Avoid adding the empty string
                packages.update(packages_str.split(','))
        _used_packages.update(packages)
        return ','.join(packages)

    def _log_unused_repos():
        known_repos = set(packages_by_repo.keys())
        if known_repos > _used_repos:
            __log__.warning(
                '%d repos are known but not used',
                len(known_repos) - len(_used_repos))
            with open('/tmp/unused_repos.csv', 'w') as tmp_file:
                writer = csv.writer(tmp_file)
                for repo in known_repos - _used_repos:
                    __log__.info(
                        'Known repo %s is not used (packages %s)',
                        repo, packages_by_repo[repo])
                    writer.writerow([repo, ','.join(packages_by_repo[repo])])

    def _log_unused_packages():
        known_packages = {
            p for ps in packages_by_repo.values() for p in ps}
        if known_packages > _used_packages:
            __log__.warning(
                '%d packages are left without repository',
                len(known_packages) - len(_used_packages))
            for package in known_packages - _used_packages:
                __log__.info('Known package is not used: %s', package)

    original = {
        row['id']: row
        for row in csv.DictReader(original_file)}

    gitlab_import = read_gitlab_import_results(gitlab_import_file)

    mirrored_repos = {
        row['github_full_name']: row
        for row in csv.DictReader(mirrored_repos_file)}

    if len(original) != len(gitlab_import):
        __log__.warning(
            'List lengths do not match: %d != %d', len(original),
            len(gitlab_import))

    for github_id, repo_data in original.items():
        combined = {}

        # Keep as many columns from original file as possible: It has the right
        # encoding.
        combined.update(repo_data)

        if github_id not in gitlab_import:
            __log__.warning(
                'ID %s is not in %s', github_id, gitlab_import_file.name)
        else:
            for key in ['full_name', 'renamed_to', 'not_found']:
                if repo_data[key] != gitlab_import[github_id][key]:
                    __log__.warning(
                        'Column %s for row with ID %s differs: "%s" vs "%s"',
                        key, github_id, repo_data[key],
                        gitlab_import[github_id][key])

            # Add information from initial import to Gitlab
            for key in GITLAB_KEYS + ['clone_status', 'clone_project_path']:
                combined[key] = gitlab_import[github_id][key]

        # Some repositories have been renamed
        repo_names = set(get_latest_repo_name(repo_data))

        # Reflect that some snapshot repositories had to be recreated.
        _correct_gitlab_data(combined, repo_names)

        # Add package names of apps which we know live in this repository
        combined['packages'] = _find_packages(github_id, repo_names)
        if not combined['packages']:
            __log__.warning(
                'No package for repository with ID %s: %s', github_id,
                ', '.join(repo_names))
            continue

        if not combined.get('clone_project_id'):
            __log__.warning(
                'Repository %s does not have a Gitlab ID: full_name: [%s], '
                'not_found: [%s], renamed_to: [%s]',
                github_id, combined['full_name'], combined['not_found'],
                combined['renamed_to'])
            continue
        yield combined

    _log_unused_repos()
    _log_unused_packages()
    __log__.info(
        'Packages in set: %d. Repositories in set: %d',
        len(_used_packages), len(_used_repos))
