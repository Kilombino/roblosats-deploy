#!/bin/sh
# docker compose for Kilobot: ./kilobot.sh up -d | ps | logs -f robosats ...
cd "$(dirname "$0")" && exec docker compose -p kilobot --env-file env/kilobot/compose.env \
  -f docker-compose.yml -f docker-compose.override-kilobot.yml "$@"
