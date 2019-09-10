#! /usr/bin/env sh

[[ ${DEBUG} == "true" ]] && set -x
: ${HTTP_PORT:=8000} # default port on 8000

BASE_DIR=$(dirname $(dirname $0))

docker build -t skshetry/whisky $BASE_DIR

# do not provide more than 500 MB memory, possible memory leak
echo "Starting server in docker in port $HTTP_PORT ..."
docker run --rm -p $HTTP_PORT:8000 -m 500m skshetry/whisky:latest