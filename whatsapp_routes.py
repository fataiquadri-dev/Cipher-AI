"""WhatsApp mode for Cipher: stats API for the UI + ingest API for the bot.

Env vars (set in Vercel):
  WA_OWNER_USERNAME  your Cipher username. Only this user can see WhatsApp data.
  WA_INGEST_KEY      long random secret. The bot sends it as the X-WA-Key header.
  WA_TIMEZONE        optional, default Africa/Lagos. Decides where "today" starts.
"""
import json
import os
import re
import sys
import hmac
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import psycopg2
import psycopg2.extras
from flask import Blueprint, request, jsonify
from flask_login import current_user

wa = Blueprint("wa", __name__, url_prefix="/api/whatsapp")
TZNAME = os.environ.get("WA_TIMEZONE", "Africa/Lagos")
TZ = ZoneInfo(TZNAME)


# ---------- helpers ----------
_get_db = None      # filled in by register_whatsapp()
_release_db = None


def register_whatsapp(app, get_db, release_db):
    """Call once from app.py: register_whatsapp(app, get_db, release_db)"""
    global _get_db, _release_db
    _get_db, _release_db = get_db, release_db
    app.register_blueprint(wa)


def query(sql, args=(), one=False):
    conn = _get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, args)
            rows = cur.fetchall() if cur.description else []
        conn.commit()
        if one:
            return rows[0] if rows else None
        return rows
    finally:
        _release_db(conn)


def is_owner():
    owner = os.environ.get("WA_OWNER_USERNAME", "").strip().lower()
    if not owner or not current_user.is_authenticated:
        return False
    return str(getattr(current_user, "username", "")).strip().lower() == owner


def has_key():
    key = os.environ.get("WA_INGEST_KEY", "")
    sent = request.headers.get("X-WA-Key", "")
    return bool(key) and hmac.compare_digest(key, sent)


def day_start(days_back=0):
    now = datetime.now(TZ)
    return now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_back)


def label(row):
    return row.get("name") or str(row["jid"]).split("@")[0]


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


# ---------- bot -> Cipher ----------
@wa.post("/ingest")
def ingest():
    """Bot reports every message. Returns whether the sender is a brand-new contact.

    JSON: {jid, name?, direction: "in"|"out", body?, auto_reply?, history?, ts?}
    history=true marks old synced messages: saved, but never treated as "new contact".
    """
    if not has_key():
        return jsonify(error="unauthorized"), 401
    d = request.get_json(silent=True) or {}
    jid = (d.get("jid") or "").strip()
    direction = d.get("direction", "in")
    if not jid or direction not in ("in", "out"):
        return jsonify(error="bad request"), 400

    try:
        ts = datetime.fromtimestamp(float(d["ts"]), tz=timezone.utc)
    except (KeyError, TypeError, ValueError):
        ts = datetime.now(timezone.utc)

    history = bool(d.get("history"))
    # Anyone you wrote to first, or from old synced history, counts as already known:
    # saved as a contact but never flagged "new", so the bot won't auto-reply to them.
    row = query(
        "insert into wa_contacts(jid, name, first_seen, greeted) values (%s,%s,%s,%s) "
        "on conflict (jid) do nothing returning jid",
        (jid, d.get("name") if direction == "in" else None, ts, history or direction == "out"),
        one=True,
    )
    new_contact = row is not None and direction == "in" and not history

    query(
        "insert into wa_messages(jid, direction, body, auto_reply, sent_at) values (%s,%s,%s,%s,%s)",
        (jid, direction, (d.get("body") or "")[:2000], bool(d.get("auto_reply")), ts),
    )
    if d.get("auto_reply"):
        query("update wa_contacts set greeted = true where jid = %s", (jid,))
    return jsonify(ok=True, new_contact=new_contact)


@wa.get("/posts/due")
def posts_due():
    """Bot polls this for channel posts that should go out now."""
    if not has_key():
        return jsonify(error="unauthorized"), 401
    rows = query(
        "update wa_posts set status='sending' where id in ("
        "select id from wa_posts where status='pending' and scheduled_at <= now() "
        "order by scheduled_at limit 5) returning id, body"
    )
    return jsonify(posts=rows)


@wa.get("/outbox/due")
def outbox_due():
    """Bot polls this for messages you confirmed in Cipher's WhatsApp screen."""
    if not has_key():
        return jsonify(error="unauthorized"), 401
    rows = query(
        "update wa_outbox set status='sending' where id in ("
        "select id from wa_outbox where status='pending' order by id limit 5) "
        "returning id, jid, body"
    )
    return jsonify(messages=rows)


@wa.post("/outbox/<int:msg_id>/done")
def outbox_done(msg_id):
    if not has_key():
        return jsonify(error="unauthorized"), 401
    ok = (request.get_json(silent=True) or {}).get("ok", True)
    row = query(
        "update wa_outbox set status=%s where id=%s returning jid, body",
        ("sent" if ok else "failed", msg_id),
        one=True,
    )
    if ok and row:
        query(
            "insert into wa_messages(jid, direction, body) values (%s, 'out', %s)",
            (row["jid"], row["body"]),
        )
    return jsonify(ok=True)


@wa.post("/posts/<int:post_id>/done")
def post_done(post_id):
    if not has_key():
        return jsonify(error="unauthorized"), 401
    status = "sent" if (request.get_json(silent=True) or {}).get("ok", True) else "failed"
    query("update wa_posts set status=%s where id=%s", (status, post_id))
    return jsonify(ok=True)


# ---------- owner -> Cipher ----------
@wa.post("/posts")
def schedule_post():
    """Schedule a channel post. JSON: {body, at} where at is ISO time like 2026-10-15T18:00."""
    if not is_owner():
        return jsonify(error="private"), 403
    d = request.get_json(silent=True) or {}
    body = (d.get("body") or "").strip()
    try:
        at = datetime.fromisoformat(d.get("at", ""))
    except ValueError:
        return jsonify(error="bad time"), 400
    if not body:
        return jsonify(error="empty post"), 400
    if at.tzinfo is None:
        at = at.replace(tzinfo=TZ)
    row = query(
        "insert into wa_posts(body, scheduled_at) values (%s,%s) returning id", (body, at), one=True
    )
    return jsonify(ok=True, id=row["id"])


@wa.post("/ask")
def ask():
    if not is_owner():
        return jsonify(answer="WhatsApp mode is private to the account owner."), 403
    d = request.get_json(silent=True) or {}
    raw = (d.get("question") or "").strip()
    hist = []
    for h in (d.get("history") or [])[-10:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str):
            hist.append({"role": h["role"], "content": h["content"][:600]})
    return jsonify(answer=answer(raw.lower(), raw, hist))


@wa.get("/status")
def status():
    if not is_owner():
        return jsonify(error="private"), 403
    online, age = bot_status()
    return jsonify(online=online, seconds=age)


# ---------- commands (post / send, always with a confirm step) ----------
POST_RE = re.compile(
    r"^(?:please\s+|can you\s+|help me\s+(?:to\s+)?)?(?:post|publish)\s+(.+?)\s+(?:on|to|in)\s+"
    r"(?:my\s+)?(?:whatsapp\s+)?channel(?:\s+(?:at|by)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?)?\s*[.!]?$",
    re.I,
)
SEND_RE = re.compile(
    r"^(?:please\s+|can you\s+|help me\s+(?:to\s+)?)?(?:send|text|message|msg)\s+(?:a\s+)?(?:message\s+)?"
    r"(?:to\s+)?(.+?)\s*(?:,|:|\s+saying\s+|\s+say\s+|\s+and\s+tell\s+(?:him|her|them)\s+|"
    r"\s+tell\s+(?:him|her|them)\s+|\s+that\s+)\s*(.+)$",
    re.I,
)
YES_RE = re.compile(r"^(yes|yep|yeah|confirm|send it|go ahead|ok|okay|do it)[.! ]*$", re.I)
NO_RE = re.compile(r"^(no|nope|cancel|stop|don'?t)[.! ]*$", re.I)
QUOTES = "\"'\u201c\u201d"


def norm(s):
    s = (s or "").replace("\u00f8", "o").replace("\u00d8", "O")
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    ).lower()


def parse_time(h, m, ap):
    hour, minute = int(h), int(m or 0)
    if ap:
        if ap.lower() == "pm" and hour < 12:
            hour += 12
        if ap.lower() == "am" and hour == 12:
            hour = 0
    if hour > 23 or minute > 59:
        return None
    now = datetime.now(TZ)
    at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return at if at > now else at + timedelta(days=1)


def confirm_pending():
    ob = query(
        "select id, name, created_at from wa_outbox where status='awaiting' "
        "and created_at > now() - interval '15 minutes' order by created_at desc limit 1",
        one=True,
    )
    po = query(
        "select id, scheduled_at, created_at from wa_posts where status='awaiting' "
        "and created_at > now() - interval '15 minutes' order by created_at desc limit 1",
        one=True,
    )
    if not ob and not po:
        return "Nothing is waiting for your confirmation."
    if ob and (not po or ob["created_at"] >= po["created_at"]):
        query("update wa_outbox set status='pending' where id=%s", (ob["id"],))
        return f"Sending to {ob.get('name') or 'them'} in a few seconds."
    query("update wa_posts set status='pending' where id=%s", (po["id"],))
    if po["scheduled_at"] > datetime.now(timezone.utc) + timedelta(minutes=1):
        return f"Scheduled for {po['scheduled_at'].astimezone(TZ):%a %H:%M}. It will post automatically."
    return "Queued. It will be posted to your channel within a minute."


def cancel_pending():
    a = query("update wa_outbox set status='cancelled' where status='awaiting' returning id")
    b = query("update wa_posts set status='cancelled' where status='awaiting' returning id")
    return "Cancelled." if (a or b) else "Nothing to cancel."


def queue_post(body, at=None):
    """Prepare a channel post for confirmation. at=None means as soon as it is confirmed."""
    body = (body or "").strip().strip(QUOTES)
    if not body:
        return None
    body = body[0].upper() + body[1:]
    when = f"at {at:%a %d %b %H:%M}" if at else "now"
    query(
        "insert into wa_posts(body, scheduled_at, status) values (%s,%s,'awaiting')",
        (body, at or datetime.now(TZ)),
    )
    return f'Ready to post to your channel {when}:\n"{body}"\n\nReply "yes" to confirm or "cancel".'


def queue_message(who, body):
    """Find one contact by name or number and prepare a message for confirmation."""
    who = (who or "").strip()
    body = (body or "").strip().strip(QUOTES)
    if not who or not body:
        return None
    digits = re.sub(r"\D", "", who)
    rows = query("select jid, name from wa_contacts order by first_seen desc limit 1000")
    if len(digits) >= 7:
        matches = [r for r in rows if digits in r["jid"].split("@")[0]]
    else:
        target = norm(who)
        matches = [r for r in rows if r["name"] and target in norm(r["name"])]
    if not matches:
        return f"I couldn't find a contact called {who}. They need to have chatted with you since the bot connected."
    if len(matches) > 1:
        return "Several contacts match: " + ", ".join(label(r) for r in matches[:5]) + ". Please be more specific."
    c = matches[0]
    body = body[0].upper() + body[1:]
    query("insert into wa_outbox(jid, name, body) values (%s,%s,%s)", (c["jid"], c.get("name"), body))
    return f'Ready to send to {label(c)}:\n"{body}"\n\nReply "yes" to confirm or "cancel".'


def run_action(a):
    """Runs an action the AI proposed. It only queues it; nothing goes out until you confirm."""
    kind = str(a.get("type") or "").lower()
    if kind == "post":
        at = None
        if a.get("at"):
            try:
                at = datetime.fromisoformat(str(a["at"]))
            except ValueError:
                return None
            if at.tzinfo is None:
                at = at.replace(tzinfo=TZ)
            if at < datetime.now(TZ) - timedelta(minutes=5):
                return "That time has already passed. Tell me a later time."
        return queue_post(str(a.get("text") or ""), at)
    if kind == "send":
        return queue_message(str(a.get("to") or ""), str(a.get("text") or ""))
    return None


CANCEL_POSTS_RE = re.compile(
    r"^(?:please\s+)?(?:cancel|delete|remove|clear)\s+(?:all\s+)?(?:my\s+)?(?:scheduled\s+|pending\s+)?"
    r"(?:channel\s+)?posts?[.!]?$",
    re.I,
)


def handle_command(raw):
    text = raw.strip()
    if YES_RE.match(text):
        return confirm_pending()
    if NO_RE.match(text):
        return cancel_pending()
    if CANCEL_POSTS_RE.match(text):
        rows = query("update wa_posts set status='cancelled' where status in ('pending','awaiting') returning id")
        return f"Cancelled {plural(len(rows), 'scheduled post')}." if rows else "There are no scheduled posts to cancel."

    m = POST_RE.match(text)
    if m:
        body, h, mi, ap = m.groups()
        at = parse_time(h, mi, ap) if h else None
        if h and at is None:
            return "That time doesn't look right. Try something like: at 6pm"
        return queue_post(body, at)

    m = SEND_RE.match(text)
    if m:
        body = re.sub(
            r"^(?:tell\s+(?:him|her|them)\s+(?:that\s+)?|say(?:ing)?\s+|that\s+)", "", m.group(2).strip(), flags=re.I
        )
        return queue_message(m.group(1), body)
    return None


# ---------- bot status + AI chat ----------
def bot_status():
    """The bot writes a heartbeat to the database every minute while connected."""
    try:
        row = query("select value from wa_auth where key='heartbeat'", one=True)
        if not row:
            return False, None
        age = int(datetime.now(timezone.utc).timestamp() - int(row["value"]) / 1000)
        return age < 150, age
    except Exception:
        return False, None


def _ask_ai_fn():
    """Borrow Cipher's own AI function from app.py (Groq, then Gemini, then OpenRouter)."""
    for name in ("app", "__main__"):
        mod = sys.modules.get(name)
        fn = getattr(mod, "ask_ai", None) if mod else None
        if fn:
            return fn
    return None


HELP = (
    "I can answer questions like:\n"
    "- How many messages today?\n- Messages per day\n- New contacts today\n"
    "- Which chats are waiting for my reply?\n- Who messaged me the most?\n- Scheduled channel posts\n\n"
    "Or tell me what to do:\n- Post <text> on my channel at 6pm\n- Send a message to <name>: <text>"
)


def ai_reply(raw, history):
    fn = _ask_ai_fn()
    if not fn:
        return HELP
    try:
        today, week = day_start(0), day_start(6)
        msgs = query("select count(*) c from wa_messages where direction='in' and sent_at >= %s", (today,), one=True)["c"]
        new = query("select count(*) c from wa_contacts where first_seen >= %s", (today,), one=True)["c"]
        new_week = query("select count(*) c from wa_contacts where first_seen >= %s", (week,), one=True)["c"]
        online, _ = bot_status()
        waiting = query(
            "select distinct on (m.jid) m.jid, m.direction, m.sent_at, c.name "
            "from wa_messages m left join wa_contacts c using (jid) "
            "where not (m.direction='out' and m.auto_reply) order by m.jid, m.sent_at desc"
        )
        waiting = [label(r) for r in waiting if r["direction"] == "in"][:5]
        posts = query(
            "select body, scheduled_at from wa_posts where status='pending' order by scheduled_at limit 3"
        )
        post_txt = "; ".join(f"{r['scheduled_at'].astimezone(TZ):%a %H:%M} '{r['body'][:30]}'" for r in posts) or "none"
    except Exception:
        return HELP
    now = datetime.now(TZ)
    context = (
        "You are Cipher Pro, the advanced WhatsApp assistant inside Cipher (created by Fatai Quadri). "
        "You are chatting with the account owner on their WhatsApp screen, so you two can talk, plan and act together. "
        "Chat naturally about anything: ideas, planning, writing posts or replies, decisions. "
        "Be warm, sharp and interactive, and keep replies short for a phone screen. "
        "You only know the live numbers below and cannot read the content of their chats; never pretend to. "
        "You can queue two actions for them, and the owner must confirm each one before it happens: "
        "(1) post text to their WhatsApp channel, (2) send a WhatsApp message to a contact. "
        "When they clearly want one of these done, reply with ONE line only, nothing else: "
        'ACTION: {"type":"post","text":"...","at":"YYYY-MM-DDTHH:MM or null"} '
        'or ACTION: {"type":"send","to":"contact name or number","text":"..."}. '
        "Times are the owner's local time; null means now. Write the text exactly as it should go out, in the owner's voice. "
        "Never say something was sent or posted; it only goes out after they confirm. "
        f"Local time now: {now:%A %d %B %Y, %H:%M}. "
        f"Live data: bot {'online' if online else 'offline'}; {msgs} messages received today; "
        f"{new} new contacts today and {new_week} in the last 7 days; "
        f"chats waiting for a reply: {', '.join(waiting) or 'none'}; channel posts waiting to go out: {post_txt}."
    )
    try:
        reply = fn(context + "\n\nUser: " + raw, history=history or None) or HELP
    except Exception:
        return HELP
    m = re.search(r"ACTION:\s*(\{.*\})", reply, re.S)
    if m:
        try:
            result = run_action(json.loads(m.group(1)))
        except Exception:
            result = None
        return result or "I couldn't set that up. Try: Post <text> on my channel, or: Send a message to <name>: <text>"
    return reply


POST_STATE = {
    "awaiting": "waiting for your confirmation",
    "sending": "being sent now",
    "sent": "posted",
    "failed": "failed to post",
    "cancelled": "cancelled",
}


# ---------- answers ----------
def answer(q, raw="", history=None):
    if raw:
        cmd = handle_command(raw)
        if cmd:
            return cmd
    today, week = day_start(0), day_start(6)

    if re.search(r"\bbot\b", q) and re.search(r"online|running|awake|connected|alive|working|offline|asleep", q):
        online, age = bot_status()
        if online:
            return "The bot is online and connected to WhatsApp."
        if age is None:
            return "The bot is offline, or has not reported in yet. Check that it is awake on Render and linked to WhatsApp."
        return f"The bot is offline. It last checked in about {age // 60} minutes ago."

    if re.search(r"executed|published|has it been|did it|status of|been posted|posted yet", q):
        rows = query("select body, status, scheduled_at from wa_posts order by id desc limit 5")
        if not rows:
            return "You haven't scheduled any channel posts yet."
        now = datetime.now(timezone.utc)
        lines = []
        for r in rows:
            st = r["status"]
            if st == "pending":
                st = "overdue, the bot hasn't picked it up" if r["scheduled_at"] < now else "scheduled"
            else:
                st = POST_STATE.get(st, st)
            lines.append(f"- {r['scheduled_at'].astimezone(TZ):%a %H:%M} \"{r['body'][:30]}\": {st}")
        out = "Your latest channel posts:\n" + "\n".join(lines)
        if any("overdue" in l for l in lines):
            out += "\n\nOverdue means the bot is asleep or has no channel set. Ask me: is the bot online?"
        return out

    if re.search(r"unanswered|waiting for (my |a )?repl|not replied|unreplied|who.*(waiting|need)", q) and not q.startswith("reply"):
        rows = query(
            "select distinct on (m.jid) m.jid, m.direction, m.sent_at, c.name "
            "from wa_messages m left join wa_contacts c using (jid) "
            "where not (m.direction='out' and m.auto_reply) "
            "order by m.jid, m.sent_at desc"
        )
        waiting = sorted([r for r in rows if r["direction"] == "in"], key=lambda r: r["sent_at"])
        if not waiting:
            return "Nobody is waiting for a reply."
        lines = [f"- {label(r)} ({r['sent_at'].astimezone(TZ):%a %H:%M})" for r in waiting[:10]]
        return (
            f"{plural(len(waiting), 'chat')} waiting for your reply:\n" + "\n".join(lines)
            + '\n\nTo answer one, say: Send a message to <name>: <text>'
        )

    if re.search(r"auto-?repl|welcome repl|greeting", q):
        n = query(
            "select count(*) c from wa_messages where auto_reply and sent_at >= %s", (today,), one=True
        )["c"]
        return f"The bot sent {n} auto-repl{'y' if n == 1 else 'ies'} today."

    if re.search(r"scheduled|channel posts|my posts|queued|upcoming", q):
        rows = query(
            "select body, scheduled_at from wa_posts where status='pending' order by scheduled_at limit 10"
        )
        if not rows:
            return "No channel posts are scheduled."
        lines = [f"- {r['scheduled_at'].astimezone(TZ):%a %d %b, %H:%M}: {r['body'][:60]}" for r in rows]
        return f"{plural(len(rows), 'post')} scheduled:\n" + "\n".join(lines)

    if re.search(r"\b(most|busiest)\b", q) and re.search(r"who|chat|message", q):
        rows = query(
            "select m.jid, c.name, count(*) c from wa_messages m left join wa_contacts c using (jid) "
            "where m.direction='in' and m.sent_at >= %s group by m.jid, c.name order by c desc limit 5",
            (today,),
        )
        if not rows:
            return "No messages received yet today."
        return "Busiest chats today:\n" + "\n".join(f"- {label(r)}: {r['c']}" for r in rows)

    if "contact" in q and re.search(r"how many|count|new|who|which|list|names?|show", q):
        since, name = (week, "this week") if "week" in q else (today, "today")
        if re.search(r"\b(who|which|what are|list|names?|show)\b", q):
            rows = query(
                "select jid, name, first_seen from wa_contacts where first_seen >= %s "
                "order by first_seen desc limit 20",
                (since,),
            )
            if not rows:
                return f"No new contacts {name}."
            lines = []
            for r in rows:
                number = r["jid"].split("@")[0]
                shown = f"+{number}" if r["jid"].endswith("@s.whatsapp.net") else number
                who = f"{r['name']} ({shown})" if r.get("name") else shown
                lines.append(f"- {who}, {r['first_seen'].astimezone(TZ):%a %H:%M}")
            return f"{plural(len(rows), 'new contact')} {name}:\n" + "\n".join(lines)
        n = query("select count(*) c from wa_contacts where first_seen >= %s", (since,), one=True)["c"]
        return f"{plural(n, 'new contact')} {name}."

    if re.search(r"per day|each day|day by day|last 7 days|last seven days|daily (messages|total)", q):
        rows = query(
            "select (sent_at at time zone %s)::date d, count(*) c from wa_messages "
            "where direction='in' and sent_at >= %s group by 1",
            (TZNAME, week),
        )
        counts = {r["d"]: r["c"] for r in rows}
        out = []
        for i in range(6, -1, -1):
            day = (datetime.now(TZ) - timedelta(days=i)).date()
            out.append(f"{day:%a %d %b}: {counts.get(day, 0)}")
        return "Messages received per day:\n" + "\n".join(out)

    if re.search(r"((last|recent|latest)\s+(\d+\s+)?messages?)|((what are|show|read|list)\s+(me\s+)?(the\s+|my\s+)?(new\s+|latest\s+|recent\s+)?messages)", q) \
            and "how many" not in q:
        rows = query(
            "select m.jid, m.direction, m.body, m.sent_at, c.name "
            "from wa_messages m left join wa_contacts c using (jid) "
            "order by m.sent_at desc limit 10"
        )
        if not rows:
            return "No messages saved yet."
        lines = []
        for r in rows:
            who = "You" if r["direction"] == "out" else label(r)
            text = (r["body"] or "[no text]")[:40]
            lines.append(f"- {who}, {r['sent_at'].astimezone(TZ):%a %H:%M}: {text}")
        return "Last 10 messages:\n" + "\n".join(lines)

    if "message" in q and re.search(r"how many|count|total|number of", q):
        since, name = (week, "in the last 7 days") if "week" in q else (today, "today")
        n = query(
            "select count(*) c from wa_messages where direction='in' and sent_at >= %s", (since,), one=True
        )["c"]
        return f"You received {plural(n, 'message')} {name}."

    # Anything else: have a normal conversation
    return ai_reply(raw or q, history)
