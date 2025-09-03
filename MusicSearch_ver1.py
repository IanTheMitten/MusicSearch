#!/usr/bin/env python3
"""
lyrics_search_and_download.py

Flow:
1) Ask for a lyrics snippet
2) Search Lyrics.com for matches
3) Fetch the top matches (title + artist) and present them
4) If user selects one, fetch and display the lyrics
5) Ask whether to download; if yes, use yt-dlp to download the best YouTube match
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin
import time
import subprocess
import shutil
import sys

BASE = "https://www.lyrics.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; lyrics-fetcher/1.0; +https://example.com/)"
}

def search_lyricscom(snippet, max_results=8):
    """Search Lyrics.com for the snippet and return list of song page URLs (unique)."""
    q = quote_plus(snippet)
    url = f"{BASE}/serp.php?st={q}&type=lyrics"
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Find links that look like /lyric/...
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/lyric/"):
            full = urljoin(BASE, href)
            if full not in links:
                links.append(full)
        if len(links) >= max_results:
            break
    return links[:max_results]

def parse_song_page(song_url):
    """Given a Lyrics.com song page URL, return dict with title, artist, lyrics (or None)."""
    r = requests.get(song_url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # title heuristics
    title = None
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(strip=True)

    # artist heuristics: look for link to artist page or h3
    artist = None
    # common pattern: <h3>Artist Name</h3> or a link to /artist/...
    h3 = soup.find("h3")
    if h3 and h3.get_text(strip=True):
        artist = h3.get_text(strip=True)
    if not artist:
        a_artist = soup.find("a", href=lambda x: x and x.startswith("/artist/"))
        if a_artist:
            artist = a_artist.get_text(strip=True)

    # lyrics heuristics:
    # Lyrics.com often uses <pre id="lyric-body-text"> or <pre class="lyric-body"> or div with large text
    lyrics = None
    pre = soup.find("pre", id="lyric-body-text")
    if pre:
        lyrics = pre.get_text("\n", strip=True)
    else:
        pre2 = soup.find("pre")
        if pre2 and len(pre2.get_text()) > 100:
            lyrics = pre2.get_text("\n", strip=True)
    if not lyrics:
        # try divs that may contain lyrics
        candidate_divs = soup.find_all("div")
        best = ""
        for d in candidate_divs:
            text = d.get_text("\n", strip=True)
            # heuristics: lyrics usually have newlines and more than 80 chars
            if len(text) > len(best) and text.count("\n") >= 2 and len(text) > 100:
                best = text
        if best:
            lyrics = best

    # clean title/artist
    if title:
        title = title.replace(" Lyrics", "").strip()
    if artist:
        artist = artist.replace("Lyrics", "").strip()

    return {"url": song_url, "title": title or "Unknown title", "artist": artist or "Unknown artist", "lyrics": lyrics}

def present_choices(songs):
    print("\nMatches found:")
    for i, s in enumerate(songs, start=1):
        print(f"{i}. {s['title']} — {s['artist']}")
    print("0. Cancel / exit")

def ensure_yt_dlp_installed():
    return shutil.which("yt-dlp") is not None

def download_with_ytdlp(title, artist, out_format="mp3"):
    # Build a search query for YouTube
    query = f"{artist} {title}"
    ytdl_target = f"ytsearch1:{query}"  # yt-dlp will search YouTube and pick top result
    cmd = [
        "yt-dlp",
        ytdl_target,
        "-x",  # extract audio
        "--audio-format", out_format,
        "--audio-quality", "0",  # best
        "-o", "%(title)s.%(ext)s"
    ]
    print("Running yt-dlp... this will download the top YouTube result for:", query)
    try:
        subprocess.run(cmd, check=True)
        print("Download finished (saved as <song title>.<ext>)")
    except subprocess.CalledProcessError as e:
        print("yt-dlp failed with exit code", e.returncode)
    except FileNotFoundError:
        print("yt-dlp not found. Please install yt-dlp and ensure it's on your PATH.")

def main():
    print("Enter a distinctive line or fragment of lyrics to search (or blank to exit):")
    snippet = input("> ").strip()
    if not snippet:
        print("No snippet provided. Exiting.")
        return

    print("\nSearching Lyrics.com for matches...")
    try:
        links = search_lyricscom(snippet, max_results=10)
    except Exception as e:
        print("Search failed:", e)
        return

    if not links:
        print("No matches found on Lyrics.com.")
        return

    # For each found link, fetch metadata (title/artist). This will make a few requests.
    songs = []
    for idx, link in enumerate(links, start=1):
        try:
            info = parse_song_page(link)
            songs.append(info)
        except Exception as e:
            # skip on error but continue
            print(f"Warning: failed to parse result {link}: {e}")
        time.sleep(0.8)  # polite delay

    if not songs:
        print("No parsable song pages found.")
        return

    present_choices(songs)

    # choose
    while True:
        choice = input("\nChoose a number to view lyrics (or 0 to cancel): ").strip()
        if not choice.isdigit():
            print("Enter a number.")
            continue
        idx = int(choice)
        if idx == 0:
            print("Cancelled.")
            return
        if 1 <= idx <= len(songs):
            chosen = songs[idx - 1]
            break
        print("Number out of range.")

    print(f"\n--- {chosen['title']} — {chosen['artist']} ---\n")
    if chosen.get("lyrics"):
        print(chosen["lyrics"])
    else:
        print("(Lyrics could not be retrieved or are not present on the page.)")
    print("\n--- end of lyrics ---\n")

    # ask to download
    while True:
        download_answer = input("Download audio from YouTube? [y/N]: ").strip().lower()
        if download_answer in ("y", "yes"):
            if not ensure_yt_dlp_installed():
                print("yt-dlp is not installed or not on PATH. Install it first (e.g. `pip install yt-dlp` or follow installation instructions).")
                return
            # choose format
            fmt = input("Audio format (mp3/m4a/webm). Press Enter for 'mp3': ").strip().lower() or "mp3"
            if fmt not in ("mp3", "m4a", "webm", "aac", "wav", "flac"):
                print("Unknown format, using mp3.")
                fmt = "mp3"
            download_with_ytdlp(chosen["title"], chosen["artist"], out_format=fmt)
            return
        elif download_answer in ("n", "no", ""):
            print("Not downloading. Exiting.")
            return
        else:
            print("Please answer y or n.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting.")
        sys.exit(0)
