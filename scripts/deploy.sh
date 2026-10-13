#!/bin/bash
# deploy.sh - ONE command that creates everything for HW4 and starts both services:
#   * APIs, two least-privilege service accounts and their IAM bindings
#   * Pub/Sub topic + subscription, static external IP, firewall rule for port 80
#   * VM 1 "hw4-web"      (e2-micro, static IP)  -> web server starts at boot
#   * VM 2 "hw4-listener" (e2-micro)             -> forbidden listener starts at boot
#
# Usage (from Cloud Shell, inside the cloned repo):
#   PROJECT=my-project BUCKET=my-bucket ./scripts/deploy.sh
# All settings below can be overridden the same way (REGION, ZONE, REPO, ...).
# Safe to re-run: anything that already exists is kept.
set -euo pipefail

PROJECT=${PROJECT:-$(gcloud config get-value project 2>/dev/null)}
BUCKET=${BUCKET:-cedar-pottery-508921-u1-pages}
PREFIX=${PREFIX:-pages/}
REGION=${REGION:-us-central1}
ZONE=${ZONE:-us-central1-a}
REPO=${REPO:-https://github.com/Avaneesh-Moorthy/cloud-hw4.git}
WEB_TYPE=${WEB_TYPE:-e2-micro}
LISTENER_TYPE=${LISTENER_TYPE:-e2-micro}
TOPIC=hw4-forbidden
SUB=hw4-forbidden-sub
WEB_SA=hw4-web-server@$PROJECT.iam.gserviceaccount.com
LIS_SA=hw4-listener@$PROJECT.iam.gserviceaccount.com
HERE=$(cd "$(dirname "$0")" && pwd)

say() { echo; echo "==> $*"; }
exists() { "$@" >/dev/null 2>&1; }
gcloud config set project "$PROJECT" >/dev/null

say "1/7 Enabling APIs"
gcloud services enable compute.googleapis.com pubsub.googleapis.com logging.googleapis.com \
  monitoring.googleapis.com iam.googleapis.com

say "2/7 Service accounts"
exists gcloud iam service-accounts describe "$WEB_SA" || \
  gcloud iam service-accounts create hw4-web-server --display-name="HW4 web server VM"
exists gcloud iam service-accounts describe "$LIS_SA" || \
  gcloud iam service-accounts create hw4-listener --display-name="HW4 forbidden listener VM"
sleep 10   # let new accounts propagate before granting roles

say "3/7 Pub/Sub topic and subscription"
exists gcloud pubsub topics describe $TOPIC || gcloud pubsub topics create $TOPIC
exists gcloud pubsub subscriptions describe $SUB || \
  gcloud pubsub subscriptions create $SUB --topic=$TOPIC

say "4/7 Least-privilege IAM (each role only on the one resource it needs)"
# web server: read the pages, publish forbidden requests, write its logs
gcloud storage buckets add-iam-policy-binding gs://$BUCKET \
  --member=serviceAccount:$WEB_SA --role=roles/storage.objectViewer --quiet >/dev/null
gcloud pubsub topics add-iam-policy-binding $TOPIC \
  --member=serviceAccount:$WEB_SA --role=roles/pubsub.publisher --quiet >/dev/null
gcloud projects add-iam-policy-binding $PROJECT --condition=None \
  --member=serviceAccount:$WEB_SA --role=roles/logging.logWriter --quiet >/dev/null
# listener: pull forbidden messages, append them to a log file in the bucket
gcloud pubsub subscriptions add-iam-policy-binding $SUB \
  --member=serviceAccount:$LIS_SA --role=roles/pubsub.subscriber --quiet >/dev/null
gcloud storage buckets add-iam-policy-binding gs://$BUCKET \
  --member=serviceAccount:$LIS_SA --role=roles/storage.objectUser --quiet >/dev/null

say "5/7 Static IP and firewall"
exists gcloud compute addresses describe hw4-web-ip --region=$REGION || \
  gcloud compute addresses create hw4-web-ip --region=$REGION
IP=$(gcloud compute addresses describe hw4-web-ip --region=$REGION --format='value(address)')
exists gcloud compute firewall-rules describe hw4-allow-http || \
  gcloud compute firewall-rules create hw4-allow-http --network=default --direction=INGRESS \
    --allow=tcp:80 --source-ranges=0.0.0.0/0 --target-tags=hw4-web

say "6/7 VM hw4-web ($WEB_TYPE, static IP $IP)"
exists gcloud compute instances describe hw4-web --zone=$ZONE || \
  gcloud compute instances create hw4-web --zone=$ZONE --machine-type=$WEB_TYPE \
    --image-family=debian-12 --image-project=debian-cloud \
    --service-account=$WEB_SA --scopes=cloud-platform \
    --address=$IP --tags=hw4-web \
    --metadata=repo=$REPO,bucket=$BUCKET,prefix=$PREFIX,topic=projects/$PROJECT/topics/$TOPIC \
    --metadata-from-file=startup-script=$HERE/startup_web.sh

say "7/7 VM hw4-listener ($LISTENER_TYPE)"
exists gcloud compute instances describe hw4-listener --zone=$ZONE || \
  gcloud compute instances create hw4-listener --zone=$ZONE --machine-type=$LISTENER_TYPE \
    --image-family=debian-12 --image-project=debian-cloud \
    --service-account=$LIS_SA --scopes=cloud-platform \
    --metadata=repo=$REPO,bucket=$BUCKET,subscription=$SUB \
    --metadata-from-file=startup-script=$HERE/startup_listener.sh

say "Done. The startup scripts need ~2-3 minutes to install and start the services."
echo "Web server:  http://$IP/123.html"
echo "Check:       curl -s -o /dev/null -w '%{http_code}\n' http://$IP/123.html"
echo "Listener:    gcloud compute ssh hw4-listener --zone=$ZONE --command='sudo journalctl -u hw4-listener -f'"
