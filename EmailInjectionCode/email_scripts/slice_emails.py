"""
Slice the first 10 messages from the baseline JSON into a smaller test file.
"""
import json

INPUT  = "onthehooks_email_baseline.json"
OUTPUT = "onthehooks_test_10.json"

with open(INPUT, "r", encoding="utf-8") as f:
    data = json.load(f)

messages_collected = []
threads_out = []

for thread in data.get("threads", []):
    if len(messages_collected) >= 10:
        break
    msgs = thread.get("messages", [])
    needed = 10 - len(messages_collected)
    sliced_msgs = msgs[:needed]
    messages_collected.extend(sliced_msgs)
    threads_out.append({**thread, "messages": sliced_msgs})

out = {**data, "threads": threads_out}

with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2)

print(f"Done. Wrote {len(messages_collected)} messages across {len(threads_out)} threads to {OUTPUT}")
