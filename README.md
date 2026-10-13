# CS528 HW4: File server on Compute Engine VMs

| VM | Machine | Service account | Runs |
|---|---|---|---|
| `hw4-web` | e2-micro, static IP `hw4-web-ip` | `hw4-web-server@…` | `server/web_server.py` on port 80 (systemd `hw4-web`) |
| `hw4-listener` | e2-micro | `hw4-listener@…` | `listener/forbidden_listener.py` (systemd `hw4-listener`) |
| `hw4-client` | e2-small | none | the provided `http-client` |

## One-command deployment (Cloud Shell)

```bash
git clone https://github.com/Avaneesh-Moorthy/cloud-hw4.git && cd cloud-hw4
PROJECT=cedar-pottery-508921-u1 BUCKET=cedar-pottery-508921-u1-pages bash scripts/deploy.sh
```

`deploy.sh` enables the APIs, creates both service accounts with least-privilege roles, the Pub/Sub
topic/subscription, a static IP, a firewall rule for port 80, and the two VMs. Each VM's startup script
installs Python, clones this repo, and starts its program as a systemd service, which also restarts it on reboot.
Optional overrides: `REGION`, `ZONE`, `REPO`, `PREFIX`, `WEB_TYPE`, `LISTENER_TYPE`.

| Service account | Role | On |
|---|---|---|
| hw4-web-server | `roles/storage.objectViewer` | the bucket |
| | `roles/pubsub.publisher` | topic `hw4-forbidden` |
| | `roles/logging.logWriter` | project (write log entries only) |
| hw4-listener | `roles/pubsub.subscriber` | subscription `hw4-forbidden-sub` |
| | `roles/storage.objectUser` | the bucket (append forbidden log) |

## Web server behaviour

| Request | Response | Cloud Logging severity |
|---|---|---|
| `GET /<file>` | 200 + file | – |
| `POST /` with `{"filename": "123.html"}`, form field or text body | 200 + file | – |
| missing file | 404 | WARNING |
| PUT, DELETE, HEAD, CONNECT, OPTIONS, TRACE, PATCH, any other | 501 | ERROR |
| `X-country` = North Korea, Iran, Cuba, Myanmar, Iraq, Libya, Sudan, Zimbabwe, Syria | 400 | CRITICAL (+ Pub/Sub → listener) |

Logs: `logName="projects/PROJECT/logs/hw4-web-server"`.

## Other scripts

* `scripts/create_client_vm.sh ~/http-client`: client VM, plus a copy of the client
* `scripts/stress.sh`: 0–4 concurrent clients × 3 min, sampling server CPU/memory/network with `server/monitor.py`
* `scripts/teardown.sh`: delete the VMs and the static IP
