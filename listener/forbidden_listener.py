"""
Service 2 - forbidden-country listener (HW3's second service, reused in HW4).

In HW4 it runs on its own VM, started automatically at boot by a systemd unit.
On the VM no --service-account is given: it authenticates as the VM's own
service account through the metadata server. On a laptop, pass
--service-account to impersonate it with short-lived tokens (HW3 setup).

Pulls "forbidden request" messages that service 1 publishes to Pub/Sub,
prints an error message for each one to standard output, and appends the
same message to a log file in the bucket:
    gs://<bucket>/forbidden_logs/forbidden_requests.log

Authentication: it acts as the SAME service account as service 1, by
impersonation, with no key file:
    every ~50 minutes it asks the gcloud CLI for a short-lived (1 hour)
    access token for the service account:
        gcloud auth print-access-token --impersonate-service-account=SA
    gcloud uses my own login (gcloud auth login) and the IAM Credentials
    API to mint the token. This only works because my user account was
    given roles/iam.serviceAccountTokenCreator on that one service account.
    Every Pub/Sub and Storage call is then made AS the service account,
    with exactly its permissions. No "gcloud auth application-default login"
    and no downloaded keys.

Run:
    python3 forbidden_listener.py \
        --project cedar-pottery-508921-u1 \
        --service-account hw3-file-server@cedar-pottery-508921-u1.iam.gserviceaccount.com
"""

import argparse
import datetime
import json
import subprocess
import time

import google.auth.credentials
from google.api_core import exceptions
from google.cloud import pubsub_v1, storage


class GcloudImpersonatedCredentials(google.auth.credentials.Credentials):
    """google-auth credentials whose token comes from
    `gcloud auth print-access-token --impersonate-service-account=...`."""

    def __init__(self, service_account):
        super().__init__()
        self.service_account = service_account

    def refresh(self, request):
        out = subprocess.run(
            ["gcloud", "auth", "print-access-token",
             f"--impersonate-service-account={self.service_account}"],
            check=True, capture_output=True, text=True)
        self.token = out.stdout.strip().splitlines()[-1]
        # Tokens live 60 min; refresh well before that. google-auth expects naive UTC.
        self.expiry = (datetime.datetime.now(datetime.timezone.utc)
                       + datetime.timedelta(minutes=50)).replace(tzinfo=None)


def append_to_bucket(bucket, object_name, line, retries=5):
    """Cloud Storage objects cannot be edited in place, so 'append' =
    read the current file, add the line, write it back. The write uses a
    generation precondition, so if something else changed the file in the
    meantime the write is rejected and we retry instead of losing a line."""
    blob = bucket.blob(object_name)
    for _ in range(retries):
        try:
            blob.reload()
            current, gen = blob.download_as_text(), blob.generation
        except exceptions.NotFound:
            current, gen = "", 0          # 0 = "only if the object doesn't exist yet"
        try:
            blob.upload_from_string(current + line + "\n", content_type="text/plain",
                                    if_generation_match=gen)
            return
        except exceptions.PreconditionFailed:
            time.sleep(0.5)
    raise RuntimeError("could not append to log file")


def main():
    ap = argparse.ArgumentParser(description="Listen for forbidden-country requests.")
    ap.add_argument("--project", required=True)
    ap.add_argument("--service-account", default="",
                    help="laptop only: service account to impersonate (omit on a VM)")
    ap.add_argument("--subscription", default="hw4-forbidden-sub")
    ap.add_argument("--bucket", default="cedar-pottery-508921-u1-pages")
    ap.add_argument("--log-object", default="forbidden_logs/hw4_forbidden_requests.log",
                    help="also append messages to this bucket object ('' to disable)")
    args = ap.parse_args()

    if args.service_account:
        creds = GcloudImpersonatedCredentials(args.service_account)
        who = args.service_account
    else:
        import google.auth
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        who = getattr(creds, "service_account_email", "default credentials")
    subscriber = pubsub_v1.SubscriberClient(credentials=creds)
    bucket = storage.Client(project=args.project, credentials=creds).bucket(args.bucket)
    sub_path = subscriber.subscription_path(args.project, args.subscription)

    print(f"Listening on {sub_path} as {who}")
    print(f"Appending to gs://{args.bucket}/{args.log_object}  (Ctrl+C to stop)", flush=True)

    while True:
        try:
            resp = subscriber.pull(request={"subscription": sub_path, "max_messages": 10},
                                   timeout=60)
        except (exceptions.DeadlineExceeded, exceptions.ServiceUnavailable):
            continue                       # nothing arrived; keep waiting
        if not resp.received_messages:
            continue
        ack_ids = []
        for rm in resp.received_messages:
            try:
                m = json.loads(rm.message.data.decode("utf-8"))
            except ValueError:
                m = {"raw": rm.message.data.decode("utf-8", "replace")}
            line = (f"{m.get('time', '?')} FORBIDDEN request from {m.get('country', '?')}: "
                    f"{m.get('method', '?')} {m.get('file', '?')} "
                    f"(client {m.get('client_ip', '?')}) -> denied with 400")
            print("ERROR:", line, flush=True)
            if args.log_object:
                append_to_bucket(bucket, args.log_object, line)
            ack_ids.append(rm.ack_id)
        # acknowledge only after the line is safely stored in the bucket
        subscriber.acknowledge(request={"subscription": sub_path, "ack_ids": ack_ids})


if __name__ == "__main__":
    main()
