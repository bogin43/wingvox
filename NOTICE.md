<!-- notice-version: 1 -->
# A few things to know about Wingvox

Wingvox listens for the dictation hotkey the whole time it is running, and it
pastes text into whatever app has focus. That means two things worth saying
plainly before you use it.

**Everything stays on your Mac.** Your audio is transcribed locally and cleaned
up by a local model. No recording, no transcript, and no text is uploaded
anywhere. Wingvox has no account, no analytics, and no telemetry.

**It checks GitHub for updates when it starts.** That one request asks whether a
newer version has been published. It sends nothing about you and nothing about
what you dictate, and Wingvox never installs an update on its own. If one is
available it tells you, and you decide whether to take it.

**It pastes through your clipboard.** Wingvox briefly replaces your clipboard
contents to paste, then puts back what was there. If you copy something in that
split second, the restore is skipped rather than overwriting your newer copy.

Wingvox is free, MIT licensed, and provided as-is. The source is at
github.com/bogin43/wingvox if you want to read any of the above for yourself.
