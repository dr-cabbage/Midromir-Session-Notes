# Campaign Chronicle 📜

A website for our D&D campaign that mostly writes itself.

After a session, one command:

1. **records** the Discord call (or takes a recording you already have),
2. **transcribes** it on your own PC with Whisper (free, private),
3. has **Claude** write a funny but accurate recap, and update NPCs, places, quests, mysteries, loot, kills and quotes,
4. opens a **review window** where you cut, fix and regenerate the notes,
5. **publishes** them to the GitHub Pages site.

```
recording ──► transcripts/session-07.txt ──► drafts/session-07.json ──► data/campaign.json ──► website
  (you)          (Whisper, on your PC)         (Claude, you can edit)       (merged)           (git push)
```

The website is `index.html`. It reads everything from `data/campaign.json`, so you never edit HTML to add a session.

---

## One-time setup (Windows)

### 1. Put this on GitHub
1. Go to <https://github.com/new>, name the repo (e.g. `dnd-chronicle`), make it **Public**, and click **Create repository**. Don't add a README.
2. In this folder, open a terminal (right-click the folder > **Open in Terminal**) and run:
   ```powershell
   git init -b main
   git add .
   git commit -m "Start the chronicle"
   git remote add origin https://github.com/YOUR-USERNAME/dnd-chronicle.git
   git push -u origin main
   ```
   If Git asks you to sign in, a browser window opens. Sign in there.
3. On GitHub, open the repo's **Settings > Pages**. Under *Build and deployment*, set **Source: Deploy from a branch**, **Branch: `main`**, folder **`/ (root)`**, then click **Save**.
4. After about a minute, your site is live at `https://YOUR-USERNAME.github.io/dnd-chronicle/`.

### 2. Install the Python pieces
You need **Python 3.10 or newer** (3.12 recommended). Check with `py --list`. If you don't see 3.10 or higher, run `winget install Python.Python.3.12` or download Python from <https://www.python.org/downloads/>.

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned   # one time only; answer Y
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```
Windows blocks PowerShell scripts by default, so without the first line `activate` fails with "running scripts is disabled on this system". Run `.venv\Scripts\activate` again each time you open a new terminal. You'll know it worked when the prompt starts with `(.venv)`.

### 3. Add your keys and settings
```powershell
copy .env.example .env
copy config.example.yaml config.yaml
```
- In **`.env`**, paste your Claude API key. You can make one at <https://console.anthropic.com/settings/keys>, and you'll need to add a few dollars of credit.
- In **`config.yaml`**, fill in the `speakers` list (Discord username → "Player (Character)"), the `dm_context` notes and the `initial_prompt` (your campaign's weird names).

Both files are in `.gitignore`, so your key never goes to GitHub.

### 4. Fill in the party
Open `data/campaign.json` and replace the example character with your party, one entry per character. Keep `"manual": true` on them. Change the `campaign` title, subtitle, setting and DM too.

Preview the site locally at any time:
```powershell
python scribe.py serve
```
To see a filled-in example, open <http://localhost:8000/?data=data/sample-campaign.json>.

---

## Recording a session

**Get everyone's OK before recording.** Some places legally require everyone's consent.

### Option A: Craig bot (recommended for Discord)
[Craig](https://craig.chat) is a free Discord bot that records **each person on their own track**. That lets the transcript say who said what, which makes the notes much better.

1. Invite Craig to your server (once) from <https://craig.chat>.
2. At the start of the session, run `/join` in Discord while you're in the voice channel.
3. At the end, run `/stop`. Craig DMs you a download link. Download the **FLAC** or **Ogg** multi-track **.zip**.
4. Then:
   ```powershell
   python scribe.py process "C:\Users\you\Downloads\craig_xxxxx.flac.zip"
   ```

Craig names each track after the Discord username, so put those usernames under `speakers:` in `config.yaml`.

### Option B: Record from your PC
```powershell
python scribe.py record
```
This records **your mic** and **everything your PC plays** (the rest of the call) as two tracks, until you press **Ctrl+C**. Then it offers to write the notes right away.

- Mute music and videos while it runs, because it captures all PC audio.
- If it picks the wrong headset, run `python scribe.py devices` and then `python scribe.py record --mic "Blue Yeti" --speaker "Headphones"`.
- Everyone except you ends up on one "Table" track, so Claude works out who's talking from context. Craig does this better.

### Option C: A recording you already have
Any audio or video file works (mp3, m4a, wav, mp4, mkv from OBS, ...). A transcript `.txt` works too:
```powershell
python scribe.py process "D:\recordings\session 7.mp4"
```

---

## After the session: review, then publish

```powershell
python scribe.py process "C:\path\to\recording-or-craig.zip"
```

This transcribes the recording and has Claude write a draft. Then a **review window** opens in your browser:

| In the window | What it does |
|---|---|
| **Edit** any text | Click any text and change it. |
| **✕ Cut** | Marks something that didn't happen or that you don't want. Cut items turn red. |
| **Claude wasn't sure about** | Things Claude couldn't confirm (was that real or a joke?). Click **It happened** or **Didn't happen**. |
| **Tell Claude what to fix** | Type corrections, e.g. "The bartender fight was a joke" or "make the dragon part funnier". |
| **↻ Regenerate** | Claude rewrites the whole draft using your cuts, answers and notes. It remembers them for this session, so later rewrites keep them. |
| **Check the transcript** | Search what was actually said. |
| **Post to campaign** | Adds the notes to `data/campaign.json`. Cut items are dropped. |
| **Commit & push** | Publishes to GitHub Pages. |
| **Close** | Ends the review. Your draft is saved. |

Reopen the review window any time with `python scribe.py review --session 7`.

Useful options:

| Command | What it does |
|---|---|
| `process FILE --session 7` | Set the session number. By default it uses the next number. |
| `process FILE --date 2026-09-12` | Set the session date. You can also change it in the review window. |
| `process FILE --retranscribe` | Redo the transcript even if one is saved. |
| `process FILE --fresh` | Throw away the existing draft and write new notes. |
| `notes --session 7` | Write fresh notes from the saved transcript, then review them. |
| `process FILE --no-review` | Skip the window and publish right away. |

Regenerating is cheap because the transcript is cached for a few minutes, so rewrites after the first draft cost much less.

**Re-posting a session is safe.** It replaces what that session added before, so you won't get duplicates.

## Editing things by hand

- **A session's notes:** run `python scribe.py review --session NN`, fix things, then Post and Commit & push.
- **Characters, NPC descriptions and anything else:** edit `data/campaign.json` directly, then `git commit` and `git push`. Add `"manual": true` to an NPC, place or mystery you wrote yourself. That keeps it from being removed when a session is re-run and stops Claude from overwriting its description.
- **Nicknames:** add `"aliases": ["Old Pipe Guy"]` to an NPC so later sessions merge into the same entry.
- **Friends can contribute:** add them as collaborators on GitHub. The Scribe runs `git pull` before every publish, so their edits aren't overwritten.

## Costs and speed

- **Transcription** is free and runs on your PC. On CPU, a long session can take a while, and the time depends a lot on your processor. Start the command and go do something else. Silent stretches are skipped, which helps with Craig's per-person tracks. With an NVIDIA GPU, `model: large-v3` is much faster and more accurate.
- **Notes:** a 4-hour session is about 50–70k tokens. With `claude-sonnet-5` ($2 per million input tokens, $10 per million output tokens), that's roughly **$0.15–0.30 per session**. `claude-opus-5` costs about 2.5× more and writes richer notes.
- Transcripts and recordings stay on your PC. They're kept out of git by default.

## Troubleshooting

| Problem | Fix |
|---|---|
| `ANTHROPIC_API_KEY is not set` | Put the key in `.env`, in the same folder as `scribe.py`. |
| The GPU/CUDA error falls back to CPU | This is fine. To use the GPU, install the NVIDIA cuBLAS/cuDNN libraries (see the faster-whisper docs) or set `device: cpu` to stop the warning. |
| Fantasy names come out wrong | Add them to `whisper.initial_prompt` and `dm_context`, then fix the draft before publishing. |
| The site shows "Couldn't load the chronicle" | You opened `index.html` directly. Use `python scribe.py serve` instead. On GitHub, check that `data/campaign.json` is valid JSON. |
| `Push failed` | Run `git pull`, then `python scribe.py apply --session N`. |
| Recording is silent | Run `python scribe.py devices` and choose the right mic and speaker with `--mic` and `--speaker`. |

## Files

```
index.html                 the website
data/campaign.json         everything the site shows (the Scribe updates this)
data/sample-campaign.json  example data for previewing
drafts/                    Claude's notes per session (committed, easy to edit)
transcripts/               Whisper transcripts (local only)
recordings/                audio from `scribe.py record` (local only)
scribe.py                  the command-line tool
chronicle/                 transcriber, note writer, merger, publisher, recorder
tests/test_scribe.py       offline tests: python tests/test_scribe.py
```
