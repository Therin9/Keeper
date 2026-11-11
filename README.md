# D&D Campaign Keeper v2 — Railway upgrade

This is an **in-place upgrade** of the v1 bot. It retains the SQLite database and existing registered characters **if the Railway volume and `DATABASE_PATH` remain unchanged**. Make a backup of `/data/campaign.sqlite3` before deploying. Do not create a second Railway service.

## Update via GitHub

1. Open the existing private GitHub repository connected to the Railway **Keeper** service.
2. Replace `bot.py` with the file in this ZIP (upload and commit). Keep `requirements.txt`, `railway.json`, and other existing files; you can update them with the included copies.
3. In Railway → Keeper → Variables, **keep your existing secrets** (`DISCORD_TOKEN`, `OPENAI_API_KEY`) and all existing IDs. Add these three variables:

```dotenv
CHARACTER_CHANNEL_1=1569850025381601300
CHARACTER_CHANNEL_2=1569850046894051329
CHARACTER_CHANNEL_3=1569850075226574940
```

4. Confirm a Railway volume is mounted at `/data` and `DATABASE_PATH=/data/campaign.sqlite3` remains unchanged. If your v1 database was not on a persistent volume, **stop and back up or migrate it before deploying**, otherwise character data may be lost.
5. Apply variables and deploy the updated GitHub commit. Look for `Logged in as ...` in Deploy Logs.

## New DM features

In `#dm-summary` (DM role only):
- `/character` — create or update one character per Discord player; set name, class, level, HP, XP, and one of the three private character channels. Existing inventory, spell slots, and currency are retained on edit.
- `/session review` — AI extracts confirmed events and posts a proposed review with **Approve & Save**, **Revise**, and **Discard** buttons.
- `/session revise review_id:<number>` — opens a correction form, posts a revised review, without committing anything.
- `/session commit review_id:<number>` — alternative to Approve & Save.

## Player commands

In their assigned character channel, players use `/myhp`, `/xp`, `/inventory`, `/stats`, `/spellslots`, and `/gold`. Responses are ephemeral. The character owner is determined by Discord account ID. Set Discord channel permissions separately to restrict visibility.

## Important limitations

- **Google Sheets sync is not implemented**. Committing saves to SQLite only.
- This version tracks currency as PP/GP/EP/SP/CP and can propose currency changes; it does not automatically exchange denominations.
- Level-up detection in `/xp` is informational only; the DM controls leveling. Spell slot maxima and stats still need a later configuration editor.
- A pending review created in v1 can be revised or committed after migration. If the DM's review contains unresolved questions, resolve them before approval.
- AI interpretation can make mistakes. The DM must review all changes before committing.
- The `#main-campaign` message logger only records messages posted while a session is active.
- Discord buttons on existing review messages may still look active after a slash-command commit; subsequent attempts are rejected safely.

## Suggested smoke test

1. In `#dm-summary`, run `/character` for Therin and assign character-channel-1.
2. In the assigned channel, run `/myhp`, `/xp`, `/gold`.
3. Start a session; post `The DM awards Therin 2 silver pieces and 50 XP` in main-campaign.
4. Run `/session review` in dm-summary. Verify it proposes `currency_delta +2 sp` and `xp_delta +50`.
5. Click **Revise** to test a correction, then **Approve & Save**. Check `/gold` and `/xp` again.
6. Don't use real campaign data until persistence is confirmed after a restart.
