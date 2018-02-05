#/bin/bash
#
# Imports data into Neo4j graph database

set -e
set -u

# Start Neo4j in background
export NEO4J_AUTH=none
/docker-entrypoint.sh neo4j &
PID_NEO4J_SCRIPT="$!"

echo "Wait for Neo4j at port 7474"
while ! nc -z localhost 7474; do
    sleep 1
done
echo "Port 7474 is available. Continue."

# Import data by python script
python3 /tmp/install/gh_android_apps.py -v store_in_neo4j \
    /tmp/data/package_details/ \
    /tmp/data/repository_details/ \
    /tmp/data/repositories.csv

# Stop Neo4j background job
kill -s SIGTERM ${PID_NEO4J_SCRIPT}
wait

# Persist DB
neo4j-admin dump --database=graph.db --to=/var/persist_graph/android_apps.dump

# Clean up
rm -rf /logs/*
