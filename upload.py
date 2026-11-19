#!/usr/bin/env python3
"""Bulk upload a folder of images as Slack custom emoji.

Run with no arguments for a guided, step-by-step setup:

    python upload.py

Or pass files / folders directly (folders are searched recursively):

    python upload.py ~/Downloads/emoji/

https://github.com/smashwilson/slack-emojinator
"""

import argparse
import io
import json
import os
import re
import shlex
import sys
import urllib.parse
from time import sleep

try:
    import requests
except ImportError:
    sys.exit("Missing a required package. Run:  pip install requests pillow")

try:
    from PIL import Image, ImageSequence
except ImportError:  # Optional: only needed to shrink images Slack rejects as too large.
    Image = None

URL_CUSTOMIZE = "https://{team_name}.slack.com/customize/emoji"
URL_ADD = "https://{team_name}.slack.com/api/emoji.add"
URL_LIST = "https://{team_name}.slack.com/api/emoji.adminList"

# Slack serves a "browser not supported" 403 to non-browser user agents.
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36")

API_TOKEN_PATTERN = re.compile(r'"?api_token"?\s*:\s*"(xox[^"]+)"')

IMAGE_EXTENSIONS = {".png", ".gif", ".jpg", ".jpeg", ".webp"}
TOO_BIG_ERRORS = ("error_too_big", "resized_but_still_too_large")
NAME_TAKEN_ERRORS = ("error_name_taken", "error_name_taken_i18n")
MAX_SUFFIX = 9
GENERIC_SLACK_HOSTS = {"app", "www", "api", "slack", "files", "edgeapi"}
SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".slack-emojinator.json")

FRIENDLY_ERRORS = {
    "error_bad_format": "Slack couldn't read this image (unsupported or corrupt file).",
    "error_bad_name_i18n": "Slack rejected the emoji name.",
    "not_allowed": "Your account isn't allowed to add emoji in this workspace.",
    "no_permission": "Your account isn't allowed to add emoji in this workspace.",
}

COOKIE_HELP = """
  How to get your Slack cookie (about a minute, in Chrome):

    1. In Chrome, open  https://{team}.slack.com  and make sure you're signed in.
    2. Open Developer Tools:   Mac: Cmd + Option + I    Windows: Ctrl + Shift + I
    3. Click the "Application" tab at the top of that panel
       (it may be hidden behind ">>").
    4. In the left sidebar, expand  Cookies  and click  https://app.slack.com
    5. Find the row whose Name is just the letter  d
    6. Double-click its Value (it starts with "xoxd-"), copy it, and paste it below.

  Treat this like a password: it lets anyone act as you in Slack.
  This tool only sends it to Slack and never saves it.
"""


class FatalError(Exception):
    """An error that should stop the run with a plain-English message."""


# --------------------------------------------------------------------------- #
# Input helpers
# --------------------------------------------------------------------------- #

def ask(prompt, default=None):
    hint = " [{}]".format(default) if default else ""
    try:
        value = input("{}{}: ".format(prompt, hint)).strip()
    except EOFError:
        value = ""
    return value or (default or "")


def ask_yes_no(prompt, default=True):
    answer = ask("{} ({})".format(prompt, "Y/n" if default else "y/N")).lower()
    return default if not answer else answer.startswith("y")


def parse_team_name(value):
    """Accept 'acme', 'acme.slack.com', or any https://acme.slack.com/... URL."""
    value = value.strip().lower()
    match = re.search(r"([a-z0-9-]+)\.slack\.com", value)
    name = match.group(1) if match else re.sub(r"[^a-z0-9-]", "", value)
    if name in GENERIC_SLACK_HOSTS:
        print("  That's Slack's general web address, not your workspace's. In Slack, click\n"
              "  your workspace name (top left); its address looks like  acme.slack.com")
        return ""
    return name


def normalize_cookie(value):
    """Accept just the d cookie value, 'd=...', or a full Cookie header."""
    value = value.strip().strip("\"'")
    if value.lower().startswith("cookie:"):
        value = value[7:].strip()
    if value.startswith("d="):
        value = value[2:]
    elif ";" in value:
        return value  # A full Cookie header.
    # Bare d value. Slack needs it URL-encoded; re-encode in case it was copied decoded.
    return "d=" + urllib.parse.quote(urllib.parse.unquote(value), safe="")


def parse_dropped_paths(value):
    """Turn paths dragged into a terminal (quoted or backslash-escaped) into real paths."""
    try:
        parts = shlex.split(value)
    except ValueError:
        parts = [value.strip("'\"")]
    return [os.path.abspath(os.path.expanduser(p)) for p in parts]


def load_settings():
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Slack
# --------------------------------------------------------------------------- #

def make_session(team_name, cookie):
    session = requests.session()
    session.headers.update({
        "Cookie": cookie,
        "User-Agent": os.getenv("SLACK_USER_AGENT", USER_AGENT),
    })
    session.url_customize = URL_CUSTOMIZE.format(team_name=team_name)
    session.url_add = URL_ADD.format(team_name=team_name)
    session.url_list = URL_LIST.format(team_name=team_name)
    session.api_token = fetch_api_token(session, team_name)
    return session


def fetch_api_token(session, team_name):
    try:
        r = session.get(session.url_customize, allow_redirects=False, timeout=30)
    except requests.RequestException as e:
        raise FatalError("Couldn't reach {}.slack.com. Check the workspace name and your "
                         "internet connection.\n  ({})".format(team_name, type(e).__name__))
    if r.is_redirect:
        location = r.headers.get("location", "")
        if "{}.slack.com".format(team_name) not in location and "redir=" not in location:
            raise FatalError("'{}.slack.com' doesn't look like a Slack workspace. "
                             "Double-check the name.".format(team_name))
        raise FatalError("Slack didn't accept your cookie (it may be wrong or expired). "
                         "Grab a fresh 'd' cookie and try again.")
    if r.status_code == 404:
        raise FatalError("'{}.slack.com' doesn't look like a Slack workspace.".format(team_name))
    if r.status_code != 200:
        raise FatalError("Slack returned an unexpected error ({}) when signing in."
                         .format(r.status_code))
    match = API_TOKEN_PATTERN.search(r.text)
    if not match:
        raise FatalError("Signed in, but couldn't find the upload token on Slack's emoji page. "
                         "Make sure your account can add custom emoji in this workspace.")
    return match.group(1)


def slack_post(session, url, data, path=None, image_bytes=None):
    """POST with automatic waiting on rate limits and network hiccups. Returns JSON."""
    while True:
        try:
            if image_bytes is not None:
                resp = session.post(url, data=data, timeout=60, allow_redirects=False,
                                    files={"image": (os.path.basename(path), image_bytes)})
            elif path:
                with open(path, "rb") as f:
                    resp = session.post(url, data=data, files={"image": f}, timeout=60,
                                        allow_redirects=False)
            else:
                resp = session.post(url, data=data, timeout=60, allow_redirects=False)
        except requests.RequestException as e:
            print("    Network hiccup ({}), retrying in 10 seconds...".format(
                type(e).__name__), flush=True)
            sleep(10)
            continue
        if resp.status_code == 429:
            wait = int(resp.headers.get("retry-after", 5))
            print("    Slack asked us to slow down, waiting {} seconds...".format(wait),
                  flush=True)
            sleep(wait)
            continue
        if resp.is_redirect or resp.status_code in (401, 403):
            raise FatalError("Slack stopped accepting your cookie (it may have expired). "
                             "Grab a fresh one and run again; emoji that already uploaded "
                             "will be skipped.")
        resp.raise_for_status()
        return resp.json()


def get_current_emoji_list(session):
    page, names = 1, set()
    while True:
        data = {"query": "", "page": page, "count": 1000, "token": session.api_token}
        resp = slack_post(session, session.url_list, data)
        if not resp.get("ok"):
            raise FatalError("Couldn't list existing emoji: {}".format(resp.get("error")))
        names.update(e["name"] for e in resp["emoji"])
        if page >= resp["paging"]["pages"]:
            return names
        page += 1


def upload_emoji(session, emoji_name, path, image_bytes=None):
    data = {"mode": "data", "name": emoji_name, "token": session.api_token}
    return slack_post(session, session.url_add, data, path=path, image_bytes=image_bytes)


# --------------------------------------------------------------------------- #
# Images
# --------------------------------------------------------------------------- #

def emoji_name_for(path, prefix="", suffix=""):
    """Slack emoji names allow only lowercase letters, digits, '_' and '-'."""
    raw = prefix + os.path.splitext(os.path.basename(path))[0] + suffix
    raw = raw.replace("+", "_plus")
    name = re.sub(r"[^a-z0-9_-]+", "_", raw.lower()).strip("_-")
    return re.sub(r"_+", "_", name) or "emoji"


def find_images(paths):
    """Expand files and folders (recursively) into a sorted list of image files."""
    found = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                for name in sorted(files):
                    if os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS:
                        found.append(os.path.join(root, name))
        elif os.path.isfile(p):
            if os.path.splitext(p)[1].lower() in IMAGE_EXTENSIONS:
                found.append(p)
            else:
                print("  Ignoring {} (not an image type Slack accepts)".format(p))
        else:
            print("  Can't find {}".format(p))
    return found


def shrink_image(path):
    """Yield progressively smaller versions of an image, as bytes."""
    if Image is None:
        return
    try:
        im = Image.open(path)
    except Exception:
        return
    if getattr(im, "n_frames", 1) <= 1:
        for size in (128, 96, 64):
            frame = im.convert("RGBA")
            frame.thumbnail((size, size))
            buf = io.BytesIO()
            frame.save(buf, format="PNG", optimize=True)
            yield buf.getvalue()
        return

    # Animated: shrink dimensions and drop frames (stretching durations to keep the speed).
    frames, durations = [], []
    for f in ImageSequence.Iterator(im):
        frames.append(f.convert("RGBA"))
        durations.append(f.info.get("duration") or 50)
    for size, step in ((128, 1), (128, 2), (96, 2), (64, 3), (64, 4)):
        kept = [fr.copy() for fr in frames[::step]]
        for fr in kept:
            fr.thumbnail((size, size))
        durs = [sum(durations[i:i + step]) for i in range(0, len(durations), step)]
        buf = io.BytesIO()
        kept[0].save(buf, format="GIF", save_all=True, append_images=kept[1:],
                     duration=durs, loop=0, disposal=2, optimize=True)
        yield buf.getvalue()


# --------------------------------------------------------------------------- #
# Main flow
# --------------------------------------------------------------------------- #

def upload_one(session, path, base_name, existing, used_this_run):
    """Upload one image. Returns (status, emoji_name_or_reason, note)."""
    if base_name in existing:
        return "skipped", base_name, ""

    candidates = [base_name] + ["{}_{}".format(base_name, i) for i in range(2, MAX_SUFFIX + 1)]
    for name in candidates:
        if name in used_this_run:
            continue  # Another file in this batch already took this name.
        if name in existing:
            return "skipped", name, ""  # Uploaded on a previous run under a numbered name.
        resp = upload_emoji(session, name, path)
        if resp.get("ok"):
            return "uploaded", name, ""
        error = resp.get("error", "unknown error")
        if error in NAME_TAKEN_ERRORS:
            used_this_run.add(name)
            continue  # Clashes with a built-in emoji; try name_2, name_3, ...
        if error in TOO_BIG_ERRORS:
            if Image is None:
                return "failed", "Too large. Install Pillow (pip install pillow) to auto-shrink.", ""
            for smaller in shrink_image(path):
                resp = upload_emoji(session, name, path, image_bytes=smaller)
                if resp.get("ok"):
                    return "uploaded", name, " (shrunk to fit)"
                if resp.get("error") not in TOO_BIG_ERRORS:
                    break
            return "failed", "Too large, even after shrinking.", ""
        if error in ("not_allowed", "no_permission", "invalid_auth", "not_authed"):
            raise FatalError(FRIENDLY_ERRORS.get(
                error, "Slack rejected your login ({}).".format(error)))
        return "failed", FRIENDLY_ERRORS.get(error, "Slack said: {}".format(error)), ""
    return "failed", "Names :{0}: through :{0}_{1}: are all taken.".format(
        base_name, MAX_SUFFIX), ""


def guided_setup(args):
    print("\n=== Slack Emoji Uploader ===\n")
    settings = load_settings()

    if not args.team_name:
        print("Step 1 of 3: Which Slack workspace?")
        print("  Paste your workspace URL (like https://acme.slack.com) or just its name.")
        while not args.team_name:
            args.team_name = parse_team_name(ask("  Workspace", settings.get("team_name")))
        settings["team_name"] = args.team_name
        save_settings(settings)
        print()

    if not args.cookie:
        print("Step 2 of 3: Sign in with your Slack cookie.")
        print(COOKIE_HELP.format(team=args.team_name))
        while not args.cookie:
            args.cookie = ask("  Paste the 'd' cookie value here")
        print()

    if not args.paths:
        print("Step 3 of 3: Which emoji?")
        print("  Drag your emoji folder (or image files) into this window, then press Enter.")
        print("  Subfolders are included. Each file's name becomes its emoji name.")
        while not args.paths:
            value = ask("  Folder")
            if value:
                args.paths = parse_dropped_paths(value)
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Bulk upload images as Slack emoji. Run with no arguments for guided setup.")
    parser.add_argument("--team-name", "-t", default=os.getenv("SLACK_TEAM"),
                        help="Workspace name or URL. Defaults to $SLACK_TEAM.")
    parser.add_argument("--cookie", "-c", default=os.getenv("SLACK_COOKIE"),
                        help="Your Slack 'd' cookie value (or a full Cookie header). "
                             "Defaults to $SLACK_COOKIE.")
    parser.add_argument("--prefix", "-p", default=os.getenv("EMOJI_NAME_PREFIX", ""),
                        help="Text added before every emoji name.")
    parser.add_argument("--suffix", "-s", default=os.getenv("EMOJI_NAME_SUFFIX", ""),
                        help="Text added after every emoji name.")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Don't ask for confirmation before uploading.")
    parser.add_argument("paths", nargs="*", help="Image files and/or folders to upload.")
    args = parser.parse_args()
    args.paths = [os.path.abspath(os.path.expanduser(p)) for p in args.paths]

    interactive = sys.stdin.isatty()
    if interactive and not (args.team_name and args.cookie and args.paths):
        guided_setup(args)
    if not (args.team_name and args.cookie and args.paths):
        raise FatalError("Need a workspace, a cookie, and at least one file or folder. "
                         "Run with no arguments for guided setup.")

    team_name = parse_team_name(args.team_name)
    if not team_name:
        raise FatalError("Need your workspace name (the 'acme' in acme.slack.com).")
    images = find_images(args.paths)
    if not images:
        raise FatalError("No images found. Slack accepts .png, .gif, .jpg, and .webp files.")

    print("Signing in to {}.slack.com...".format(team_name), flush=True)
    session = make_session(team_name, normalize_cookie(args.cookie))
    existing = get_current_emoji_list(session)
    print("Signed in. The workspace has {} custom emoji.\n".format(len(existing)))

    print("Found {} image(s) to upload.".format(len(images)))
    if interactive and not args.yes:
        if not ask_yes_no("Upload them to {}.slack.com now?".format(team_name)):
            print("Cancelled. Nothing was uploaded.")
            return
    print("\nUploading. Slack limits how fast this can go, so big batches take a while.\n"
          "It's safe to stop (Ctrl+C) and run again later: finished emoji are skipped.\n")

    root = args.paths[0] if len(args.paths) == 1 and os.path.isdir(args.paths[0]) else None
    uploaded, skipped, failed, renamed = [], [], [], []
    used_this_run = set()
    width = len(str(len(images)))
    for i, path in enumerate(images, 1):
        display = os.path.relpath(path, root) if root else os.path.basename(path)
        base = emoji_name_for(path, args.prefix.strip(), args.suffix.strip())
        status, detail, note = upload_one(session, path, base, existing, used_this_run)
        label = "[{:>{w}}/{}]".format(i, len(images), w=width)
        if status == "uploaded":
            existing.add(detail)
            used_this_run.add(detail)
            uploaded.append(detail)
            if detail != base:
                renamed.append((display, base, detail))
            print("{} added   :{}:{}".format(label, detail, note), flush=True)
        elif status == "skipped":
            used_this_run.add(detail)
            skipped.append(detail)
            print("{} skipped :{}: (already exists)".format(label, detail), flush=True)
        else:
            failed.append((display, detail))
            print("{} FAILED  {}: {}".format(label, display, detail), flush=True)

    print("\n=== Done ===")
    print("  Added:          {}".format(len(uploaded)))
    print("  Already there:  {}".format(len(skipped)))
    print("  Failed:         {}".format(len(failed)))
    if renamed:
        print("\nThese names were already taken (by a built-in Slack emoji or another file "
              "in this batch),\nso a number was added:")
        for display, wanted, got in renamed:
            print("  {}  ->  :{}:  (wanted :{}:)".format(display, got, wanted))
    if failed:
        print("\nThese didn't upload:")
        for display, reason in failed:
            print("  {}: {}".format(display, reason))


if __name__ == "__main__":
    try:
        main()
    except FatalError as e:
        print("\nProblem: {}".format(e))
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nStopped. Run again any time; emoji that already uploaded will be skipped.")
        sys.exit(130)
