#!/bin/sh
# docker compose for a Roblosats coordinator: ./coordinator.sh <alias> up -d | ps | logs -f robosats ...
# Expects env/<alias>/compose.env (see env-sample/roblosats) and the override docker-compose.override-kilobot.yml.
A="$1"; shift
cd "$(dirname "$0")" && exec docker compose -p "$A" --env-file "env/$A/compose.env" \
  -f docker-compose.yml -f docker-compose.override-kilobot.yml "$@"
