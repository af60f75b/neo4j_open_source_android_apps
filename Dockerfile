FROM neo4j:3.3

# Install dependencies
RUN apk add --no-cache --quiet \
        git \
        python3 \
    && pip3 install --no-cache-dir --upgrade \
        pip \
        setuptools \
        neo4j-driver==1.5.0

# Copy installation scripts and data into the container
ADD scripts /tmp/install
ADD data /tmp/data

# Import data into Neo4j
RUN /tmp/install/import.sh

# Clean up
RUN pip3 uninstall -y \
        setuptools \
        pip \
        neo4j-driver \
    && apk del --no-cache --quiet --purge \
        python3 \
        git \
    && rm -rf /tmp

# This is used to restore a dump of the database when
# running the container. The entry point of the parent
# image (/docker-entrypoint.sh) sources the script
# specified in EXTENSION_SCRIPT.
COPY scripts/load_db.sh /var/persist_graph/load_db.sh
ENV EXTENSION_SCRIPT=/var/persist_graph/load_db.sh
