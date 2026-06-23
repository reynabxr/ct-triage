#!/bin/bash
# Start agents in sequence to ensure Band registration before downstream agents connect

set -e

echo "Starting CT Queue Agents (sequential startup)..."
echo ""

# Start router
echo "1. Starting router..."
python3 -m agents.run_router &
ROUTER_PID=$!
sleep 3

# Start review
echo "2. Starting review..."
python3 -m agents.run_review &
REVIEW_PID=$!
sleep 3

# Start delay harm (router will also send to this)
echo "3. Starting delay harm..."
python3 -m agents.run_delay_harm &
DELAY_HARM_PID=$!
sleep 3

# Start moderator (review and delay harm will send to this)
echo "4. Starting moderator..."
python3 -m agents.run_moderator &
MODERATOR_PID=$!
sleep 3

# Start escalation
echo "5. Starting escalation..."
python3 -m agents.run_escalation &
ESCALATION_PID=$!

echo ""
echo "✅ All agents started. Press Ctrl+C to stop all."
echo ""

# Wait for all processes
wait $ROUTER_PID $REVIEW_PID $DELAY_HARM_PID $MODERATOR_PID $ESCALATION_PID
