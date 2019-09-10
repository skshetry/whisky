command -v vegeta >/dev/null 2>&1 || { echo >&2 "Vegeta not installed. Aborting..."; exit 1; }

: ${ATTACK_RATE:="100/s"}
: ${ATTACK_DURATION:="60s"}
: ${ATTACK_URL:="http://:8000"}
: ${ATTACK_METHOD:="GET"}

echo "Attacking at the rate of $ATTACK_RATE for $ATTACK_DURATION using: \"$ATTACK_METHOD $ATTACK_URL\""

echo "$ATTACK_METHOD $ATTACK_URL" | vegeta attack -duration=${ATTACK_DURATION} -rate=$ATTACK_RATE | vegeta encode > results.json
vegeta report -type=text results.json