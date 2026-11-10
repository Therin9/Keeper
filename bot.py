import os, json, sqlite3, asyncio
from datetime import datetime, timezone
import discord
from discord import app_commands
from discord.ext import commands
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()
TOKEN=os.environ['DISCORD_TOKEN']; GUILD_ID=int(os.environ['GUILD_ID'])
ADVENTURE_ID=int(os.environ['ADVENTURE_CHANNEL_ID']); DM_CHANNEL_ID=int(os.environ['DM_CHANNEL_ID'])
DM_ROLE_ID=int(os.environ['DM_ROLE_ID']); MODEL=os.getenv('OPENAI_MODEL','gpt-4.1-mini')
DB=os.getenv('DATABASE_PATH','campaign.sqlite3')
os.makedirs(os.path.dirname(os.path.abspath(DB)),exist_ok=True)
client=AsyncOpenAI(api_key=os.environ['OPENAI_API_KEY'])
conn=sqlite3.connect(DB)
conn.row_factory=sqlite3.Row
conn.executescript('''
CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT, status TEXT NOT NULL DEFAULT 'active');
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, author_id INTEGER NOT NULL, author_name TEXT NOT NULL, content TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS characters(user_id INTEGER PRIMARY KEY, name TEXT NOT NULL, hp INTEGER NOT NULL, max_hp INTEGER NOT NULL, xp INTEGER NOT NULL DEFAULT 0, inventory TEXT NOT NULL DEFAULT '[]', stats TEXT NOT NULL DEFAULT '{}', spell_slots TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, from_message_id INTEGER NOT NULL, to_message_id INTEGER NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS applied_events(review_id INTEGER NOT NULL, event_index INTEGER NOT NULL, PRIMARY KEY(review_id,event_index));
''')
conn.commit()
intents=discord.Intents.default(); intents.message_content=True
bot=commands.Bot(command_prefix='!',intents=intents)
group=app_commands.Group(name='session',description='DM campaign management')

def is_dm(interaction):
    return isinstance(interaction.user,discord.Member) and any(r.id==DM_ROLE_ID for r in interaction.user.roles)

def current_session():
    return conn.execute("SELECT * FROM sessions WHERE status='active' ORDER BY id DESC LIMIT 1").fetchone()

def last_committed(session_id):
    row=conn.execute("SELECT MAX(to_message_id) AS marker FROM reviews WHERE session_id=? AND status='committed'",(session_id,)).fetchone()
    return row['marker'] or 0

def check_channel(interaction):
    return interaction.channel_id==DM_CHANNEL_ID and is_dm(interaction)

@bot.event
async def on_message(message):
    if message.author.bot or message.channel.id!=ADVENTURE_ID: return
    s=current_session()
    if not s: return
    conn.execute('INSERT OR IGNORE INTO messages VALUES (?,?,?,?,?)',(message.id,s['id'],message.author.id,message.author.display_name,message.content))
    conn.commit()

@group.command(name='start',description='Begin collecting adventure messages')
async def start(interaction:discord.Interaction):
    if not check_channel(interaction): return await interaction.response.send_message('DM-only command in #dm-summary.',ephemeral=True)
    if current_session(): return await interaction.response.send_message('A session is already active.',ephemeral=True)
    conn.execute('INSERT INTO sessions(started_at) VALUES (?)',(datetime.now(timezone.utc).isoformat(),));conn.commit()
    await interaction.response.send_message('Session started. Adventure messages are being recorded.')

SYSTEM='''You analyze a D&D 2024/5e human-DM transcript. Return ONLY JSON with keys summary (string), questions (array of strings), events (array). Each event: {"user_id": integer, "character": string, "type": "hp_delta"|"xp_delta"|"item_add"|"item_remove"|"spell_slot_delta", "amount": integer, "item": string, "slot_level": string, "evidence": string}. Use negative HP for damage and positive for healing. Only emit clearly CONFIRMED events, not proposals, attempts, jokes or restatements. XP must be explicitly awarded by DM; do not invent XP from monsters. Use only supplied character user IDs; if identity or target is ambiguous, add a question instead. Don't double-count damage when players repeat current HP. Do not apply rest, level-up or complex rules automatically; flag them in questions. Each event should be a discrete delta. Inventory amounts positive; spell slots negative for consumption. No markdown.'''

@group.command(name='review',description='Analyze unsaved session messages for DM approval')
async def review(interaction:discord.Interaction):
    if not check_channel(interaction): return await interaction.response.send_message('DM-only command in #dm-summary.',ephemeral=True)
    s=current_session()
    if not s: return await interaction.response.send_message('Start a session first.',ephemeral=True)
    pending=conn.execute("SELECT id FROM reviews WHERE session_id=? AND status='pending'",(s['id'],)).fetchone()
    if pending: return await interaction.response.send_message(f'Review #{pending["id"]} is still pending. Commit or discard it first.',ephemeral=True)
    marker=last_committed(s['id'])
    msgs=conn.execute('SELECT * FROM messages WHERE session_id=? AND id>? ORDER BY id',(s['id'],marker)).fetchall()
    if not msgs: return await interaction.response.send_message('No new messages to review.',ephemeral=True)
    await interaction.response.defer(ephemeral=True,thinking=True)
    chars=[dict(r) for r in conn.execute('SELECT user_id,name,hp,max_hp,xp FROM characters')]
    transcript='\n'.join(f'{r["author_name"]} (discord_id={r["author_id"]}): {r["content"]}' for r in msgs)
    try:
        response=await client.chat.completions.create(model=MODEL,temperature=0,response_format={'type':'json_object'},messages=[{'role':'system','content':SYSTEM},{'role':'user','content':f'Characters: {json.dumps(chars)}\nTranscript:\n{transcript[:100000]}'}])
        payload=json.loads(response.choices[0].message.content)
        if not isinstance(payload.get('events'),list): raise ValueError('Invalid event list')
    except Exception as e:
        return await interaction.followup.send(f'AI review failed: {type(e).__name__}: {e}',ephemeral=True)
    cur=conn.execute('INSERT INTO reviews(session_id,from_message_id,to_message_id,payload,created_at) VALUES (?,?,?,?,?)',(s['id'],msgs[0]['id'],msgs[-1]['id'],json.dumps(payload),datetime.now(timezone.utc).isoformat()));conn.commit()
    rid=cur.lastrowid
    lines=[f'**Session review #{rid} — NOT SAVED**',str(payload.get('summary',''))[:1200],'**Proposed changes**']
    for i,e in enumerate(payload['events']): lines.append(f'{i+1}. {e.get("character",e.get("user_id"))}: {e.get("type")} {e.get("amount")} {e.get("item","")} {e.get("slot_level","")} — {str(e.get("evidence",""))[:90]}')
    if payload.get('questions'): lines.append('**DM questions**\n'+'\n'.join('• '+str(q) for q in payload['questions']))
    lines.append(f'Use `/session commit review_id:{rid}` to approve or `/session discard review_id:{rid}` to reject. No changes are applied until commit.')
    text='\n'.join(lines)
    channel=bot.get_channel(DM_CHANNEL_ID) or await bot.fetch_channel(DM_CHANNEL_ID)
    for i in range(0,len(text),1900): await channel.send(text[i:i+1900])
    await interaction.followup.send(f'Review #{rid} posted to the DM channel.',ephemeral=True)

def apply_event(e):
    uid=int(e['user_id']); row=conn.execute('SELECT * FROM characters WHERE user_id=?',(uid,)).fetchone()
    if not row: raise ValueError(f'Unknown character user ID {uid}')
    typ=e['type']; amt=int(e['amount'])
    if typ=='hp_delta':
        hp=max(0,min(row['max_hp'],row['hp']+amt))
        conn.execute('UPDATE characters SET hp=? WHERE user_id=?',(hp,uid))
    elif typ=='xp_delta':
        if amt<0: raise ValueError('Negative XP requires manual correction')
        conn.execute('UPDATE characters SET xp=xp+? WHERE user_id=?',(amt,uid))
    elif typ in ('item_add','item_remove'):
        item=str(e.get('item','')).strip()
        if not item or amt<=0: raise ValueError('Item needs a name and positive quantity')
        inventory=json.loads(row['inventory']); delta=amt if typ=='item_add' else -amt
        found=next((x for x in inventory if x['name'].lower()==item.lower()),None)
        if found: found['quantity']+=delta
        elif delta>0: inventory.append({'name':item,'quantity':delta})
        else: raise ValueError(f'Cannot remove missing item {item}')
        if found and found['quantity']<0: raise ValueError(f'Insufficient quantity of {item}')
        inventory=[x for x in inventory if x['quantity']>0]
        conn.execute('UPDATE characters SET inventory=? WHERE user_id=?',(json.dumps(inventory),uid))
    elif typ=='spell_slot_delta':
        level=str(e.get('slot_level','')); slots=json.loads(row['spell_slots'])
        if level not in slots: raise ValueError(f'Spell slot level {level} not configured')
        slots[level]['current']+=amt
        if not 0<=slots[level]['current']<=slots[level]['max']: raise ValueError('Spell slot out of range')
        conn.execute('UPDATE characters SET spell_slots=? WHERE user_id=?',(json.dumps(slots),uid))
    else: raise ValueError(f'Unsupported event type {typ}')

@group.command(name='commit',description='Approve a review and save its character changes')
@app_commands.describe(review_id='Number shown in DM review')
async def commit(interaction:discord.Interaction,review_id:int):
    if not check_channel(interaction): return await interaction.response.send_message('DM-only command in #dm-summary.',ephemeral=True)
    r=conn.execute('SELECT * FROM reviews WHERE id=?',(review_id,)).fetchone()
    if not r or r['status']!='pending': return await interaction.response.send_message('No pending review with that ID.',ephemeral=True)
    if not current_session() or current_session()['id']!=r['session_id']: return await interaction.response.send_message('Review is not from the active session.',ephemeral=True)
    if r['from_message_id']<=last_committed(r['session_id']): return await interaction.response.send_message('Review overlaps previously committed messages.',ephemeral=True)
    payload=json.loads(r['payload'])
    try:
        with conn:
            for i,e in enumerate(payload['events']):
                apply_event(e)
                conn.execute('INSERT INTO applied_events VALUES (?,?)',(review_id,i))
            conn.execute("UPDATE reviews SET status='committed' WHERE id=?",(review_id,))
    except Exception as e: return await interaction.response.send_message(f'Commit rejected; nothing changed: {e}',ephemeral=True)
    await interaction.response.send_message(f'Committed review #{review_id}: {len(payload["events"])} changes saved locally. Google Sheets synchronization is not yet enabled.')

@group.command(name='discard',description='Discard an unapproved review')
async def discard(interaction:discord.Interaction,review_id:int):
    if not check_channel(interaction): return await interaction.response.send_message('DM-only command in #dm-summary.',ephemeral=True)
    r=conn.execute("SELECT * FROM reviews WHERE id=? AND status='pending'",(review_id,)).fetchone()
    if not r: return await interaction.response.send_message('No pending review with that ID.',ephemeral=True)
    conn.execute("UPDATE reviews SET status='discarded' WHERE id=?",(review_id,));conn.commit()
    await interaction.response.send_message(f'Discarded review #{review_id}. Run `/session review` to analyze again.')

@group.command(name='end',description='Close the session after committing all reviews')
async def end(interaction:discord.Interaction):
    if not check_channel(interaction): return await interaction.response.send_message('DM-only command in #dm-summary.',ephemeral=True)
    s=current_session()
    if not s: return await interaction.response.send_message('No active session.',ephemeral=True)
    pending=conn.execute("SELECT COUNT(*) FROM reviews WHERE session_id=? AND status='pending'",(s['id'],)).fetchone()[0]
    remaining=conn.execute('SELECT COUNT(*) FROM messages WHERE session_id=? AND id>?',(s['id'],last_committed(s['id']))).fetchone()[0]
    if pending or remaining: return await interaction.response.send_message(f'Cannot end: {pending} pending reviews and {remaining} unsaved messages. Commit a review or discard and re-review.',ephemeral=True)
    conn.execute("UPDATE sessions SET status='ended',ended_at=? WHERE id=?",(datetime.now(timezone.utc).isoformat(),s['id']));conn.commit()
    await interaction.response.send_message('Session closed.')

@bot.tree.command(name='myhp',description='Show your saved HP')
async def myhp(interaction:discord.Interaction):
    r=conn.execute('SELECT * FROM characters WHERE user_id=?',(interaction.user.id,)).fetchone()
    await interaction.response.send_message(f'{r["name"]}: **{r["hp"]}/{r["max_hp"]} HP**' if r else 'No character registered for your Discord account.',ephemeral=True)

@bot.tree.command(name='xp',description='Show your saved XP')
async def xp(interaction:discord.Interaction):
    r=conn.execute('SELECT * FROM characters WHERE user_id=?',(interaction.user.id,)).fetchone()
    await interaction.response.send_message(f'{r["name"]}: **{r["xp"]} XP**' if r else 'No character registered.',ephemeral=True)

@bot.tree.command(name='inventory',description='Show your saved inventory')
async def inventory(interaction:discord.Interaction):
    r=conn.execute('SELECT * FROM characters WHERE user_id=?',(interaction.user.id,)).fetchone()
    items=json.loads(r['inventory']) if r else []
    await interaction.response.send_message('\n'.join(f'{x["name"]} ×{x["quantity"]}' for x in items) or 'No items recorded.',ephemeral=True)

@bot.tree.command(name='stats',description='Show your saved stats')
async def stats(interaction:discord.Interaction):
    r=conn.execute('SELECT * FROM characters WHERE user_id=?',(interaction.user.id,)).fetchone()
    await interaction.response.send_message(json.dumps(json.loads(r['stats']),indent=2)[:1900] if r else 'No character registered.',ephemeral=True)

@bot.tree.command(name='spellslots',description='Show your saved spell slots')
async def spellslots(interaction:discord.Interaction):
    r=conn.execute('SELECT * FROM characters WHERE user_id=?',(interaction.user.id,)).fetchone()
    slots=json.loads(r['spell_slots']) if r else {}
    await interaction.response.send_message('\n'.join(f'Level {k}: {v["current"]}/{v["max"]}' for k,v in slots.items()) or 'No spell slots recorded.',ephemeral=True)

@bot.tree.command(name='register',description='DM: register or replace a character')
async def register(interaction:discord.Interaction,player:discord.Member,name:str,max_hp:int,current_hp:int=0,xp:int=0):
    if not check_channel(interaction): return await interaction.response.send_message('DM-only command in #dm-summary.',ephemeral=True)
    if max_hp<1 or current_hp<0 or current_hp>max_hp or xp<0: return await interaction.response.send_message('Invalid HP or XP.',ephemeral=True)
    if current_hp==0: current_hp=max_hp
    conn.execute('INSERT INTO characters(user_id,name,hp,max_hp,xp) VALUES (?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET name=excluded.name,hp=excluded.hp,max_hp=excluded.max_hp,xp=excluded.xp',(player.id,name,current_hp,max_hp,xp));conn.commit()
    await interaction.response.send_message(f'Registered {name} for {player.mention}.')

@bot.event
async def on_ready():
    if not getattr(bot,'_synced',False):
        bot.tree.add_command(group,guild=discord.Object(id=GUILD_ID))
        # Copy globally defined commands into the test guild for immediate availability.
        bot.tree.copy_global_to(guild=discord.Object(id=GUILD_ID))
        await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        bot._synced=True
    print(f'Logged in as {bot.user}')

bot.run(TOKEN)
