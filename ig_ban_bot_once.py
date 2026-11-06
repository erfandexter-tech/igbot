import os
import json
import time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

BOT_TOKEN = os.environ["8946001528:AAHSKDetQlviv0OvdqrZb-Xr7YR7V19ShVc"]
DB_FILE = "watch.json"
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

IG_URL = "https://www.instagram.com/api/v1/users/web_profile_info/"
IG_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "x-ig-app-id": "936619743392459",
}


# ---------- storage ----------
def load():
    try:
        with open(DB_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    data.setdefault("offset", None)
    data.setdefault("items", {})
    return data


def save(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


# ---------- telegram ----------
def send(chat_id, text):
    try:
        requests.post(f"{API}/sendMessage",
                      data={"chat_id": chat_id, "text": text}, timeout=20)
    except Exception as e:
        print("telegram error:", e)


# ---------- instagram ----------
def check(username):
    try:
        r = requests.get(IG_URL, params={"username": username},
                         headers=IG_HEADERS, timeout=20, allow_redirects=False)
    except Exception as e:
        print("network error:", e)
        return None, {}
    print(username, "->", r.status_code)
    if r.status_code == 200:
        try:
            user = r.json().get("data", {}).get("user")
        except ValueError:
            return None, {}
        if not user:
            return "banned", {}
        return "active", {
            "followers": user.get("edge_followed_by", {}).get("count"),
            "verified": bool(user.get("is_verified")),
        }
    if r.status_code == 404:
        return "banned", {}
    return None, {}


# ---------- formatting ----------
def fmt_duration(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h} hours, {m} minutes, {s} seconds"


def build_message(w, kind):
    banned = kind == "ban"
    now = datetime.now(ZoneInfo("America/New_York"))
    followers = w.get("followers")
    f_txt = f"{followers:,}" if isinstance(followers, int) else "Unknown"
    verified = "✅ Verified" if w.get("verified") else "⚪ Not verified"
    return (
        f"Account {'banned' if banned else 'unbanned'}\n"
        f"Instagram Account @{w['username']} | Status | "
        f"{'Banned ❌' if banned else 'Unbanned ✅'}\n\n"
        f"📊 Last known: {f_txt} followers\n\n"
        f"ℹ️ Account Info:\n{verified}\n\n"
        f"Time taken: {fmt_duration(time.time() - w['added_at'])}\n"
        f"{'Banned' if banned else 'Unbanned'} at {now.strftime('%H:%M %Z')}\n"
        f"👤 {'Banned' if banned else 'Unbanned'} by: {w['added_by']}"
    )


# ---------- commands ----------
def handle(update, db):
    items = db["items"]
    msg = update.get("message") or {}
    text = (msg.get("text") or "").strip()
    if not text.startswith("/"):
        return
    chat_id = msg["chat"]["id"]
    frm = msg.get("from", {})
    who = "@" + frm["username"] if frm.get("username") else frm.get("first_name", "unknown")

    parts = text.split()
    cmd = parts[0].split("@")[0].lower()
    arg = parts[1].lstrip("@").lower() if len(parts) > 1 else ""

    if cmd in ("/start", "/help"):
        send(chat_id, "Commands:\n/ban @username - notify me when it gets banned\n"
                      "/unban @username - notify me when it comes back\n"
                      "/list - show watched accounts\n/remove @username - stop watching\n\n"
                      "Replies can take a few minutes.")
        return

    if cmd == "/list":
        lines = [f"{'🔴' if w['mode'] == 'ban' else '🟢'} @{w['username']} ({w['mode']})"
                 for w in items.values() if w["chat_id"] == chat_id]
        send(chat_id, "\n".join(lines) or "Nothing is being watched.")
        return

    if not arg:
        send(chat_id, f"Usage: {cmd} @username")
        return

    if cmd == "/remove":
        for k in [k for k, w in items.items() if w["chat_id"] == chat_id and w["username"] == arg]:
            del items[k]
        send(chat_id, f"Removed @{arg}")
        return

    if cmd in ("/ban", "/unban"):
        mode = cmd[1:]
        status, info = check(arg)
        if mode == "ban" and status == "banned":
            send(chat_id, f"@{arg} is already banned / not found.")
            return
        if mode == "unban" and status == "active":
            send(chat_id, f"@{arg} is already active.")
            return
        items[f"{chat_id}:{mode}:{arg}"] = {
            "chat_id": chat_id, "username": arg, "mode": mode,
            "added_by": who, "added_at": time.time(),
            "followers": info.get("followers"), "verified": info.get("verified", False),
        }
        send(chat_id, f"✅ Added @{arg} to the {mode} list.")


# ---------- monitoring ----------
def run_checks(db):
    items = db["items"]
    for key, w in list(items.items()):
        status, info = check(w["username"])
        time.sleep(3)
        if status is None:
            continue
        if info:
            w["followers"] = info["followers"]
            w["verified"] = info["verified"]
        if w["mode"] == "ban" and status == "banned":
            send(w["chat_id"], build_message(w, "ban"))
            del items[key]
        elif w["mode"] == "unban" and status == "active":
            send(w["chat_id"], build_message(w, "unban"))
            del items[key]


def main():
    db = load()
    params = {"timeout": 0}
    if db["offset"] is not None:
        params["offset"] = db["offset"]
    r = requests.get(f"{API}/getUpdates", params=params, timeout=30).json()
    for u in r.get("result", []):
        db["offset"] = u["update_id"] + 1
        try:
            handle(u, db)
        except Exception as e:
            print("handle error:", e)
    run_checks(db)
    save(db)


if __name__ == "__main__":
    main()
