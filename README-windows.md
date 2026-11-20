# ilias-cli on Windows

Step-by-step guide to install and use `ilias` on Windows 10/11.

## 1. Install Python

1. Download Python 3.10 or newer from https://www.python.org/downloads/windows/
2. Run the installer and **tick "Add python.exe to PATH"** on the first screen.
3. Open **Windows Terminal** or **PowerShell** and check:
   ```powershell
   python --version
   ```
   If this opens the Microsoft Store instead, disable the "App execution aliases" for
   `python.exe` under *Settings → Apps → Advanced app settings → App execution aliases*.

## 2. Install ilias-cli

`pipx` installs CLI tools into their own environment and puts them on your PATH:

```powershell
python -m pip install --user pipx
python -m pipx ensurepath
```

**Close and reopen the terminal**, then:

```powershell
pipx install git+https://github.com/user0384/ilias-cli.git
ilias --help
```

> The repository is private: you need to have been invited and be logged in to GitHub
> with git (e.g. via [Git for Windows](https://git-scm.com/download/win), which opens a
> browser login the first time). If git is missing, install it first.

**Update** later with `pipx upgrade ilias-cli`, **uninstall** with `pipx uninstall ilias-cli`.

## 3. Log in

HSLU uses SWITCH edu-ID with 2FA, so the CLI borrows the session from your browser:

1. Log in at https://elearning.hslu.ch/ilias in Edge / Chrome / Firefox.
2. Press **F12** → tab **Application** (Edge/Chrome) or **Storage** (Firefox)
   → **Cookies** → `https://elearning.hslu.ch`.
3. Copy the **Value** of `PHPSESSID`.
4. Run the following and paste the value (right-click or Ctrl+V; nothing is shown while you type):
   ```powershell
   ilias login
   ```

The session is stored in `C:\Users\<you>\.config\ilias-cli\cookies.json`. Treat it like a
password; anyone with it can act as you in ILIAS until it expires. When it expires
(after some hours of inactivity) you'll get a message telling you to run `ilias login` again.

## 4. Use it

Paths start at your "Meine Kurse und Gruppen" dashboard and use **forward slashes**.
You only need to type a unique part of each name. Put paths with spaces in quotes.

```powershell
ilias ls                                     # your courses and groups
ilias ls PLAB                                # contents of a course
ilias ls -l "PLAB/Unterlagen OOP/SW01"       # with size and date
ilias tree PLAB -d 2                         # overview

# download a single file into Downloads
ilias get "PLAB/Unterlagen OOP/SW01/A01" -o $HOME\Downloads

# download a whole folder
ilias get "PLAB/Unterlagen OOP" -o C:\hslu\plab

# mirror a course; run it again any time to fetch only new/changed files
ilias sync PLAB C:\hslu\plab
ilias sync PLAB C:\hslu\plab --dry-run       # just show what would be downloaded
```

Without `-o`, `get` saves into the folder your terminal is currently in (shown in the prompt).

## Troubleshooting

| Problem | Fix |
|---|---|
| `ilias` is not recognized | Run `python -m pipx ensurepath` and reopen the terminal. |
| `Session expired or invalid` | Copy a fresh `PHPSESSID` from the browser and run `ilias login`. |
| Errors about paths being too long | Sync into a short folder such as `C:\hslu`, or enable long paths: *Run as admin* → `New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -Value 1 -PropertyType DWORD -Force` |
| `✓` or progress shows as garbage | Use Windows Terminal instead of the old `cmd.exe` window. |
| `'xyz' is ambiguous` | Type more of the name, or use the ref id shown by `ilias ls -l`. |
