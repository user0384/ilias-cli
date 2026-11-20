# ilias-cli

Browse and download files from [HSLU ILIAS](https://elearning.hslu.ch/ilias/) on the command line.

## Install

```bash
cd ~/cli/ilias-cli
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
ln -s ~/cli/ilias-cli/.venv/bin/ilias ~/.local/bin/ilias   # put it on your PATH
```

## Login

HSLU uses SWITCH edu-ID (SSO + 2FA), so the CLI reuses your browser session:

1. Log in at https://elearning.hslu.ch/ilias in your browser.
2. DevTools (F12) → *Application* (Chrome) / *Storage* (Firefox) → Cookies → `elearning.hslu.ch`.
3. Copy the `PHPSESSID` value and run `ilias login` (input is hidden).

The cookie is stored in `~/.config/ilias-cli/cookies.json` (mode 600). Sessions expire after
some hours of inactivity; then just repeat the login. `ilias status` checks the session.

## Usage

Paths start at the "Meine Kurse und Gruppen" dashboard. Each segment matches
case-insensitively by exact title, unique prefix, unique substring, or ref id.

```bash
ilias ls                                   # your courses & groups
ilias ls PLAB.H2601                        # contents of a course
ilias ls -l "PLAB.H2601/Unterlagen OOP"    # with type, ref id, file info
ilias tree PLAB.H2601 -d 2
ilias get "PLAB.H2601/Unterlagen OOP/SW01" -o ~/Downloads     # a file
ilias get "PLAB.H2601/Unterlagen OOP"                         # a whole folder
ilias sync PLAB.H2601 ~/hslu/s1/plab/ilias                    # incremental mirror
ilias sync PLAB.H2601 ~/hslu/s1/plab/ilias --dry-run
ilias url "PLAB.H2601/Forum"               # print browser link
ilias ls PLAB.H2601 --json | jq '.[].title'
```

`sync` stores state in `DEST/.ilias-sync.json` and re-downloads a file when its
version/date info in ILIAS changes. It never deletes local files.

## Development

```bash
.venv/bin/pytest
```

Set `ILIAS_BASE_URL` to point at another ILIAS 9 instance.
