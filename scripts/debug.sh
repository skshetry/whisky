#! /usr/bin/env sh

[[ ${DEBUG} == "true" ]] && set -x

BASE_DIR=$(dirname $(dirname $0))

docker build -t skshetry/whisky $BASE_DIR

# do not provide more than 500 MB memory, possible memory leak
docker run --rm -p 5000:8000 -m 500m skshetry/whisky:latest