#!/usr/bin/env bash
# ============================================================
#  run_load_tests.sh — Run Locust load tests against TaskFlow
# ============================================================
set -euo pipefail

HOST="${HOST:-http://localhost:8000}"
RESULTS_DIR="results"
mkdir -p "$RESULTS_DIR"

echo "═══════════════════════════════════════════════"
echo "  TaskFlow Load Tests"
echo "  Target: $HOST"
echo "═══════════════════════════════════════════════"

# Install locust if needed
if ! command -v locust &> /dev/null; then
    echo "→ Installing locust…"
    pip install -r "$(dirname "$0")/requirements.txt" -q
fi

run_test() {
    local label="$1"
    local users="$2"
    local spawn="$3"
    local duration="$4"
    local csv_prefix="$RESULTS_DIR/${label}"

    echo ""
    echo "▶ Running: $label ($users users, spawn rate $spawn/s, for ${duration})"
    locust \
        -f "$(dirname "$0")/locustfile.py" \
        --host="$HOST" \
        --users="$users" \
        --spawn-rate="$spawn" \
        --run-time="$duration" \
        --headless \
        --csv="$csv_prefix" \
        --html="$csv_prefix.html" \
        2>&1 | tail -20
    echo "→ Report saved: ${csv_prefix}.html"
}

case "${1:-all}" in
    smoke)
        # Quick sanity check — 5 users, 30 seconds
        run_test "smoke" 5 2 "30s"
        ;;
    load)
        # Normal production load
        run_test "load_50"  50  5  "60s"
        ;;
    stress)
        # Stress test — find the breaking point
        run_test "stress_100" 100 10 "60s"
        run_test "stress_200" 200 20 "60s"
        ;;
    spike)
        # Sudden spike — simulates peak traffic burst
        run_test "spike" 150 50 "30s"
        ;;
    all)
        run_test "smoke"      5   2  "30s"
        run_test "load_50"    50  5  "60s"
        run_test "stress_100" 100 10 "60s"
        ;;
    *)
        echo "Usage: $0 [smoke|load|stress|spike|all]"
        exit 1
        ;;
esac

echo ""
echo "✓ All tests complete. HTML reports in ./$RESULTS_DIR/"
