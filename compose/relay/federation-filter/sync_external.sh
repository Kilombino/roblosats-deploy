#!/bin/sh
# Like the image's sync_external.sh, but order events (38383) are only synced for the
# coordinators in /etc/strfry/allowed-order-pubkeys.txt (the write policy rejects the
# rest anyway; filtering here avoids downloading them again on every run).

authors=$(sed 's/#.*//' /etc/strfry/allowed-order-pubkeys.txt 2>/dev/null | grep -oE '^[[:space:]]*[0-9a-fA-F]{64}' | tr -d ' \t' | sed 's/.*/"&"/' | paste -sd, -)
if [ -n "$authors" ]; then authors_json=",\"authors\":[$authors]"; else authors_json=""; fi

filters_sync="{\"kinds\":[38383]${authors_json},\"since\":$(date -d "2 weeks ago" +%s)}"
timeout_duration="15s"

while IFS= read -r line; do
  timeout "$timeout_duration" /app/strfry --config /etc/strfry.conf sync ${line} --filter "$filters_sync" --dir both
done < /app/external_urls.txt
