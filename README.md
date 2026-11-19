# Slack Emojinator

*Bulk upload emoji into Slack*

Want to create a custom Slack emoji for every pokemon? Slack doesn't currently expose an API endpoint for creating emoji, probably to prevent users from doing exactly what I'm doing, but here's a way to do it anyway.

## Quick start (no coding needed)

1. Download this project: click the green **Code** button on GitHub, choose **Download ZIP**, and unzip it.
2. Put all your emoji images in one folder (subfolders are fine). Each file's name becomes the emoji's name, so `party-cat.gif` becomes `:party-cat:`.
3. Double-click **Upload Emoji.command** (Mac) or **Upload Emoji (Windows).bat** (Windows).
   * On a Mac, if it says the file "can't be opened," right-click it, choose **Open**, then **Open** again.
   * If Python isn't installed, the tool opens the download page for you. Install it and double-click again.
4. Answer the three questions it asks:
   * **Workspace:** paste your Slack address, like `https://acme.slack.com`.
   * **Cookie:** the tool shows step-by-step instructions for copying your Slack sign-in cookie from Chrome. Treat it like a password.
   * **Folder:** drag your emoji folder into the window and press Enter.

Big batches take a while because Slack limits upload speed. You can close the window at any time and run it again later: emoji that already uploaded are skipped.

The tool handles the fiddly parts for you:

* Names with spaces, capitals, or symbols are cleaned up (`Heart Hands.gif` becomes `:heart_hands:`).
* If a name is taken by one of Slack's built-in emoji (like `:badger:`) or by another file in your folder, it adds a number (`:badger_2:`).
* Images Slack says are too large are shrunk automatically.
* At the end you get a summary of what was added, renamed, or failed, and why.

You need permission to add custom emoji in the workspace.

## Creating Emoji (command line)

You'll need Python 3 and `pip` to get started.

Prepare a directory that contains an image for each emoji you want to create. Remember to respect Slack's specifications for valid emoji images: no greater than 128px in width or height, no greater than 64K in image size. The base filename of each image file should be the name of the emoji (the bit you'll type inside `:` to display it).

Clone the project and install its prereqs:

`libxml` is required on your system, if you'd like to use the bulk export script.

```bash
git clone https://github.com/smashwilson/slack-emojinator.git
cd slack-emojinator
pipenv install
```

You'll need to provide your team name (the bit before ".slack.com" in your admin URL) and your session cookie (grab it from your browser). Copy `.env.example`, fill them in, and source it.

To grab your Slack session cookie:

* [Open your browser's dev tools](http://webmasters.stackexchange.com/a/77337) and copy the value of `document.cookie`.
* Go to the Network tab.
* Re-load your workspace's `https://{teamname}.slack.com/customize/emoji` page.
* Find the call to `emoji` (it is most likely the very top request).
* Scroll to `Request-Headers`, copy the value of "Cookie," and add to your `.env` file.

```bash
cp .env.example .env
${EDITOR} .env
source .env
```

Only the `d` cookie is actually required: `SLACK_COOKIE` can be either the full Cookie header or just the `d` value (starting with `xoxd-`).

Now you're ready to go. Pass folders (searched recursively) and/or individual image files:

```bash
pip install requests pillow
python upload.py ${EMOJI_DIR}
```

Run `python upload.py` with no arguments for the guided setup, or `--help` for all options (`--prefix`, `--suffix`, `--yes`).

:sparkles:

## Exporting Emoji

To export emoji, use `export.py` and specify an emoji directory:

```bash
source .env
pipenv run python export.py path-to-destination/
```
