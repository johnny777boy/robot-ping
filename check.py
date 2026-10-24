#!/usr/bin/env python3
"""robot-ping: is the CI robot server alive? Runs on a GitHub-hosted runner. Standard library only, no secrets in files.

The robot (its watchdog, every 5 minutes) writes ONE value into this repository's Actions variable ROBOT_LAST_SEEN:
the UTC time, like 2026-10-16T12:00:00Z. Nothing else. This script gets that value from the workflow (env LAST_SEEN),
compares it with now, and sends ONE Telegram message when the robot looks dead and ONE when it is back.

  status "up" / "down" is kept in state.json on the branch `state` (the workflow commits it). The script never prints
  a token or a chat id: it prints only the age and the decision. A Telegram failure leaves the state as it was, so the
  next run (30 minutes later) tries again, and the run turns red (GitHub e-mails the owner).

  python3 check.py --state state.json [--dry-run] [--send-test]
  env: LAST_SEEN, TG_TOKEN, TG_CHAT_ID   (TG_* come from Actions secrets)
"""
import argparse, datetime as dt, json, os, sys, urllib.error, urllib.parse, urllib.request

STALE_MIN = 45        # older than this = the robot looks dead (the robot writes every 5 minutes; this run is every 30)
FUTURE_MIN = 10       # a time further ahead than this is not believed (same as no signal)
TOUCH_DAYS = 6        # rewrite state.json at least this often: keeps the repo "active" (GitHub pauses idle schedules at 60 days)
FMT = "%Y-%m-%dT%H:%M:%SZ"


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime(FMT)


def parse(s):
    """'2026-10-16T12:00:00Z' -> aware datetime, or None for anything else (empty, junk, other formats)."""
    if not isinstance(s, str):
        return None
    try:
        return dt.datetime.strptime(s.strip(), FMT).replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def _minutes(a, b):
    return int((a - b).total_seconds() // 60)


def decide(last_seen, now, state):
    """-> (action, new_state, text). action: 'down' | 'back' | 'none'. state: {'status','since','touched'} or {}.
    A new_state equal to state means nothing needs saving (the caller adds the weekly touch)."""
    status = state.get("status") if state.get("status") in ("up", "down") else None
    seen = parse(last_seen)
    if seen is not None and _minutes(seen, now) > FUTURE_MIN:
        seen = None                                    # a time from the future is not a signal
    age = _minutes(now, seen) if seen is not None else None
    alive = age is not None and age <= STALE_MIN
    st = dict(state)
    if alive:
        if status == "down":
            was = parse(state.get("since"))
            mins = f" (it was silent for about {_minutes(now, was)} minutes)" if was else ""
            st.update(status="up", since=iso(now))
            return "back", st, f"ROBOT BACK: the CI robot server is checking in again{mins}. Last check-in {iso(seen)}."
        if status is None:
            st.update(status="up", since=iso(now))
        return "none", st, ""
    # no good signal
    if status is None and seen is None:
        return "none", st, ""                          # never heard from it yet (not switched on): nothing to alarm about
    if status == "down":
        return "none", st, ""                          # already told once
    st.update(status="down", since=iso(now))
    if seen is None:
        words = "has no check-in time on record any more"
    else:
        words = f"has not checked in for {age} minutes (last check-in {iso(seen)})"
    return "down", st, (f"ROBOT DOWN: the CI robot server {words}. "
                        "It may be off, rebooted without starting, or cut off from the internet. Check OVH and ssh.")


def send_telegram(token, chat_id, text, opener=urllib.request.urlopen):
    """True when Telegram says ok. Never prints or raises with the token (the URL has it, so errors are reduced to a class name)."""
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text[:3500]}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data, method="POST")
    try:
        with opener(req, timeout=20) as r:
            return bool(json.load(r).get("ok"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"telegram: send failed ({type(e).__name__})")
        return False


def read_state(path):
    try:
        with open(path) as f:
            v = json.load(f)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def run(env, state_path, now, send=send_telegram, dry_run=False, send_test=False, out=print):
    """-> exit code. 0 = fine (a message that went out counts), 1 = a message could not be sent."""
    token, chat = env.get("TG_TOKEN", ""), env.get("TG_CHAT_ID", "")
    if send_test:
        if not token or not chat:
            out("send-test: the Actions secrets TG_TOKEN and TG_CHAT_ID are not both set")
            return 1
        ok = send(token, chat, "robot-ping test message: Telegram works from GitHub. Nothing is wrong.")
        out(f"send-test: {'sent' if ok else 'FAILED'}")
        return 0 if ok else 1
    state = read_state(state_path)
    action, new, text = decide(env.get("LAST_SEEN", ""), now, state)
    seen = parse(env.get("LAST_SEEN", ""))
    out(f"robot-ping: last_seen={'none' if seen is None else iso(seen)} status={state.get('status') or 'unknown'} "
        f"action={action}")
    if dry_run:
        if text:
            out("dry run, would send: " + text)
        return 0
    if action != "none":
        if not token or not chat or not send(token, chat, text):
            out("robot-ping: the message was NOT delivered; state unchanged, retry next run")
            return 1
    touched = parse(state.get("touched"))
    if new != state or touched is None or (now - touched).days >= TOUCH_DAYS:
        new["touched"] = iso(now)
        with open(state_path, "w") as f:
            json.dump(new, f, indent=1, sort_keys=True)
            f.write("\n")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--send-test", action="store_true")
    a = ap.parse_args(argv)
    return run(os.environ, a.state, utcnow(), dry_run=a.dry_run, send_test=a.send_test)


if __name__ == "__main__":
    sys.exit(main())
