#!/bin/bash
cd "$(dirname "$0")"
MSQUIC=/home/harshitharm/Desktop/ABE
NS="mq-s1 mq-s2 mq-r1 mq-r2 mq-d1 mq-d2"
[ -f configure_queue.py.orig ] || cp configure_queue.py configure_queue.py.orig
mkdir -p results_noecn

force_clean() {
  for ns in $NS; do ip netns pids $ns 2>/dev/null | xargs -r kill -9 2>/dev/null; done
  pkill -9 tcpdump 2>/dev/null
  for ns in $NS; do ip netns del $ns 2>/dev/null; done
}

i=0
for sc in "40 5" "40 10" "40 50" "20 50" "40 50" "50 50"; do
  i=$((i+1)); set -- $sc; RTT=$1; BW=$2; D=$((RTT/2))
  if [ "$BW" = "50" ]; then BURST=60; else BURST=15; fi
  sed -e "s/\"rate\", \"[0-9]*mbit\"/\"rate\", \"${BW}mbit\"/" \
      -e "s/\"ceil\", \"[0-9]*mbit\"/\"ceil\", \"${BW}mbit\"/" \
      -e "s/\"burst\", \"[0-9]*k\"/\"burst\", \"${BURST}k\"/" \
      -e "s/\"delay\", \"[0-9]*ms\"/\"delay\", \"${D}ms\"/" \
      configure_queue.py.orig > configure_queue.py
  for run in 1 2 3; do
    dest="results_noecn/sc${i}_rtt${RTT}_bw${BW}_run${run}"
    [ -f "$dest/cwnd_rtt.png" ] && { echo "skip $dest (done)"; continue; }
    echo "=== sc${i}: RTT ${RTT} ms, BW ${BW} Mbit, run ${run} ==="
    force_clean
    python3 run_all.py --msquic "$MSQUIC" --ecn off --duration 60
    latest=$(ls -dt results/*-ecn-off 2>/dev/null | head -1)
    if [ -n "$latest" ] && [ -f "$latest/cwnd_rtt.png" ] && [ -f "$latest/summary.json" ]; then
      mv "$latest" "$dest"; echo "saved $dest"
    else
      echo "REAL FAILURE: sc${i} rtt${RTT} bw${BW} run${run}; stopping."
      force_clean; cp configure_queue.py.orig configure_queue.py; exit 1
    fi
    force_clean; sleep 3
  done
done
cp configure_queue.py.orig configure_queue.py
[ -n "$SUDO_USER" ] && chown -R "$SUDO_USER":"$SUDO_USER" results results_noecn
echo "Done. Results in results_noecn/"
