#!/bin/sh
# One step from plug-in to playing: wait for the UNO Q, make sure it is online
# with a synced clock, flash this track, then follow the Python logs.
set -eu
cd "$(dirname "$0")/.."
on_board() { adb -d shell -T "$1"; }

echo "Waiting for the UNO Q on USB..."
adb wait-for-usb-device
until on_board 'TMPDIR=/tmp arduino-app-cli app list >/dev/null 2>&1'; do sleep 2; done
echo "Board is up."

# Only one app can run at a time (README "Terminal commands"); stop any App Lab app first.
on_board 'export TMPDIR=/tmp; arduino-app-cli app ps | awk "NR > 1 && NF { print \$1 }" | while read -r id; do echo "Stopping $id"; arduino-app-cli app stop "$id"; done' || :

online() { on_board 'curl -s -m8 -o /dev/null https://downloads.arduino.cc/' >/dev/null 2>&1; }
if ! online; then
    echo "Board has no internet; trying the saved iPhone hotspot..."
    on_board 'nmcli -t -f NAME,TYPE connection show | grep -i iphone | grep wireless | cut -d: -f1 | head -1 | xargs -r -I{} nmcli connection up id "{}"' || :
    sleep 5
    online || { echo "Still offline. Turn on the hotspot (Maximize Compatibility) and rerun." >&2; exit 1; }
fi
echo "Internet OK."

echo "Waiting for the board clock to sync..."
i=0
until [ "$(on_board 'timedatectl show -p NTPSynchronized --value')" = yes ]; do
    i=$((i + 1))
    [ "$i" -le 45 ] || { echo "Clock did not sync; downloads will fail signature checks." >&2; exit 1; }
    sleep 2
done
on_board 'date -u'

make flash
echo "Flashed. Following logs (Ctrl+C leaves; the game keeps running)."
make logs
