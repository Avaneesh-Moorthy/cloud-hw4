#!/bin/bash
# teardown.sh - deletes the VMs and the static IP so they stop costing money.
# (Service accounts, Pub/Sub and the firewall rule cost nothing and are kept.)
ZONE=${ZONE:-us-central1-a}; REGION=${REGION:-us-central1}
gcloud compute instances delete hw4-web hw4-listener hw4-client --zone=$ZONE --quiet
gcloud compute addresses delete hw4-web-ip --region=$REGION --quiet
gcloud compute instances list
