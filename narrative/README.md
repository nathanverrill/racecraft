# narrative

Turning a race weekend into text, and text into commentary.

`scrape_racefans.py` and `extract_racefans.py` pull race reports; `youtube_scraper.py`
takes transcripts from race coverage; `combine_txt.py` merges the lot into a single
per-race corpus. `glossary.txt` is the domain vocabulary the generation step needs to
not sound like an outsider, and `themes-and-memes.txt` carries the fandom register —
which is most of what separates plausible F1 commentary from a summary.

`corpus/` holds three worked examples: Australia and China 2025, and Singapore
qualifying. The generated audio and the fuller scraped archive stay on disk
(see [`../docs/DATA.md`](../docs/DATA.md)).
