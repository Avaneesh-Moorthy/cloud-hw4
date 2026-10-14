#!/bin/bash
# Creates the CLIENT VM (separate from the server) and copies the provided
# Linux http-client onto it. The client VM needs no Google permissions at all,
# so it runs with NO service account. Ubuntu 24.04 is used because the provided
# client binary needs GLIBC >= 2.38 (Debian 12 only has 2.36).
# Usage: ./scripts/create_client_vm.sh ~/http-client
set -euo pipefail
CLIENT_BIN=${1:?path to the linux http-client binary}
ZONE=${ZONE:-us-central1-a}
TYPE=${CLIENT_TYPE:-e2-small}
gcloud compute instances describe hw4-client --zone=$ZONE >/dev/null 2>&1 || \
  gcloud compute instances create hw4-client --zone=$ZONE --machine-type=$TYPE \
    --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
    --no-service-account --no-scopes
sleep 20
gcloud compute scp "$CLIENT_BIN" hw4-client:~/http-client --zone=$ZONE
gcloud compute ssh hw4-client --zone=$ZONE --command='chmod +x ~/http-client && ~/http-client -h | head -3'
