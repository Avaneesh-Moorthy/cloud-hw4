#!/bin/bash
# stress.sh - runs 1, 2, 3 and 4 concurrent copies of the http-client on hw4-client
# against hw4-web for 3 minutes each, while monitor.py samples the server's
# CPU / memory / network every 2 s. Results land in ~/hw4_results in Cloud Shell.
# Usage: ./scripts/stress.sh            (about 15 minutes in total)
set -uo pipefail
ZONE=${ZONE:-us-central1-a}
REGION=${REGION:-us-central1}
SECS=${SECS:-180}
IP=$(gcloud compute addresses describe hw4-web-ip --region=$REGION --format='value(address)')
OUT=~/hw4_results; mkdir -p $OUT

run() {  # $1 = number of concurrent clients (0 = idle baseline)
  N=$1
  echo; echo "===== $N concurrent client(s), ${SECS}s ====="
  gcloud compute ssh hw4-web --zone=$ZONE --command \
    "python3 /opt/hw4/repo/server/monitor.py --seconds $SECS --out /var/tmp/mon_${N}.csv" \
    > $OUT/summary_${N}.txt 2>&1 &
  MON=$!
  sleep 2
  if [ "$N" -gt 0 ]; then
    gcloud compute ssh hw4-client --zone=$ZONE --command "
      for i in \$(seq 1 $N); do
        timeout -s INT $SECS ./http-client -d $IP -p 80 -b none -w pages -n 1000000 -i 11999 -t 10 -r \$i \
          > client_${N}_\$i.log 2>&1 &
      done; wait; echo clients finished" 2>&1 | tail -1
  fi
  wait $MON
  cat $OUT/summary_${N}.txt
  gcloud compute scp hw4-web:/var/tmp/mon_${N}.csv $OUT/ --zone=$ZONE >/dev/null
  sleep 20   # cool down between runs
}

for N in 0 1 2 3 4; do run $N; done
gcloud compute scp "hw4-client:~/client_*.log" $OUT/ --zone=$ZONE >/dev/null 2>&1
echo; echo "Client-side errors (timeouts / connection errors) per log:"
for f in $OUT/client_*.log; do
  printf '  %-18s %s\n' "$(basename $f)" "$(grep -ciE 'timeout received|refused|reset by peer|errno|remotedisconnected|badstatus' $f)"
done
tar czf ~/hw4_results.tgz -C ~ hw4_results && echo "Packed: ~/hw4_results.tgz"
