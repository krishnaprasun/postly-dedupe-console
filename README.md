# Postly Duplicate Review & Removal Console

Reviews the duplicate clusters found by the perceptual scan of the live library
(10,627 of 10,633 videos fingerprinted) and turns confirmed ones into a removal
manifest. **Nothing is removed by browsing.** Removal is a separate, gated step
that acts only on clusters a human confirmed.

## Run

    cd ~/postly-dedupe-console
    python3 app.py            # http://127.0.0.1:8077
    # login: postly / dedupe2026   (override with DEDUPE_USER / DEDUPE_PASS)

## What's in it

- **Queue** — 601 clusters, filterable by status and by class:
  - *Invisible to link-match* (239) — identical content, different source files.
    These are the ones the CMS sha256 check and any link comparison cannot see.
  - *Cross-vendor* (115) — the same clip billed to more than one vendor.
  - *Date-variant* (98) — flagged, see below.
- **Cluster view** — every copy side by side with three real frames, plus sheet row,
  vendor, engagement and a link to the original. Pick which copy survives.
- **Background reuse** — 1,931 videos over 803 backgrounds, view-only. Not duplication;
  distinct statuses sharing stock footage. Removing these would delete real content.
- **Removal** — manifest of every non-keeper in a confirmed cluster.

Keyboard: `1`–`9` pick keeper, `c` confirm, `r` not-duplicates, `s` skip.

## The date-variant warning

The detector compares frames, so it cannot read a small date stamp. Daily darshan art
for 7-7-2026 and 8-7-2026 is otherwise pixel-identical and scores as a duplicate.
98 clusters touching a date-stamped or darshan category are flagged and sorted last.
Look before confirming those.

## Removal modes

`DEDUPE_EXEC_MODE` (default `export`):

- `export` — writes `postly_removals.csv`. Safe; touches nothing external.
- `sheet` — **not wired up.** The mechanism for retiring content that is already live
  in the app has not been confirmed. Column J only ever holds `Live On App` or
  `Rejected-Other Reason`, and every rejected row has an empty Postly path, so no
  existing status means "was live, now retired". That needs answering before any
  write-back is built.

## Rebuilding the data

    python3 build_data.py [path-to-scratchpad]

Reads `postly_duplicate_content.csv` + `postly_background_reuse.csv` and copies the
frames for rows that appear in a cluster.
