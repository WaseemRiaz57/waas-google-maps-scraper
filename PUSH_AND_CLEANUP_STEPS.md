# Push + security cleanup — NOT RUN YET (needs Waseem's explicit approval)

Local commit ready: `ba7681d` — "Add fixed scraper_v2 and whatsapp_bot_v2".
Offline tests: 16/16 passed (price, opt-out, phone format, real-data-only demo URL, shared header).

## Step 1 — GitHub login (required before any push)
This environment is not logged into GitHub (`gh auth status` = not logged in).
Sign in on GitHub, then push the local commit:
```
git push origin main
```

## Step 2 — History cleanup (DESTRUCTIVE — approve explicitly before running)
Deleting `chrome_profile/` and the credentials-like file from the working copy does NOT
remove them from git history. History rewrite requires force-push and will break anyone
else's clone of this repo. Do NOT run this without Waseem's clear approval:
```
pip install git-filter-repo
git filter-repo --path chrome_profile --path '~$edentials.json' --invert-paths --force
git push origin main --force
```
Afterwards, if the credentials file was a real Google service-account key, revoke/rotate it
in Google Cloud, and if the chrome_profile session was real, log out / revoke that WhatsApp
Web session. Treat both as compromised until verified. The credentials file's contents were
never opened by the assistant.

## Step 3 — Live test (blocked on credentials + WhatsApp session)
- Scraper v2 needs a valid Google service-account `credentials.json` (NOT the public repo's file)
  and a Google Sheet named `Leads_Data`.
- Bot v2 needs a fresh WhatsApp Web QR scan into `chrome_profile_local/` (never the committed profile).
- Do NOT run either live until Steps 1–2 are done and Waseem approves a live test run.
