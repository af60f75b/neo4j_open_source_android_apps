"""Store information in Neo4j graph database.

Use -h or --help for more information.
"""
import argparse
import csv
import logging
import os
from typing import Dict, IO, List

from util.neo4j import Neo4j, Node
from util.parse import \
    parse_google_play_info, \
    parse_iso8601


__log__ = logging.getLogger(__name__)


NEO4J_HOST = 'bolt://localhost'
NEO4J_PORT = 7687
GITLAB_HOST = 'http://145.108.225.21'
GITLAB_REPOSITORY_PATH = '/var/opt/gitlab/git-data/repositories/gitlab'


def add_google_play_page_node(
        package_name: str, neo4j: Neo4j, play_details_dir: str) -> Node:
    """Create a node for an Google Play page.

    Meta data of Google Play page is loaded from JSON file at
    <play_details_dir>/<package_name>.json

    :param str package_name:
        Package name.
    :param Neo4j neo4j:
        Neo4j instance to add nodes to.
    :param str play_details_dir:
        Name of directory to include JSON files from. Filenames in this
        directory need to have .json extension. Filename without extension is
        assumed to be package name for details contained in file.
    :return Node:
        Node created for Google Play page if JSON file exists, otherwise None.
    """
    google_play_info = parse_google_play_info(package_name, play_details_dir)
    if not google_play_info:
        __log__.warning('Cannot create GooglePlayPage node %s.', package_name)
        return None
    __log__.info('Create GooglePlayPage node for %s.', package_name)
    return neo4j.create_node('GooglePlayPage', **google_play_info)


def format_repository_data(meta_data: dict, snapshot: dict) -> dict:
    """Format repository data for insertion into Neo4j.

    :param dict meta_data:
        Meta data of Google Play Store page parses from JSON.
    :param dict snapshot:
        Information about Gitlab project that hosts snapshot of the repository.
    :returns dict:
        A dictionary of properties of the node to create.
    """
    if snapshot.get('created_at'):
        timestamp = parse_iso8601(snapshot.get('created_at'))
    else:
        timestamp = None
    return {
        'id': meta_data['id'],
        'owner': meta_data['owner_login'],
        'name': meta_data['name'],
        'snapshot': snapshot.get('web_url'),
        'snapshotTimestamp': timestamp,
        'description': meta_data['description'],
        'createdAt': meta_data['created_at'],
        'forksCount': meta_data['forks_count'],
        'stargazersCount': meta_data['stargazers_count'],
        'subscribersCount': meta_data['subscribers_count'],
        'watchersCount': meta_data['watchers_count'],
        'networkCount': meta_data['network_count'],
        'ownerType': meta_data['owner_type'],
        'parentId': meta_data['parent_id'],
        'sourceId': meta_data['source_id']
        }


def add_fork_relationships(neo4j: Neo4j):
    """Add FORK_OF relationships between existing GitHubRepository entities.

    :param Neo4j neo4j:
        Neo4j instance to add nodes to.
    """
    query = '''
        MATCH (fork:GitHubRepository), (parent:GitHubRepository)
        WHERE fork.parentId = parent.id OR fork.sourceId = parent.id
        CREATE (fork)-[:FORKS]->(parent)
        '''
    neo4j.run(query)


def add_repository_node(
        meta_data: dict, snapshots: List[dict], neo4j: Neo4j) -> Node:
    """Add a repository and link it to all apps imnplemented by it.

    Does not do anything if packages_names is empty or no :App node exists
    with a matching package name.

    :param dict meta_data:
        Meta data of Google Play Store page parses from JSON.
    :param List[Dict[str, str]] snapshots:
        List of snapshots data. Must be length 1.
    :param Neo4j neo4j:
        Neo4j instance to add nodes to.
    :returns Node:
        The node created for the repository.
    """
    snapshot = snapshots[0] if snapshots else {}
    repo_data = format_repository_data(meta_data, snapshot)
    query = '''
        CREATE (repo:GitHubRepository {repo_properties})
        RETURN repo
        '''
    result = neo4j.run(query, repo_properties=repo_data)
    return result.single()[0]


def add_tag_nodes(tags: List[dict], repo_node_id: int, neo4j: Neo4j):
    """Create nodes representing GIT tags of a repository.

    Creates a node for each tag and links it with the repository identified
    by repo_node_id and the commit the tag points to.

    :param List[Dict[str, str]] tags:
        List of tag data.
    :param int repo_node_id:
        ID of node the tags should be linked to.
    :param Neo4j neo4j:
        Neo4j instance to add nodes to.
    """
    for tag in tags:
        parameters = {
            'commit_hash': tag.get('commit_hash'),
            'repo_id': repo_node_id,
            'tag_details': {
                'name': tag.get('tag_name'),
                'message': tag.get('tag_message'),
                },
            }

        neo4j.run(
            '''
            MATCH (repo:GitHubRepository) WHERE id(repo) = {repo_id}
            MERGE (commit:Commit {id: {commit_hash}})
            CREATE
                (tag:Tag {tag_details})-[:BELONGS_TO]->(repo),
                (tag)-[:POINTS_TO]->(commit)
            ''', **parameters)


def add_branche_nodes(branches: List[dict], repo_node_id: int, neo4j: Neo4j):
    """Create nodes representing GIT branches of a repository.

    Creates a node for each branch and links it with the repository identified
    by repo_node_id and the commit the branch points to.

    :param List[Dict[str, str]] branches:
        List of information on branches.
    :param int repo_node_id:
        ID of node the branches should be linked to.
    :param Neo4j neo4j:
        Neo4j instance to add nodes to.
    """
    for branch in branches:
        parameters = {
            'commit_hash': branch.get('commit_hash'),
            'repo_id': repo_node_id,
            'branch_details': {
                'name': branch.get('branch_name'),
                },
            }

        neo4j.run(
            '''
            MATCH (repo:GitHubRepository) WHERE id(repo) = {repo_id}
            MERGE (commit:Commit {id: {commit_hash}})
            CREATE
                (branch:Branch {branch_details})-[:BELONGS_TO]->(repo),
                (branch)-[:POINTS_TO]->(commit)
            ''', **parameters)


def add_commit_nodes(commits: List[dict], repo_node_id: int, neo4j: Neo4j):
    """Create nodes representing GIT commits of a repository.

    Creates a node for each commit and links it with  the repository identified
    by repo_node_id.

    Also creates relationships to author, committer and parent commits. Creates
    each of these in turn unless they exist already.

    :param List[Dict[str, str]] commits:
        List of data of commits.
    :param int repo_node_id:
        ID of node the commits should be linked to.
    :param Neo4j neo4j:
        Neo4j instance to add nodes to.
    """
    for commit in commits:
        parameters = {
            'repo_id': repo_node_id,
            'commit': {
                'id': commit.get('id'),
                'short_id': commit.get('short_id'),
                'title': commit.get('title'),
                'message': commit.get('message'),
                'additions': commit.get('additions'),
                'deletions': commit.get('deletions'),
                'total': commit.get('total'),
                },
            'author': {
                'email': commit.get('author_email'),
                'name': commit.get('author_name'),
                },
            'committer': {
                'email': commit.get('committer_email'),
                'name': commit.get('committer_name'),
                },
            'authored_date': commit.get('authored_date'),
            'committed_date': commit.get('committed_date'),
            }

        neo4j.run(
            '''
            MATCH (repo:GitHubRepository) WHERE id(repo) = {repo_id}
            MERGE (commit:Commit {id: {commit}.id})
                ON CREATE SET commit = {commit}
                ON MATCH SET commit += {commit}
            MERGE (author:Contributor {email: {author}.email})
                ON CREATE SET author = {author}
                ON MATCH SET author += {author}
            MERGE (committer:Contributor {email: {committer}.email})
                ON CREATE SET committer = {committer}
                ON MATCH SET committer += {committer}
            CREATE
                (commit)-[:BELONGS_TO]->(repo),
                (author)-[:AUTHORS {timestamp: {authored_date}}]->(commit),
                (committer)-[:COMMITS {timestamp: {committed_date}}]->(commit)
            ''', **parameters)

        for parent in commit.get('parent_ids').split(','):
            neo4j.run(
                '''
                MATCH (c:Commit {id: {child}})
                MERGE (p:Commit {id: {parent}})
                CREATE (c)-[:PARENT]->(p)
                ''', parent=parent, child=commit.get('id'))

        __log__.debug('Created commit %s', parameters['commit']['id'])


def add_paths_property(
        properties: dict, repo_node_id: int, package_name: str, neo4j: Neo4j):
    """Add path names as properties based on search.

    Search a git repository and add file names which contain matches to an
    :IMPLEMENTED_BY relationship matched agains package_name and repoe_node_id.

    :param dict properties:
        Mapping of property name to propertie values to be added to
        relationship.
    :param int repo_node_id:
        Identifier for :GitHubRepository node which the :IMPLEMENTED_BY
        relationship points to.
    :param str package_name:
        Package name of :App node.
    :param Neo4j neo4j:
        Neo4j instance to add nodes to.
    """
    parameters = {
        'package': package_name,
        'repo_id': repo_node_id,
        'rel_properties': properties,
        }
    query = '''
        MATCH
            (a:App {id: {package}}), (repo:GitHubRepository)
        WHERE id(repo) = {repo_id}
        MERGE (a)-[r:IMPLEMENTED_BY]->(repo)
        ON CREATE SET r = {rel_properties}
        ON MATCH SET r += {rel_properties}
        '''
    neo4j.run(query, **parameters)


def add_implementation_properties(
        properties: List[dict], repo_node_id: int, packages: List[str],
        neo4j: Neo4j):
    """Add properties to IMPLEMENTED_BY relationship.

    Find Android manifest files and build system files for app in the
    repository and add their paths as properties to the IMPLEMENTED_BY
    relationship.

    :param List[Dict[str, str]] properties:
        A list of dictionaries. Each has a key 'package' and other keys that
        need to be added to a relation with that package.
    :param int repo_node_id:
        ID of node representing the repository.
    :param List[str] packages:
        A list of package names to be connected with the repository identified
        by repo_node_id.
    :param Neo4j neo4j:
        Neo4j instance to add nodes to.
    """
    if {pp['package'] for pp in properties} != set(packages):
        __log__.error(
            'Packages stored with paths do not match. '
            'Original: %s. Properties: %s', packages, properties)
        # Create empty IMPLEMENTED_BY relations to make sure all packages are
        # connected.
        for package in packages:
            add_paths_property({}, repo_node_id, package, neo4j)

    for attr in properties:
        package = attr['package']
        del attr['package']
        add_paths_property(attr, repo_node_id, package, neo4j)


def read_csv(prefix: str, filename: str) -> List[Dict[str, str]]:
    """List of all rows of a CSV file as dictionaries.

    :param str prefix:
        Directory of CSV file.
    :param str filename:
        Filename of CSV file.
    :returns List[Dict[str, str]]:
        List of rows of CSV file as dictionaries.
    """
    path = os.path.join(prefix, filename)
    with open(path) as csv_file:
        csv_reader = csv.DictReader(csv_file)
        return list(csv_reader)


def add_repository_info(
        csv_file: IO[str], play_details_dir: str, neo4j: Neo4j,
        repo_details_dir: str):
    """Add data of GIT repositories to Neo4j.

    :param IO[str] csv_file:
        CSV file containing meta data of repositories.
    :param str play_details_dir:
        Name of directory to include JSON files from. Filenames in this
        directory need to have .json extension. Filename without extension is
        assumed to be package name for details contained in file.
    :param Neo4j neo4j:
        Neo4j instance to add nodes to.
    :param str repo_details_dir:
        Path in which CSV files with repository details, such as commits,
        branches, etc are stored.
    """
    csv_reader = csv.DictReader(csv_file)
    for row in csv_reader:
        __log__.info('Create repo info: %s', (
            row['id'], row['full_name'],
            row['clone_project_id'], row['clone_project_path']))
        packages = row['packages'].split(',')
        __log__.info('Found packages: %s', packages)
        add_app_data(packages, play_details_dir, neo4j)

        path = os.path.join(repo_details_dir, row['id'])

        snapshots = read_csv(path, 'snapshot.csv')
        node = add_repository_node(row, snapshots, neo4j)
        __log__.info('Created :GitHubRepository node with id %d', node.id)
        add_commit_nodes(read_csv(path, 'commits.csv'), node.id, neo4j)
        __log__.info('Created :Commit nodes')
        add_branche_nodes(read_csv(path, 'branches.csv'), node.id, neo4j)
        __log__.info('Created :Branch nodes')
        add_tag_nodes(read_csv(path, 'tags.csv'), node.id, neo4j)
        __log__.info('Created :Tag nodes')
        add_implementation_properties(
            read_csv(path, 'paths.csv'), node.id, packages, neo4j)
    add_fork_relationships(neo4j)


def add_app_data(packages: List[str], play_details_dir: str, neo4j: Neo4j):
    """Create nodes and relationships for Android apps.

    :param List[str] packages:
        List of package names to create :App and :GooglePlayPage nodes for.
    :param str play_details_dir:
        Name of directory to include JSON files from. Filenames in this
        directory need to have .json extension. Filename without extension is
        assumed to be package name for details contained in file.
    :param Neo4j neo4j:
        Neo4j instance to add nodes to.
    """
    for package in packages:
        __log__.info(
            'Add :GooglePlayPage and :App nodes for package: %s', package)
        add_google_play_page_node(package, neo4j, play_details_dir)
        neo4j.run(
            '''MERGE (g:GooglePlayPage {docId: {package}})
            CREATE (a:App {id: {package}})-[:PUBLISHED_AT]->(g)''',
            package=package)


def define_cmdline_arguments(parser: argparse.ArgumentParser):
    """Add arguments to parser."""
    parser.add_argument(
        'PLAY_STORE_DETAILS_DIR', type=str,
        help='Directory containing JSON files with details from Google Play.')
    parser.add_argument(
        'REPO_DETAILS_DIR', type=str,
        help='Directory containing CSV files with details from repositories.')
    parser.add_argument(
        'REPOSITORY_LIST', type=argparse.FileType('r'),
        help='''CSV file that lists meta data for repositories and their
        snapshots on Gitlab.''')
    parser.add_argument(
        '--neo4j-host', type=str, default=NEO4J_HOST,
        help='''Hostname Neo4j instance is running on. Default:
        {}'''.format(NEO4J_HOST))
    parser.add_argument(
        '--neo4j-port', type=int, default=NEO4J_PORT,
        help='Port number of Neo4j instance. Default: {}'.format(NEO4J_PORT))
    parser.set_defaults(func=_main)


def _main(args: argparse.Namespace):
    """Pass arguments to respective function."""
    __log__.info('------- Arguments: -------')
    __log__.info('PLAY_STORE_DETAILS_DIR: %s', args.PLAY_STORE_DETAILS_DIR)
    __log__.info('REPO_DETAILS_DIR: %s', args.REPO_DETAILS_DIR)
    __log__.info('REPOSITORY_LIST: %s', args.REPOSITORY_LIST.name)
    __log__.info('--neo4j-host: %s', args.neo4j_host)
    __log__.info('--neo4j-port: %d', args.neo4j_port)
    __log__.info('------- Arguments end -------')

    neo4j_user = ''
    neo4j_password = ''

    with Neo4j(NEO4J_HOST, neo4j_user, neo4j_password, NEO4J_PORT) as neo4j:
        add_repository_info(
            args.REPOSITORY_LIST, args.PLAY_STORE_DETAILS_DIR, neo4j,
            args.REPO_DETAILS_DIR)
