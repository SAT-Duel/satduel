# SAT Duel backend

Django + DRF, deployed to Heroku (app `satduel`). Local dev DB is sqlite; prod
is Heroku Postgres and migrates in the Procfile release phase. The React
frontend lives in the sibling `satduel_react/` repo.

Run tests with `.venv/bin/python manage.py test api classes`.

## Email: two separate paths, on purpose

**Transactional** — Django SMTP (`EMAIL_*` in settings). Everything goes through
`send_branded_email()` in `api/emails.py`, which renders a matched
`templates/emails/<name>.html` + `.txt` pair and sends them as one multipart
message. Every template extends `emails/base.html`.

To add one: write both template files, add a thin `send_*` wrapper in
`api/emails.py`, call it. Do not build a new sending helper, and do not send
HTML without the text alternative — plain text is what keeps mail out of spam.

Current transactional emails: `verify_email`, `password_link`,
`password_changed`, `welcome`.

**Marketing / campaigns** — Resend, driven from its dashboard (Broadcasts).
`api/marketing.py` only mirrors *contacts* and their consent
(`Profile.marketing_opt_in`) into Resend; the app never sends a campaign itself.
`api/views/marketing_views.py` handles the inbound unsubscribe webhook.

The split is deliberate: campaign volume must never damage the sender
reputation that password resets and confirmations depend on. Keep it. A
recurring or promotional send belongs in Resend, not in `api/emails.py`.

Anything sent from `api/emails.py` must be genuinely about the recipient's own
account — it bypasses `marketing_opt_in` by design.

## Lifecycle side effects

`api/signals.py` holds the receivers that hang off account events (email
confirmation fans out to the welcome email and the Resend contact sync). Put new
lifecycle side effects there rather than inline in a view, and make each one
failure-isolated: a broken side effect must never break signup or confirmation.

## Conventions

- Views live in `api/views/` split by domain; `api/urls.py` is the single route
  table. Party, practice, and duel logic each own a module.
- The Discord invite is duplicated across repos by necessity:
  `DISCORD_INVITE_URL` here, `DISCORD_INVITE` in
  `satduel_react/src/components/Discord.jsx`. Change both together.
