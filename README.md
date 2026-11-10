# D&D Campaign Keeper — Railway deployment

## Deploy
1. Create a **private** GitHub repository and upload the files in this folder to its root.
2. In Railway: New Project > Deploy from GitHub repo > choose the repository.
3. Add a Railway Volume mounted at `/data` to the bot service. Do this **before** beginning actual gameplay.
4. Set the following Railway service variables (never put secrets in GitHub):

```
DISCORD_TOKEN=<private bot token>
OPENAI_API_KEY=<private OpenAI API key>
GUILD_ID=1569849816777760889
ADVENTURE_CHANNEL_ID=1569849817629200476
DM_CHANNEL_ID=1569849985120342117
DM_ROLE_ID=1569850672021643284
OPENAI_MODEL=gpt-4.1-mini
DATABASE_PATH=/data/campaign.sqlite3
```

5. Deploy/redeploy and check Railway Logs for `Logged in as ...`. Discord Message Content Intent must be enabled.
6. In #dm-summary use `/register`, then `/session start`. Post test messages in #main-campaign, then `/session review`, `/session commit`, `/session end`.

## Important limitations
- This is a **prototype**: it has not been tested live and does not yet sync to Google Sheets. `/session commit` saves only to SQLite.
- The three character channels are not yet mapped to player IDs; character lookup commands use Discord user IDs and ephemeral responses.
- The DM must review AI-proposed events carefully. There is no event-edit UI yet; `/session discard` rejects a proposed review.
- Character registration initializes HP and XP; other fields need later enhancements.
- Capture only runs while the bot is online and a session is active.
- Do not scale the service beyond one replica while using SQLite. Maintain backups of the volume.
