"""WhatsApp mode for Cipher: stats API for the UI + ingest API for the bot.

Env vars (set in Vercel):
  WA_OWNER_USERNAME  your Cipher username. Only this user can see WhatsApp data.
  WA_INGEST_KEY      long random secret. The bot sends it as the X-WA-Key header.
  WA_TIMEZONE        optional, default Africa/Lagos. Decides where "today" starts.
"""
import os
import re
import hmac
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
        "select id, body from wa_posts where status='pending' and scheduled_at <= now() "
        "order by scheduled_at limit 5"
    )
    return jsonify(posts=rows)


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
    q = ((request.get_json(silent=True) or {}).get("question") or "").lower()
    return jsonify(answer=answer(q))


# ---------- answers ----------
def answer(q):
    today, week = day_start(0), day_start(6)

    if re.search(r"unanswered|waiting|not replied|need.*repl|reply to", q):
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
        return f"{plural(len(waiting), 'chat')} waiting for your reply:\n" + "\n".join(lines)

    if re.search(r"auto|welcome|bot (send|sent)", q):
        n = query(
            "select count(*) c from wa_messages where auto_reply and sent_at >= %s", (today,), one=True
        )["c"]
        return f"The bot sent {n} auto-repl{'y' if n == 1 else 'ies'} today."

    if re.search(r"channel|post|schedul", q):
        rows = query(
            "select body, scheduled_at from wa_posts where status='pending' order by scheduled_at limit 10"
        )
        if not rows:
            return "No channel posts are scheduled."
        lines = [f"- {r['scheduled_at'].astimezone(TZ):%a %d %b, %H:%M}: {r['body'][:60]}" for r in rows]
        return f"{plural(len(rows), 'post')} scheduled:\n" + "\n".join(lines)

    if re.search(r"most|busiest|top", q):
        rows = query(
            "select m.jid, c.name, count(*) c from wa_messages m left join wa_contacts c using (jid) "
            "where m.direction='in' and m.sent_at >= %s group by m.jid, c.name order by c desc limit 5",
            (today,),
        )
        if not rows:
            return "No messages received yet today."
        return "Busiest chats today:\n" + "\n".join(f"- {label(r)}: {r['c']}" for r in rows)

    if "contact" in q:
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

    if re.search(r"per day|each day|daily|7 days|seven days", q):
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

    if re.search(r"(last|recent|latest)\s+(\d+\s+)?messages?", q) and "how many" not in q:
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

    if "message" in q:
        since, name = (week, "in the last 7 days") if "week" in q else (today, "today")
        n = query(
            "select count(*) c from wa_messages where direction='in' and sent_at >= %s", (since,), one=True
        )["c"]
        return f"You received {plural(n, 'message')} {name}."

    return (
        "I can answer questions like:\n"
        "- How many messages today?\n- Messages per day\n- New contacts today\n"
        "- Which chats are waiting for my reply?\n- Who messaged me the most?\n- Scheduled channel posts"
    )
