#!/usr/bin/env bash
set -euo pipefail
CTN="${WAZUH_CONTAINER:-single-node-wazuh.manager-1}"
docker exec -it "$CTN" /var/ossec/bin/wazuh-analysisd -t
docker exec -it "$CTN" /var/ossec/bin/wazuh-control restart
