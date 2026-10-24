# SiteSphere scraper + WhatsApp bot — v2 fix (24 Oct 2026)

Fixed files: `scraper_v2.py` and `whatsapp_bot_v2.py`. The originals are untouched.
Nothing has been pushed to GitHub yet, and no WhatsApp message has been sent by v2.

## What v2 fixes
- **Security:** bot no longer uses the committed `chrome_profile/` session folder. It uses
  `chrome_profile_local/` (or `WHATSAPP_PROFILE_DIR`) which must stay uncommitted.
- **Auth:** `oauth2client` (deprecated) replaced with `google-auth` (`google.oauth2.service_account`).
- **Header bug:** scraper writes one shared header row first (`ensure_header`), so the first lead
  is never eaten as a header, and the bot finds the Status column from the header, not a hardcoded 6.
- **De-duplication:** scraper skips phones already in the sheet.
- **No fabricated demo data:** random rating (4.7–5.0), random "Happy Patients" (50–200),
  invented `info@<business>.com` email and generic Unsplash image sets are removed.
  The demo URL now carries only verified fields; rating/review count/top review/photos are
  included only when actually found on the Maps page, otherwise omitted.
- **Reviews + photos:** scraper_v2 best-effort collects real rating, review count, one top review
  snippet and up to 3 business photo URLs from the Maps detail panel. For a LIVE client site,
  publish reviews/photos only with the client's confirmation and Google attribution where required.
  The clean live route is the Google Places API (needs an API key) or client-supplied photos/reviews.
- **Message (revised evening 24 Oct 2026):** professional English first message, NO price mentioned yet.
  Price is discussed only after the clinic shows interest. The message keeps an opt-out
  ("Reply STOP if you prefer not to receive further messages").
  The demo link is included only when a real demo URL is passed; pass "" to omit it.
- **Approval gate:** the bot sends ONLY rows whose Status is exactly "Approved".
  "Pending" rows are drafts and are never auto-sent. The bot also asks for a typed YES before sending.
- **Honest status:** "Send clicked" means only the send button was clicked, NOT confirmed delivery.
- **Safety:** bot no longer force-kills all Chrome processes; send delay raised to 30–60 seconds;
  out-of-range end rows are clamped instead of aborting.

## SECURITY CLEANUP — do this before any v2 run or push
1. Delete `chrome_profile/` and the credentials-like file from the public repo, including from
   git history (e.g. `git filter-repo` or BFG), then force-push. Deleting only the working copy
   does NOT remove them from history.
2. If that credentials file was a real Google service-account key, revoke/rotate it in Google Cloud.
3. If the chrome_profile session was a real WhatsApp Web session, log it out / revoke it.
4. Treat both as compromised until verified. Do NOT open or copy the credentials-like file's contents.

## Run (after cleanup + GitHub login)
```
pip install -r requirements.txt
python scraper_v2.py        # writes leads with Status "Pending"
# Mark rows "Approved" in the sheet only for clinics Waseem approved, then:
python whatsapp_bot_v2.py   # sends Approved rows only, after a typed YES
```

## Still open
- v2 has NOT been run against live Google Maps / WhatsApp, so the rating/photo extractors are
  best-effort and untested on a real detail panel.
- Google Places API key (for reliable live reviews/photos) is not available.
- Pushing v2 to GitHub needs a GitHub login; this environment is not logged into GitHub.
