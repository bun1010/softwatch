Softwatch daily post. Do not search the web. Do not alter, round or add numbers.

1. In /home/user/softwatch run: `git pull --ff-only origin main`
2. Read out/last_run.json. If its finished_at is more than 26 hours old, or ok is false, post exactly one line: "Softwatch: today's collection didn't run. Last good run: <finished_at or unknown>." and stop.
3. Otherwise read out/notify.txt. If it is empty, end the turn with no_reply_needed. If not empty, post its contents verbatim with post_message. Wrap the URLs as they appear. Do not add text.
