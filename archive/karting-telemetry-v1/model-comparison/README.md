# model-comparison

Claude and Gemini, given the same karting session and asked to build a telemetry
dashboard. Three iterations on the Claude side; Gemini's contribution was the session
trimming approach.

Only the **build scripts and templates** are here. The rendered `dashboard.html` files
each embedded ~5 MB of session data and were dropped — run `build_dashboard.py` against
a local recording (see [`../../docs/DATA.md`](../../docs/DATA.md)) to regenerate them.

`claude/v3/` is the most developed: separate session-finding and statistics passes, a
spectrogram generator for the engine audio, and an upload-trimming step written to fit
the data inside a chat context window — which is itself a reminder of the constraint
this whole comparison ran under.
