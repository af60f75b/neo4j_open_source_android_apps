"""Convenience methods for creation of nodes and relations.

Example:
>>> with Neo4j('bolt://localhost', 'test_user', 'password') as neo4j:
>>>     greeting = neo4j.create_node(
>>>         'Greeting', formal='Good evening', informal='Whatzzup?')
>>>     print(greeting.get('formal'))
'Good evening'
"""

from neo4j.v1 import GraphDatabase, Session, StatementResult
from neo4j.v1 import Node, Relationship


class Neo4j(object):
    """Convenience wrapper for neo4j.v1.GraphDatabase.

    :param str uri:
        URI of the database.
    :param str user:
        Username for authenticating against Neo4j instance.
    :param str password:
        Password for authenticating against Neo4j instance.
    :param int port:
        Port number. Default: 7687.
    """
    def __init__(self, uri: str, user: str, password: str, port: int = 7687):
        self._driver = GraphDatabase.driver(
            '{}:{}'.format(uri, port), auth=(user, password))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._driver.close()

    def session(self) -> Session:
        """Create a new session.

        See neo4j.v1.Driver.session() for details.

        :returns neo4j.v1.Session:
            new Session object.
        """
        return self._driver.session()

    def run(self, query: str, **kwargs) -> StatementResult:
        """Execute a query.

        Opens a new session and runs query on it with **kwargs used for
        parameter substition.

        :param str query:
            Query to execute. May contain variables enclosed in curly braces
            for variable substitution.
        :param kwargs:
            Keywoard arguments used for variable substitution in query.
        :returns neo4j.v1.StatementResult:
            the result.
        """
        with self.session() as session:
            return session.run(query, parameters=kwargs)

    def create_node(self, label: str, **kwproperties) -> Node:
        """Create a new node.

        :param str label:
            Label to be used for new node.
        :param kwproperties:
            Keywoard properties to be added to the new node.
        :returns neo4j.v1.Node:
            the newly created node.
        """
        query = '''
            CREATE (a:{label} {{properties}})
            RETURN a
            '''.format(label=label)
        result = self.run(query, properties=kwproperties)
        return result.single()[0]

    def create_relationship(
            self, label: str, from_id: int, to_id: int,
            **kwproperties) -> Relationship:
        """Create a new relationship between two nodes..

        :param str label:
            Label to be used for new relationship.
        :param int from_id:
            ID of source node of relationship.
        :param int to_id:
            ID or target node of relationship.
        :param kwproperties:
            Keywoard properties to be added to the relationship.
        :returns neo4j.v1.Relationship:
            the newly created relationship.
        """
        query = '''
            MATCH (a), (b)
            WHERE id(a)={{id_a}} AND id(b)={{id_b}}
            CREATE (a)-[r:{label} {{properties}}]->(b)
            RETURN r
            '''.format(label=label)
        result = self.run(
            query, id_a=from_id, id_b=to_id, properties=kwproperties)
        return result.single()[0]

    def get_node_by_id(self, node_id: int) -> Node:
        """Get an existing node by ID.

        :param int from_id:
            ID of source node of relationship.
        :returns neo4j.v1.Node:
            the matching node it it exists, otherwise None.
        """
        query = 'MATCH (node) WHERE id(node) = {node_id}'
        result = self.run(query, node_id=node_id)
        return result.single()[0] if result else None
