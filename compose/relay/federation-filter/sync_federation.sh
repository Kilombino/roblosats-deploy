#!/bin/sh
# Like the image's sync_federation.sh, but kept to this relay's own federation
# (coordinators in /etc/strfry/allowed-order-pubkeys.txt):
#  - pass 1: order events (38383) signed by those coordinators;
#  - pass 2: ratings (31986) of those coordinators, plus gift wraps (1059) only if the
#    file has 1059 in its "sync-kinds" line (they carry no federation mark, so a peer
#    relay that also syncs with another federation would hand us that federation's).

CONF=/etc/strfry/allowed-order-pubkeys.txt
authors=$(sed 's/#.*//' $CONF 2>/dev/null | grep -oE '^[[:space:]]*[0-9a-fA-F]{64}' | tr -d ' \t' | sed 's/.*/"&"/' | paste -sd, -)
synckinds=$(sed 's/#.*//' $CONF 2>/dev/null | sed -n 's/^[[:space:]]*sync-kinds[[:space:]]*//p')
since=$(date -d "4 weeks ago" +%s)
if [ -z "$authors" ]; then
  filters_orders=""
  filters_other="{\"kinds\":[38383,31986,1059],\"since\":$since}"
else
  filters_orders="{\"kinds\":[38383],\"authors\":[$authors],\"since\":$since}"
  if echo " $synckinds " | grep -q " 1059 "; then
    filters_other="{\"kinds\":[31986,1059],\"since\":$since}"
  else
    filters_other="{\"kinds\":[31986],\"#p\":[$authors],\"since\":$since}"
  fi
fi
filter_delete="{\"until\":$since}"
timeout_duration="15s"

timeout "$timeout_duration" /app/strfry --config /etc/strfry.conf delete --filter "$filter_delete"

while IFS= read -r line; do
  [ -n "$filters_orders" ] && timeout "$timeout_duration" /app/strfry --config /etc/strfry.conf sync ${line} --filter "$filters_orders" --dir both
  timeout "$timeout_duration" /app/strfry --config /etc/strfry.conf sync ${line} --filter "$filters_other" --dir both
done < /app/federation_urls.txt
