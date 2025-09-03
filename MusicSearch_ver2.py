#!/usr/bin/env python3
"""
genius_lyrics_search_and_download.py

Flow:
1) Prompt for a lyrics snippet
2) Use lyricsgenius.Genius.search_lyrics() to find matches
3) Present candidates (title — artist)
4) On selection, fetch full lyrics with genius.lyrics(song_url=...)
5) Ask whether to download audio; if yes, use yt-dlp to download the top YouTube match

Notes:
- Set GENIUS_CLIENT_ACCESS_TOKEN env var or paste token when prompted.
- Install dependencies: pip install lyricsgenius requests
- Install yt-dlp if you intend to download.
"""

import os
import sys
import subprocess
import shutil
from typing import List, Dict

try:
    import lyricsgenius
except Exception as e:
    print("Missing dependency 'lyricsgenius'. Install with: pip install lyricsgenius")
    raise SystemExit(1)

def get_genius_client() -> lyricsgenius.Genius:
    token = os.environ.get("GENIUS_CLIENT_ACCESS_TOKEN") or os.environ.get("GENIUS_ACCESS_TOKEN")
    if not token:
        # ask once, not repeatedly
        token = input("Enter your Genius client access token (or set GENIUS_CLIENT_ACCESS_TOKEN env var): ").strip()
        if not token:
            print("No token provided. Exiting.")
            sys.exit(1)
    g = lyricsgenius.Genius(token, timeout=15, retries=3, sleep_time=0.5)
    # recommended small adjustments to avoid extra verbose scraping
    g.skip_non_songs = True
    g.excluded_terms = ["(Remix)", "(Live)"]
    return g

def search_by_lyrics(genius_client: lyricsgenius.Genius, snippet: str, max_results: int = 8) -> List[Dict]:
    """
    Use Genius.search_lyrics() to find hits. Returns list of dicts:
    {'title':..., 'artist':..., 'url':...}
    """
    try:
        resp = genius_client.search_lyrics(snippet)
    except Exception as e:
        # API may throw (403) or other network errors. Bubble up a clear error.
        raise RuntimeError(f"Genius search_lyrics failed: {e}")

    results = []
    sections = resp.get("sections") or []
    # sections can have multiple types; the examples show lyric hits in sections[0]
    for sec in sections:
        hits = sec.get("hits") or []
        for h in hits:
            r = h.get("result") or {}
            title = r.get("title")
            prim = r.get("primary_artist") or {}
            artist = prim.get("name")
            url = r.get("url")  # full Genius URL
            if title and artist and url:
                entry = {"title": title.strip(), "artist": artist.strip(), "url": url.strip()}
                if entry not in results:
                    results.append(entry)
            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break
    return results

def present_choices(results: List[Dict]):
    print("\nMatches:")
    for i, r in enumerate(results, start=1):
        print(f"{i}. {r['title']} — {r['artist']}")
    print("0. Cancel / exit")

def fetch_lyrics_for_result(genius_client: lyricsgenius.Genius, chosen: Dict) -> str:
    # lyricsgenius can fetch lyrics by song URL
    try:
        lyrics = genius_client.lyrics(song_url=chosen["url"])
    except Exception as e:
        raise RuntimeError(f"Failed to fetch lyrics: {e}")
    return lyrics

def ensure_yt_dlp_installed() -> bool:
    return shutil.which("yt-dlp") is not None

def download_audio_with_ytdlp(title: str, artist: str, audio_format: str = "mp3"):
    query = f"{artist} {title} audio"
    target = f"ytsearch1:{query}"
    cmd = [
        "yt-dlp",
        target,
        "-x",
        "--audio-format", audio_format,
        "--audio-quality", "0",
        "-o", "%(title)s.%(ext)s"
    ]
    print("Running yt-dlp to download top YouTube result for:", query)
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"yt-dlp failed with exit code {e.returncode}")
    except FileNotFoundError:
        raise RuntimeError("yt-dlp not found on PATH. Install it first (e.g. pip install yt-dlp).")

def main():
    genius = get_genius_client()

    snippet = input("Paste a distinctive lyrics fragment (blank to exit):\n> ").strip()
    if not snippet:
        print("No snippet. Exiting.")
        return

    print("\nSearching Genius for matches (this queries the Genius search_lyrics endpoint)...")
    try:
        hits = search_by_lyrics(genius, snippet, max_results=10)
    except Exception as e:
        print("Search failed:", e)
        print("You can try a different fragment or check your token/network.")
        return

    if not hits:
        print("No matches found.")
        return

    present_choices(hits)

    # Choose
    while True:
        choice = input("\nChoose a number to view lyrics (or 0 to cancel): ").strip()
        if not choice.isdigit():
            print("Enter a number.")
            continue
        idx = int(choice)
        if idx == 0:
            print("Cancelled.")
            return
        if 1 <= idx <= len(hits):
            chosen = hits[idx - 1]
            break
        print("Out of range.")

    print(f"\n--- {chosen['title']} — {chosen['artist']} ---\n")
    try:
        lyrics = fetch_lyrics_for_result(genius, chosen)
    except Exception as e:
        print("Error fetching lyrics:", e)
        return

    if lyrics:
        print(lyrics)
    else:
        print("(No lyrics returned.)")
    print("\n--- end of lyrics ---\n")

    # Ask to download
    while True:
        y = input("Download audio from YouTube? [y/N]: ").strip().lower()
        if y in ("y", "yes"):
            if not ensure_yt_dlp_installed():
                print("yt-dlp is not installed or not on PATH. Install it and retry.")
                return
            fmt = input("Audio format (mp3/m4a/webm). Press Enter for 'mp3': ").strip().lower() or "mp3"
            if fmt not in ("mp3", "m4a", "webm", "aac", "wav", "flac"):
                print("Unknown/unsupported format, defaulting to mp3.")
                fmt = "mp3"
            try:
                download_audio_with_ytdlp(chosen["title"], chosen["artist"], audio_format=fmt)
            except Exception as e:
                print("Download failed:", e)
            return
        elif y in ("n", "no", ""):
            print("Not downloading. Exiting.")
            return
        else:
            print("Answer 'y' or 'n'.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting.")
        sys.exit(0)
