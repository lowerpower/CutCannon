#!/usr/bin/env python3
"""ytpost.py: schedule uploads to a YouTube channel through the YouTube Data API.

Every upload goes up PRIVATE with a scheduled publish time, so it can be checked in
YouTube Studio before it goes public.

  ytpost.py auth <channel> --client-secret FILE        one-time: print the Google sign-in link
                     [--scope full|upload]             what the sign-in may do (see Permissions below)
  ytpost.py auth <channel> --code '<address>'          finish sign-in (the 127.0.0.1 address Google sent you to)
  ytpost.py post <channel> <project> <short_id> [opts] newest render of a cutcannon short + its post kit
  ytpost.py post <channel> --video FILE [--meta FILE]  any video; meta defaults to <video>_post.json
  ytpost.py queue <channel> [--offline]                recent and scheduled uploads, with live status
  ytpost.py set <channel> [key=value ...]              show or change the channel's settings, e.g.
                                                       slots=10:00,18:00  category_id=28  made_for_kids=no

post options:
  --at "YYYY-MM-DD HH:MM"  publish time, in the channel's time zone
  --next                   next free slot from the channel's settings (the default)
  --slots 10:00,18:00      use these daily slots for this upload's --next, not the settings'
  --playlist ID            also add to this playlist (default: the settings' playlist_id)
  --synthetic              disclose realistic altered or synthetic content (YouTube's AI label)
  --made-for-kids yes|no   YouTube's audience designation for this upload (else the meta file's
                           youtube.made_for_kids, else the channel's made_for_kids setting)
  --category N             YouTube category id (default from settings; 10 is Music)
  --thumbnail FILE         custom thumbnail (long-form videos; Shorts don't take one)
  --no-captions            don't upload the .srt next to the video as a caption track
  --dry-run                show what would be uploaded; no sign-in needed, nothing is sent
  --force                  upload again even though this file was already uploaded

Per-channel files in ~/.config/cutcannon/youtube/ (directory 0700, files 0600):
  client_secret.json     the Desktop OAuth client from Google Cloud (shared by all channels)
  <channel>.token.json   the channel's refresh token (written by auth)
  <channel>.json         settings (ytpost.py set): channel_id, tz, slots, category_id, playlist_id,
                         made_for_kids, min_lead_minutes, caption_language. Defaults: one slot a day
                         at 10:00 America/Los_Angeles, category 22 (People & Blogs, YouTube's own
                         default). made_for_kids has no default: uploads stop until it's chosen.
  <channel>.lock         held during an upload, so overlapping runs can't pick the same slot
Next to each video, .<video>_youtube.lock is held during its upload, so it can't go up twice at once.
  <channel>.log.jsonl    one line per upload (used by --next and queue)
Each upload also writes <video>_youtube.json next to the video, which stops a second upload.

Permissions (chosen at sign-in, kept in the settings as "scope"; change them by signing in again):
  full    (default) youtube.upload + youtube.force-ssl: everything, including caption tracks and
          playlists. The token can also edit and delete the channel's videos and comments.
  upload  youtube.upload + youtube.readonly: uploads, thumbnails, the channel check and queue, but
          no caption tracks or playlists. The token can add videos, replace the thumbnail of any of
          the channel's videos and see the whole channel (private videos too), but can't delete
          videos or change their titles, descriptions or privacy.
Revoke either one at Google Account > Security > Third-party apps.

The meta file is a cutcannon post kit (<tag>_post.json). Only its "youtube" section is used:
  {"youtube": {"title": "...", "description": "...", "hashtags": "#Shorts", "tags": ["..."],
               "made_for_kids": false}}        (made_for_kids is optional)
For a cutcannon short, the project's credit line goes in the description, as in the _post.md that
postkit writes: post.json's "credits", or by default "Full episode: {episode_link}". A project with
no episode link needs "credits": "" in its post.json (no credit line) or an episode_link; a video
given with --video gets no credit line.
"""
import argparse
import datetime as dt
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

CONF = Path.home() / ".config" / "cutcannon" / "youtube"
AUTH = "https://www.googleapis.com/auth/"
SCOPE_SETS = {
    "full": [AUTH + "youtube.upload", AUTH + "youtube.force-ssl"],   # + captions, playlists, edit, delete
    "upload": [AUTH + "youtube.upload", AUTH + "youtube.readonly"],  # add videos, thumbnails, read
}
MANAGE = AUTH + "youtube.force-ssl"   # what caption tracks and playlist adds need
REDIRECT = "http://127.0.0.1:8765/"
DEFAULTS = {"tz": "America/Los_Angeles", "slots": ["10:00"], "category_id": "22",
            "playlist_id": None, "made_for_kids": None, "min_lead_minutes": 120,
            "caption_language": "en"}
SETTABLE = {
    "slots": "daily publish times for --next, comma-separated HH:MM (e.g. 10:00,18:00)",
    "tz": "time zone for slots and --at (e.g. America/Los_Angeles)",
    "category_id": "YouTube category: 28 Science & Technology, 10 Music, 22 People & Blogs, 24 Entertainment",
    "playlist_id": "playlist every upload is added to (none to clear)",
    "made_for_kids": "yes or no: YouTube's made-for-kids designation for uploads (no default; required)",
    "min_lead_minutes": "--next never picks a slot sooner than this (at least 15)",
    "caption_language": "language of the .srt caption track (e.g. en)",
}
RETRY_STATUS = (500, 502, 503, 504)

os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


def die(msg):
    sys.exit(f"ytpost: {msg}")


def private_write(path, text):
    CONF.mkdir(parents=True, exist_ok=True)
    os.chmod(CONF, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(path, 0o600)


LOCKS = []   # open lock files; each lock is held until the process exits


def hold_lock(path, what):
    """Exclusive lock on path, waiting (and saying so) while another ytpost holds it."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fh = open(path, "a")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"waiting for another ytpost upload of {what} to finish...", flush=True)
        fcntl.flock(fh, fcntl.LOCK_EX)
    LOCKS.append(fh)


def yes_no(v, what):
    """True/False from yes/no (or a JSON boolean); None stays None."""
    if v is None or isinstance(v, bool):
        return v
    t = str(v).strip().lower()
    if t in ("yes", "y", "true"):
        return True
    if t in ("no", "n", "false"):
        return False
    die(f"{what} must be yes or no (got {v!r})")


def settings(ch):
    s = dict(DEFAULTS)
    f = CONF / f"{ch}.json"
    if f.exists():
        s.update(json.loads(f.read_text()))
    return s


def utc_iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_utc_iso(text, tz):
    return dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).astimezone(tz)


# --- Google sign-in -------------------------------------------------------------------------

def cmd_auth(a):
    from google_auth_oauthlib.flow import Flow
    secret = CONF / "client_secret.json"
    if a.client_secret:
        src = Path(a.client_secret).expanduser()
        if "installed" not in json.loads(src.read_text()):
            die(f"{src} isn't a Desktop app client (create one of type 'Desktop app')")
        private_write(secret, src.read_text())
    if not secret.exists():
        die(f"no client secret yet: run  ytpost.py auth {a.channel} --client-secret FILE")
    pending = CONF / f"{a.channel}.pending.json"

    if not a.code:
        scope = a.scope or settings(a.channel).get("scope", "full")
        flow = Flow.from_client_secrets_file(str(secret), scopes=SCOPE_SETS[scope], redirect_uri=REDIRECT,
                                             autogenerate_code_verifier=True)
        url, state = flow.authorization_url(access_type="offline", prompt="consent")
        private_write(pending, json.dumps({"state": state, "code_verifier": flow.code_verifier,
                                           "scope": scope}))
        print(f"Permissions: {scope} ({', '.join(s.removeprefix(AUTH) for s in SCOPE_SETS[scope])})")
        print("Open this link, sign in, and pick the channel:\n\n" + url + "\n")
        print("Google then sends you to a 127.0.0.1 page that won't load. That's expected:\n"
              f"copy that page's full address and run\n\n  ytpost.py auth {a.channel} --code '<address>'")
        return

    if not pending.exists():
        die(f"no sign-in in progress: run  ytpost.py auth {a.channel}  first")
    p = json.loads(pending.read_text())
    code = a.code.strip()
    if code.startswith("http"):
        q = parse_qs(urlparse(code).query)
        if q.get("error"):
            die(f"Google returned an error: {q['error'][0]}")
        if q.get("state", [p["state"]])[0] != p["state"]:
            die(f"that address is from a different sign-in: run  ytpost.py auth {a.channel}  again")
        code = (q.get("code") or [""])[0]
    if not code:
        die("no code in that address")
    if a.scope and a.scope != p["scope"]:
        die(f"this sign-in was started with --scope {p['scope']}; finish it without --scope, or start over")
    flow = Flow.from_client_secrets_file(str(secret), scopes=SCOPE_SETS[p["scope"]], redirect_uri=REDIRECT,
                                         state=p["state"], code_verifier=p["code_verifier"])
    flow.fetch_token(code=code)
    creds = flow.credentials
    if not creds.refresh_token:
        die(f"Google sent no refresh token: run  ytpost.py auth {a.channel}  again")
    private_write(CONF / f"{a.channel}.token.json", creds.to_json())
    pending.unlink()

    items = youtube(a.channel)[0].channels().list(part="snippet", mine=True).execute().get("items", [])
    if not items:
        die("signed in, but that Google account has no YouTube channel")
    chan = items[0]
    s = settings(a.channel)
    s.update(channel_id=chan["id"], channel_title=chan["snippet"]["title"], scope=p["scope"])
    private_write(CONF / f"{a.channel}.json", json.dumps(s, indent=2) + "\n")
    print(f"Signed in: '{a.channel}' is the YouTube channel \"{chan['snippet']['title']}\" ({chan['id']}),"
          f" permissions: {p['scope']}.")
    print(f"Settings: {CONF / (a.channel + '.json')}")


def credentials(ch):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    f = CONF / f"{ch}.token.json"
    if not f.exists():
        die(f"'{ch}' isn't signed in: run  ytpost.py auth {ch}")
    creds = Credentials.from_authorized_user_file(str(f))   # the scopes granted at sign-in
    if not creds.valid:
        try:
            creds.refresh(Request())
        except Exception as e:  # revoked, expired (7-day Testing apps), password change
            die(f"the sign-in for '{ch}' stopped working ({e}). Run  ytpost.py auth {ch}  again.")
        private_write(f, creds.to_json())
    return creds


def youtube(ch):
    """(client, granted scopes)"""
    from googleapiclient.discovery import build
    creds = credentials(ch)
    return build("youtube", "v3", credentials=creds, cache_discovery=False), set(creds.scopes or [])


def api_error(e):
    try:
        err = json.loads(e.content.decode())["error"]
        reasons = {x.get("reason") for x in err.get("errors", [])}
        if reasons & {"quotaExceeded", "uploadLimitExceeded", "rateLimitExceeded"}:
            return f"{err.get('message')} (YouTube API quota; it resets at midnight Pacific)"
        return err.get("message") or str(e)
    except Exception:
        return str(e)


# --- What to upload -------------------------------------------------------------------------

def cutcannon_source(project, sid):
    import plan as P
    d = P.proj_dir(project)
    rs = sorted((d / "renders").glob(f"{sid}_v[0-9][0-9][0-9].mp4"))
    if not rs:
        die(f"{project} {sid}: not rendered yet")
    mp4 = rs[-1]
    meta = mp4.with_name(f"{mp4.stem}_post.json")
    if not meta.exists():
        die(f"{meta.name} is missing: write the copy and run postkit first")
    shared_f = d / "post.json"
    return mp4, meta, json.loads(shared_f.read_text()) if shared_f.exists() else {}


def compose(meta_f, shared, project=False):
    """Title, description, tags and made_for_kids, checked against YouTube's limits. For a cutcannon
    project the credit line follows postkit: post.json's "credits", default "Full episode: {episode_link}"."""
    yt = json.loads(meta_f.read_text()).get("youtube") or {}
    title = " ".join((yt.get("title") or "").split())
    parts = [(yt.get("description") or "").strip()]
    credits = (shared.get("credits", "Full episode: {episode_link}") or "").strip() if project else ""
    if "{episode_link}" in credits:
        if not shared.get("episode_link"):
            die("this short's post kit credits the full episode, but the project's post.json has no "
                "episode_link: set it, or set \"credits\": \"\" in post.json for no credit line")
        credits = credits.replace("{episode_link}", shared["episode_link"])
    if credits:
        parts.append(credits)
    if yt.get("hashtags"):
        parts.append(yt["hashtags"].strip())
    desc = "\n\n".join(p for p in parts if p)
    tags = [t.strip() for t in yt.get("tags", []) if t.strip()]

    probs = []
    if not 1 <= len(title) <= 100:
        probs.append(f"title must be 1-100 characters (is {len(title)})")
    if len(desc.encode()) > 5000:
        probs.append(f"description must be at most 5000 bytes (is {len(desc.encode())})")
    if re.search(r"[<>]", title + desc):
        probs.append("YouTube doesn't allow < or > in the title or description")
    if "[EPISODE LINK]" in desc:
        probs.append("the description still has the [EPISODE LINK] placeholder")
    if sum(len(t) + (2 if " " in t else 0) for t in tags) + max(len(tags) - 1, 0) > 500:
        probs.append("tags are over YouTube's 500-character limit")
    if probs:
        die(f"{meta_f.name}: " + "; ".join(probs))
    return title, desc, tags, yes_no(yt.get("made_for_kids"), f"{meta_f.name}: youtube.made_for_kids")


def probe(mp4):
    """(width, height, seconds), rotation applied; None if ffprobe can't tell."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=width,height:stream_side_data=rotation:format=duration",
                              "-of", "json", str(mp4)], capture_output=True, text=True, check=True).stdout
        j = json.loads(out)
        st = j["streams"][0]
        w, h = st["width"], st["height"]
        rot = next((abs(int(sd.get("rotation", 0))) for sd in st.get("side_data_list", [])), 0)
        if rot in (90, 270):
            w, h = h, w
        return w, h, float(j["format"]["duration"])
    except Exception:
        return None


# --- When -----------------------------------------------------------------------------------

def read_log(ch):
    f = CONF / f"{ch}.log.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines() if x.strip()] if f.exists() else []


def parse_slots(text):
    out = set()
    for x in text.split(","):
        try:
            out.add(dt.time.fromisoformat(x.strip()).strftime("%H:%M"))
        except ValueError:
            die(f"bad slot time {x.strip()!r}: use HH:MM, e.g. 10:00,18:00")
    return sorted(out)


def next_slot(s, ch, slots=None):
    tz = ZoneInfo(s["tz"])
    now = dt.datetime.now(tz)
    earliest = now + dt.timedelta(minutes=int(s["min_lead_minutes"]))
    taken = {e.get("publish_at") for e in read_log(ch)}
    slots = sorted(dt.time.fromisoformat(x) for x in (slots or s["slots"]))
    if not slots:
        die("the channel settings have no slots; add some, e.g. \"slots\": [\"10:00\"]")
    day = now.date()
    for _ in range(366):
        for t in slots:
            cand = dt.datetime.combine(day, t, tz)
            if cand >= earliest and utc_iso(cand) not in taken:
                return cand
        day += dt.timedelta(days=1)
    die("no free slot in the next year")


def parse_at(text, s):
    tz = ZoneInfo(s["tz"])
    try:
        t = dt.datetime.fromisoformat(text.strip().replace(" ", "T"))
    except ValueError:
        die(f'--at wants "YYYY-MM-DD HH:MM" (got {text!r})')
    t = t if t.tzinfo else t.replace(tzinfo=tz)
    if t < dt.datetime.now(tz) + dt.timedelta(minutes=15):
        die("--at must be at least 15 minutes from now")
    return t


# --- Upload ---------------------------------------------------------------------------------

def run_upload(req):
    from googleapiclient.errors import HttpError
    resp, tries, shown = None, 0, -1
    while resp is None:
        try:
            status, resp = req.next_chunk()
            if status and int(status.progress() * 10) != shown:
                shown = int(status.progress() * 10)
                print(f"  {shown * 10}%", flush=True)
        except HttpError as e:
            if e.resp.status in RETRY_STATUS and tries < 6:
                tries += 1
                time.sleep(2 ** tries)
                continue
            die(f"upload failed: {api_error(e)}")
        except (OSError, TimeoutError) as e:
            if tries < 6:
                tries += 1
                time.sleep(2 ** tries)
                continue
            die(f"upload failed: {e}")
    return resp


def extra(label, fn):
    """Captions, playlist, thumbnail: report a failure but keep the upload."""
    from googleapiclient.errors import HttpError
    try:
        fn()
        print(f"{label}: done")
        return True
    except HttpError as e:
        print(f"{label}: FAILED ({api_error(e)})")
        return False


def cmd_post(a):
    s = settings(a.channel)
    if a.video:
        mp4 = Path(a.video).expanduser().resolve()
        meta = Path(a.meta).expanduser() if a.meta else mp4.with_name(f"{mp4.stem}_post.json")
        shared = {}
        if not mp4.exists():
            die(f"{mp4} not found")
        if not meta.exists():
            die(f"{meta} not found (give one with --meta)")
    elif a.project and a.short:
        mp4, meta, shared = cutcannon_source(a.project, a.short)
    else:
        die("give <project> <short_id>, or --video FILE")

    title, desc, tags, meta_kids = compose(meta, shared, project=not a.video)
    for value, source in ((yes_no(a.made_for_kids, "--made-for-kids"), "--made-for-kids"),
                          (meta_kids, meta.name), (yes_no(s.get("made_for_kids"), "setting"), "channel setting")):
        if value is not None:
            kids, kids_from = value, source
            break
    else:
        kids, kids_from = None, None
        if not a.dry_run:
            die(f"choose the audience first: ytpost.py set {a.channel} made_for_kids=no (or yes), "
                "or --made-for-kids yes|no for this upload")
    if not a.dry_run:
        # Held until the process exits: the duplicate check, the slot choice and the records below
        # can't interleave with another upload of this video or to this channel.
        hold_lock(mp4.with_name(f".{mp4.stem}_youtube.lock"), mp4.name)
        hold_lock(CONF / f"{a.channel}.lock", f"channel '{a.channel}'")
    record_f = mp4.with_name(f"{mp4.stem}_youtube.json")
    if record_f.exists() and not a.force:
        die(f"{mp4.name} was already uploaded as {json.loads(record_f.read_text())['url']} "
            "(--force uploads it again)")
    if a.at and a.slots:
        die("--slots only applies to --next; give --at or --slots, not both")
    when = parse_at(a.at, s) if a.at else next_slot(s, a.channel, parse_slots(a.slots) if a.slots else None)
    srt = mp4.with_suffix(".srt")
    srt = srt if srt.exists() and not a.no_captions else None
    thumb = Path(a.thumbnail).expanduser() if a.thumbnail else None
    if thumb and not thumb.exists():
        die(f"{thumb} not found")
    playlist = a.playlist or s.get("playlist_id")
    category = str(a.category or s["category_id"])
    manage = s.get("scope", "full") == "full"
    shape = probe(mp4)
    if shape:
        w, h, secs = shape
        kind = "Short" if h >= w and secs <= 180 else "regular video"
        shape_txt = f"{w}x{h}, {secs:.1f} s: YouTube will treat it as a {kind}"
    else:
        shape_txt = "unknown (ffprobe failed)"

    print(f"channel:     {s.get('channel_title', a.channel + ' (not signed in yet)')}")
    print(f"video:       {mp4}  ({mp4.stat().st_size / 1e6:.1f} MB)")
    print(f"format:      {shape_txt}")
    print(f"publishes:   {when:%a %Y-%m-%d %H:%M %Z}  (private until then)")
    print(f"title:       {title}")
    print(f"tags:        {', '.join(tags) or '-'}")
    print(f"category:    {category}    AI disclosure: {'yes' if a.synthetic else 'no'}")
    print("audience:    " + (f"{'made for kids' if kids else 'not made for kids'} (from {kids_from})"
                             if kids is not None else
                             f"NOT SET: set {a.channel} made_for_kids=no|yes, or --made-for-kids"))
    skip = "" if manage else " (skipped: needs --scope full)"
    print(f"captions:    {(srt.name + skip) if srt else '-'}    playlist: {(playlist + skip) if playlist else '-'}"
          f"    thumbnail: {thumb.name if thumb else '-'}")
    print("description:\n  " + desc.replace("\n", "\n  "))
    if a.dry_run:
        print("\n(dry run: nothing uploaded)")
        return

    from googleapiclient.http import MediaFileUpload
    yt, granted = youtube(a.channel)
    manage = MANAGE in granted
    items = yt.channels().list(part="id", mine=True).execute().get("items", [])
    got = items[0]["id"] if items else None
    if s.get("channel_id") and got != s["channel_id"]:
        die(f"the signed-in channel ({got}) isn't '{a.channel}' ({s['channel_id']}): run auth again")

    body = {"snippet": {"title": title, "description": desc, "tags": tags, "categoryId": category},
            "status": {"privacyStatus": "private", "publishAt": utc_iso(when),
                       "selfDeclaredMadeForKids": kids, "containsSyntheticMedia": bool(a.synthetic)}}
    media = MediaFileUpload(str(mp4), mimetype="video/*", chunksize=16 * 1024 * 1024, resumable=True)
    print("\nuploading...")
    vid = run_upload(yt.videos().insert(part="snippet,status", body=body, media_body=media))["id"]
    rec = {"video_id": vid, "url": f"https://youtu.be/{vid}", "studio": f"https://studio.youtube.com/video/{vid}/edit",
           "channel": a.channel, "channel_id": got, "title": title, "publish_at": utc_iso(when),
           "file": str(mp4), "uploaded_at": utc_iso(dt.datetime.now(dt.timezone.utc))}
    # Record it before anything else can fail, so a retry can't upload it twice.
    record_f.write_text(json.dumps(rec, indent=2) + "\n")
    with open(CONF / f"{a.channel}.log.jsonl", "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"uploaded:    {rec['url']}  (scheduled {when:%a %m-%d %H:%M %Z})")
    print(f"studio:      {rec['studio']}")

    if (srt or playlist) and not manage:
        print(f"captions/playlist: skipped (this sign-in can't add them; ytpost.py auth {a.channel} --scope full)")
    if srt and manage:
        rec["captions"] = extra("captions", lambda: yt.captions().insert(
            part="snippet",
            body={"snippet": {"videoId": vid, "language": s["caption_language"], "name": ""}},
            media_body=MediaFileUpload(str(srt), mimetype="application/octet-stream")).execute())
    if playlist and manage:
        rec["playlist"] = playlist if extra("playlist", lambda: yt.playlistItems().insert(
            part="snippet",
            body={"snippet": {"playlistId": playlist,
                              "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()) else None
    if thumb:
        rec["thumbnail"] = extra("thumbnail", lambda: yt.thumbnails().set(
            videoId=vid, media_body=MediaFileUpload(str(thumb))).execute())
    record_f.write_text(json.dumps(rec, indent=2) + "\n")


# --- Settings and queue ---------------------------------------------------------------------

def cmd_set(a):
    s = settings(a.channel)
    for kv in a.pairs:
        k, sep, v = kv.partition("=")
        v = v.strip()
        if k == "scope":
            die(f"permissions change only by signing in again: ytpost.py auth {a.channel} --scope full|upload")
        if not sep or k not in SETTABLE:
            die("use key=value, where key is one of: " + ", ".join(SETTABLE))
        if k == "slots":
            v = parse_slots(v)
        elif k == "tz":
            try:
                ZoneInfo(v)
            except Exception:
                die(f"unknown time zone {v!r}")
        elif k == "min_lead_minutes":
            if not v.isdigit() or int(v) < 15:
                die("min_lead_minutes must be a whole number, at least 15")
            v = int(v)
        elif k == "category_id" and not v.isdigit():
            die("category_id is a number, e.g. 28")
        elif k == "playlist_id" and v.lower() in ("", "none"):
            v = None
        elif k == "made_for_kids":
            v = yes_no(v, "made_for_kids")
        s[k] = v
    if a.pairs:
        private_write(CONF / f"{a.channel}.json", json.dumps(s, indent=2) + "\n")
    for k in ("channel_title", "channel_id", "scope", *SETTABLE):
        if k in s:
            v = s[k]
            if isinstance(v, list):
                v = ", ".join(v)
            elif isinstance(v, bool):
                v = "yes" if v else "no"
            elif v is None:
                v = "not set"
            print(f"{k:<17} {v}")


def cmd_queue(a):
    s = settings(a.channel)
    tz = ZoneInfo(s["tz"])
    recent = read_log(a.channel)[-25:]
    if not recent:
        print("nothing uploaded yet")
        return
    live = {}
    if not a.offline:
        yt = youtube(a.channel)[0]
        ids = [e["video_id"] for e in recent]
        for i in range(0, len(ids), 50):
            resp = yt.videos().list(part="status", id=",".join(ids[i:i + 50])).execute()
            live.update({it["id"]: it["status"] for it in resp.get("items", [])})
    for e in sorted(recent, key=lambda e: e["publish_at"]):
        st = live.get(e["video_id"])
        if a.offline:
            state = "-"
        elif st is None:
            state = "deleted"
        elif st.get("uploadStatus") in ("rejected", "failed"):
            state = st["uploadStatus"]
        elif st.get("privacyStatus") == "private" and st.get("publishAt"):
            state = "scheduled"
        else:
            state = st.get("privacyStatus", "?")
        print(f"{from_utc_iso(e['publish_at'], tz):%a %m-%d %H:%M}  {state:<9}  {e['url']}  {e['title'][:60]}")


def main():
    ap = argparse.ArgumentParser(prog="ytpost.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("auth")
    p.add_argument("channel")
    p.add_argument("--client-secret")
    p.add_argument("--code")
    p.add_argument("--scope", choices=sorted(SCOPE_SETS))
    p = sub.add_parser("post")
    p.add_argument("channel")
    p.add_argument("project", nargs="?")
    p.add_argument("short", nargs="?")
    p.add_argument("--video")
    p.add_argument("--meta")
    when = p.add_mutually_exclusive_group()
    when.add_argument("--at")
    when.add_argument("--next", action="store_true")
    p.add_argument("--slots")
    p.add_argument("--playlist")
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--made-for-kids", choices=["yes", "no"])
    p.add_argument("--category")
    p.add_argument("--thumbnail")
    p.add_argument("--no-captions", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("queue")
    p.add_argument("channel")
    p.add_argument("--offline", action="store_true")
    p = sub.add_parser("set")
    p.add_argument("channel")
    p.add_argument("pairs", nargs="*", metavar="key=value")
    if len(sys.argv) == 1:
        sys.exit(__doc__)
    a = ap.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", a.channel):
        die("channel names are lowercase letters, digits, - and _ (e.g. mychannel)")
    {"auth": cmd_auth, "post": cmd_post, "queue": cmd_queue, "set": cmd_set}[a.cmd](a)


if __name__ == "__main__":
    main()
