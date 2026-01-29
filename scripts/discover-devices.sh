#!/bin/bash
# Discover ESPHome devices on the local network via mDNS
# Outputs INI-style config grouped by matching yaml files

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="$(dirname "$SCRIPT_DIR")"
TIMEOUT=${1:-5}
TEMP_FILE=$(mktemp)
RESULTS_FILE=$(mktemp)

cleanup() {
    rm -f "$TEMP_FILE" "$RESULTS_FILE"
    if [[ -n "$DNS_SD_PID" ]]; then
        kill "$DNS_SD_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

echo "Discovering ESPHome devices (waiting ${TIMEOUT}s)..." >&2

# Start dns-sd browse in background
dns-sd -B _esphomelib._tcp local > "$TEMP_FILE" 2>&1 &
DNS_SD_PID=$!

sleep "$TIMEOUT"
kill "$DNS_SD_PID" 2>/dev/null || true
wait "$DNS_SD_PID" 2>/dev/null || true

# Parse discovered device names (last column)
DEVICES=$(grep -E "Add.*_esphomelib._tcp" "$TEMP_FILE" 2>/dev/null | awk '{print $NF}' | sort -u)

if [[ -z "$DEVICES" ]]; then
    echo "No ESPHome devices found on the network." >&2
    exit 0
fi

echo "Found devices, resolving addresses..." >&2

# Build list of config files (without secrets.yaml and base_*.yaml)
CONFIG_FILES=$(ls "$CONFIG_DIR"/*.yaml 2>/dev/null | xargs -n1 basename | grep -v '^secrets\.yaml$' | grep -v '^base_' || true)

# Resolve each device and match to config, write to results file
for DEVICE in $DEVICES; do
    MDNS_FILE=$(mktemp)
    dns-sd -G v4 "${DEVICE}.local" > "$MDNS_FILE" 2>&1 &
    MDNS_PID=$!
    sleep 2
    kill "$MDNS_PID" 2>/dev/null || true
    wait "$MDNS_PID" 2>/dev/null || true

    IP=$(grep -E "^\S+\s+Add\s+" "$MDNS_FILE" 2>/dev/null | awk '{print $6}' | head -1)
    rm -f "$MDNS_FILE"

    if [[ -z "$IP" ]]; then
        continue
    fi

    # Try to match device name to a config file
    MATCHED=""
    for CONFIG in $CONFIG_FILES; do
        CONFIG_BASE="${CONFIG%.yaml}"
        CONFIG_PATTERN=$(echo "$CONFIG_BASE" | tr '_' '-')

        if [[ "$DEVICE" == ${CONFIG_PATTERN}* ]]; then
            MATCHED="$CONFIG"
            break
        fi
    done

    if [[ -n "$MATCHED" ]]; then
        echo "${MATCHED}|${IP}|${DEVICE}" >> "$RESULTS_FILE"
    else
        echo "_UNMATCHED_|${IP}|${DEVICE}" >> "$RESULTS_FILE"
    fi
done

# Output grouped by config
if [[ -f "$RESULTS_FILE" ]]; then
    # Get unique configs and output each section
    grep -v '^_UNMATCHED_|' "$RESULTS_FILE" 2>/dev/null | cut -d'|' -f1 | sort -u | while read -r CONFIG; do
        echo ""
        echo "[$CONFIG]"
        grep "^${CONFIG}|" "$RESULTS_FILE" | while IFS='|' read -r _ ip device; do
            echo "${ip}  # ${device}"
        done | sort -t. -k4 -n
    done

    # Output unmatched devices
    if grep -q '^_UNMATCHED_|' "$RESULTS_FILE" 2>/dev/null; then
        echo ""
        echo "# Unmatched devices (add manually to appropriate section):"
        grep '^_UNMATCHED_|' "$RESULTS_FILE" | while IFS='|' read -r _ ip device; do
            echo "# ${ip}  # ${device}"
        done
    fi
fi