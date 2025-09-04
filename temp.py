#!/usr/bin/env python3
"""
genius_lyrics_search_and_download_enhanced.py

Enhanced CLI for searching Genius and downloading audio via yt-dlp.

Behavior change requested by user:
- When browsing an artist, the script now searches for albums first and only when the user
  selects an album will it fetch the songs included in that album. It will NOT fetch the
  artist's entire song list up front unless the Genius client library does not expose an
  album endpoint (fallback).

Notes:
- Set GENIUS_CLIENT_ACCESS_TOKEN env var or paste token when prompted.
- Install dependencies: pip install lyricsgenius requests beautifulsoup4
- Install yt-dlp if you want downloads: pip install yt-dlp (and ensure it's on PATH)

This script is defensive: it tries to use album endpoints when available, and falls back
to scraping the album page when necessary.
"""

import os
import sys
import subprocess
import shutil
import time
from typing import List, Dict, Optional, Tuple

# new imports for scraping fallback
import re
from urllib.parse import urljoin

try:
    import requests
except Exception:
    print("Missing dependency 'requests'. Install with: pip install requests")
    raise SystemExit(1)

try:
    from bs4 import BeautifulSoup
except Exception:
    print("Missing dependency 'beautifulsoup4'. Install with: pip install beautifulsoup4")
    raise SystemExit(1)

try:
    import lyricsgenius
except Exception:
    print("Missing dependency 'lyricsgenius'. Install with: pip install lyricsgenius")
    raise SystemExit(1)


def get_genius_client() -> lyricsgenius.Genius:
    token = os.environ.get("GENIUS_CLIENT_ACCESS_TOKEN") or os.environ.get("GENIUS_ACCESS_TOKEN")
    if not token:
        token = input("Enter your Genius client access token (or set GENIUS_CLIENT_ACCESS_TOKEN env var): ").strip()
        if not token:
            print("No token provided. Exiting.")
            sys.exit(1)
    g = lyricsgenius.Genius(token, timeout=15, retries=3, sleep_time=0.5)
    g.skip_non_songs = True
    g.excluded_terms = ["(Remix)", "(Live)"]
    return g


def search_by_lyrics(genius_client: lyricsgenius.Genius, snippet: str, artist_filter: Optional[str] = None, max_results: int = 10) -> List[Dict]:
    try:
        resp = genius_client.search_lyrics(snippet)
    except Exception as e:
        raise RuntimeError(f"Genius search_lyrics failed: {e}")

    results: List[Dict] = []

    # `resp` should be a dict-like structure; be defensive
    sections = (resp.get("sections") if isinstance(resp, dict) else getattr(resp, "get", lambda k, d=None: d)("sections", [])) or []
    for sec in sections:
        hits = sec.get("hits") or [] if isinstance(sec, dict) else []
        for h in hits:
            r = h.get("result") or {}
            title = r.get("title")
            prim = r.get("primary_artist") or {}
            artist = prim.get("name")
            url = r.get("url")
            if title and artist and url:
                entry = {"title": title.strip(), "artist": artist.strip(), "url": url.strip()}
                if artist_filter:
                    if artist_filter.strip().lower() != artist.strip().lower():
                        continue
                if entry not in results:
                    results.append(entry)
            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break
    return results


def search_by_title(genius_client: lyricsgenius.Genius, title: str, artist: Optional[str] = None) -> List[Dict]:
    try:
        song = genius_client.search_song(title, artist)
    except Exception as e:
        raise RuntimeError(f"Genius search_song failed: {e}")

    if song is None:
        return []

    # song may be an object with attributes or a dict
    song_title = getattr(song, "title", None) or (song.get("title") if isinstance(song, dict) else title)
    song_artist = getattr(song, "artist", None) or (song.get("artist") if isinstance(song, dict) else (artist or "Unknown"))
    song_url = getattr(song, "url", None) or (song.get("url") if isinstance(song, dict) else None)

    return [{
        "title": song_title,
        "artist": song_artist,
        "url": song_url,
        "song_obj": song,
    }]


def fetch_lyrics_for_result(genius_client: lyricsgenius.Genius, chosen: Dict) -> str:
    # If we have a Song object use its .lyrics property; otherwise fetch by URL
    song_obj = chosen.get("song_obj")
    if song_obj is not None:
        lyrics_attr = getattr(song_obj, "lyrics", None)
        if lyrics_attr:
            return lyrics_attr
        # sometimes song_obj is dict-like
        if isinstance(song_obj, dict):
            return song_obj.get("lyrics", "") or ""
    url = chosen.get("url")
    if not url:
        return ""
    # lyricsgenius provides a .lyrics method which may accept song_url or url
    try:
        # try with named param first
        lyrics = genius_client_call_lyrics(genius_client, url)
    except Exception as e:
        raise RuntimeError(f"Failed to fetch lyrics: {e}")
    return lyrics


def genius_client_call_lyrics(genius_client: lyricsgenius.Genius, url: str) -> str:
    """Helper to call lyrics fetching in a safe way across versions."""
    # try common signatures
    try:
        return genius_client.lyrics(song_url=url)
    except TypeError:
        pass
    except Exception as e:
        # other exceptions bubble up
        raise
    try:
        return genius_client.lyrics(url)
    except Exception:
        # last resort: try search_song by URL or scrape
        # search_song sometimes accepts song_api_path; we will try fetch via search_song if possible
        try:
            s = genius_client.search_song(url=url)
            if s is not None:
                return getattr(s, "lyrics", "") or ""
        except Exception:
            pass
    # If we got here, no lyrics could be fetched
    raise RuntimeError("Could not fetch lyrics with available genius client methods.")


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
        "-o", "%(title)s.%(ext)s",
    ]
    print("Running yt-dlp to download top YouTube result for:", query)
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"yt-dlp failed with exit code {e.returncode}")
    except FileNotFoundError:
        raise RuntimeError("yt-dlp not found on PATH. Install it first (e.g. pip install yt-dlp).")


def present_choices(results: List[Dict]):
    print("Matches:")
    for i, r in enumerate(results, start=1):
        print(f"{i}. {r.get('title')} — {r.get('artist')}")
    print("0. Cancel / back")


# --- New album-focused functions ---


def fetch_artist_albums(genius_client: lyricsgenius.Genius, artist_id: int, limit: int = 500) -> List[Dict]:
    """
    Try to fetch albums for an artist using Genius client album endpoints.
    Returns a list of album dicts: {'id': id, 'name': name, 'url': url}

    Falls back to returning [] if an albums endpoint isn't available or fails.
    """
    albums: List[Dict] = []
    per_page = 50
    page = 1

    # Prefer a high-level artist_albums call if available
    artist_albums_fn = getattr(genius_client, "artist_albums", None)
    if callable(artist_albums_fn):
        while len(albums) < limit:
            try:
                res = artist_albums_fn(artist_id, per_page=per_page, page=page)
            except Exception as e:
                print(f"Warning: failed to fetch artist albums page {page}: {e}")
                break
            # res expected as dict-like
            page_albums = res.get("albums") if isinstance(res, dict) else getattr(res, "get", lambda k, d=None: d)("albums", [])
            if not page_albums:
                break
            for a in page_albums:
                # a might be dict or object
                if isinstance(a, dict):
                    aid = a.get("id")
                    name = a.get("name")
                    url = a.get("url")
                else:
                    aid = getattr(a, "id", None)
                    name = getattr(a, "name", None) or getattr(a, "title", None)
                    url = getattr(a, "url", None)
                if name:
                    albums.append({"id": aid, "name": name, "url": url})
                if len(albums) >= limit:
                    break
            if len(page_albums) < per_page:
                break
            page += 1
            time.sleep(0.2)
        return albums

    # If no artist_albums method available, return empty list for caller to fallback
    return []


def fetch_album_songs(genius_client: lyricsgenius.Genius, album_id: int, album_name_hint: Optional[str] = None) -> List[Dict]:
    """
    Fetch songs for a specific album id. Attempt several available client methods;
    if none exist, return an empty list to signal fallback required.

    Returned list items: {'title':..., 'artist':..., 'url':...}
    """
    # Try album(...) first
    album_fn = getattr(genius_client, "album", None)
    if callable(album_fn):
        try:
            album_obj = album_fn(album_id)
            songs_list: List[Dict] = []
            if isinstance(album_obj, dict):
                tracks = album_obj.get("tracks") or album_obj.get("songs") or []
                for t in tracks:
                    title = t.get("title")
                    artist = (t.get("primary_artist") or {}).get("name")
                    url = t.get("url")
                    songs_list.append({"title": title, "artist": artist, "url": url})
                return songs_list
            else:
                tracks = getattr(album_obj, "tracks", None) or getattr(album_obj, "songs", None)
                if tracks:
                    for t in tracks:
                        title = getattr(t, "title", None)
                        artist = getattr(t, "artist", None) or (getattr(getattr(t, "primary_artist", None), "name", None) if getattr(t, "primary_artist", None) else None)
                        url = getattr(t, "url", None)
                        songs_list.append({"title": title, "artist": artist, "url": url})
                    return songs_list
        except Exception as e:
            print(f"Warning: album(...) call failed for album_id={album_id}: {e}")

    # Try album_songs if available
    album_songs_fn = getattr(genius_client, "album_songs", None)
    if callable(album_songs_fn):
        try:
            res = album_songs_fn(album_id)
            page_songs = res.get("songs") or [] if isinstance(res, dict) else getattr(res, "get", lambda k, d=None: d)("songs", [])
            out: List[Dict] = []
            for s in page_songs:
                out.append({"title": s.get("title"), "artist": (s.get("primary_artist") or {}).get("name"), "url": s.get("url")})
            return out
        except Exception as e:
            print(f"Warning: album_songs failed for album_id={album_id}: {e}")

    # If none of the album-specific endpoints are available, return empty list -> caller will fallback
    return []


def fetch_artist_songs(genius_client: lyricsgenius.Genius, artist_id: int, limit: int = 300) -> List[Dict]:
    """
    Fetches songs for an artist using the public API paging (artist_songs) when available.
    Returns a list of dicts with keys title, artist, url, album.
    """
    per_page = 50
    page = 1
    songs: List[Dict] = []

    artist_songs_fn = getattr(genius_client, "artist_songs", None)
    if callable(artist_songs_fn):
        while len(songs) < limit:
            try:
                res = artist_songs_fn(artist_id, per_page=per_page, page=page)
            except Exception as e:
                print(f"Warning: failed to fetch artist songs page {page}: {e}")
                break
            page_songs = res.get("songs") or [] if isinstance(res, dict) else getattr(res, "get", lambda k, d=None: d)("songs", [])
            if not page_songs:
                break
            for s in page_songs:
                title = s.get("title")
                primary = (s.get("primary_artist") or {}).get("name")
                url = s.get("url")
                album = None
                album_obj = s.get("album")
                if album_obj and isinstance(album_obj, dict):
                    album = album_obj.get("name")
                songs.append({"title": title, "artist": primary, "url": url, "album": album})
                if len(songs) >= limit:
                    break
            if len(page_songs) < per_page:
                break
            page += 1
            time.sleep(0.2)
        return songs

    # Fallback: try search_artist with get_full_info
    try:
        artist_full = genius_client.search_artist(artist_id, max_songs=limit, get_full_info=True)
        out: List[Dict] = []
        if artist_full and getattr(artist_full, "songs", None):
            for s in getattr(artist_full, "songs"):
                out.append({"title": getattr(s, "title", None), "artist": getattr(s, "artist", None), "url": getattr(s, "url", None), "album": getattr(s, "album", None)})
        return out
    except Exception:
        return songs


def search_artist_and_list_albums(genius_client: lyricsgenius.Genius, artist_name: str, max_albums_fetch: int = 200) -> Tuple[Optional[Dict], List[Dict]]:
    """
    Search for artist metadata using the client. Prefer API album endpoints;
    if they are missing or return nothing, attempt to scrape the artist page
    for albums (best-effort).
    Returns (artist_meta, albums_list).
    """
    try:
        artist_meta = genius_client.search_artist(artist_name, max_songs=0, get_full_info=False)
    except Exception as e:
        raise RuntimeError(f"Artist search failed: {e}")

    if artist_meta is None:
        return None, []

    # extract artist id if available
    artist_id = None
    if isinstance(artist_meta, dict):
        artist_id = artist_meta.get("id")
    else:
        artist_id = getattr(artist_meta, "id", None)

    # try standard API/client method first
    albums = []
    try:
        albums = fetch_artist_albums(genius_client, artist_id, limit=max_albums_fetch) if artist_id is not None else []
    except Exception:
        albums = []

    # If we got nothing from the API, try scraping the artist page
    if not albums:
        # attempt to obtain an artist page URL from artist_meta
        artist_url = None
        if isinstance(artist_meta, dict):
            artist_url = artist_meta.get("url")
        else:
            artist_url = getattr(artist_meta, "url", None)

        # If we still don't have an URL, craft one from the name (best effort)
        if not artist_url:
            # sanitize artist_name into a genius artist slug: replace whitespace with '-', remove weird chars
            slug = re.sub(r'[^A-Za-z0-9\s\-]', '', artist_name or "")
            slug = re.sub(r'\s+', '-', slug.strip())
            artist_url = f"https://genius.com/artists/{slug}" if slug else None

        if artist_url:
            try:
                scraped = scrape_artist_albums_from_url(artist_url, max_albums=max_albums_fetch)
                if scraped:
                    # normalize: keep 'id' as None, name and url present
                    albums = scraped
            except Exception:
                # swallow and continue to final fallback
                albums = albums or []

    return artist_meta, albums


def choose_from_list(prompt: str, max_choice: int) -> Optional[int]:
    while True:
        choice = input(prompt).strip()
        if not choice.isdigit():
            print("Enter a number.")
            continue
        idx = int(choice)
        if idx == 0:
            return None
        if 1 <= idx <= max_choice:
            return idx - 1
        print("Out of range.")


def main_menu():
    print("Genius CLI — choose a search mode:")
    print("1) Search by lyrics snippet")
    print("2) Search by song title")
    print("3) Search by artist (browse albums and songs)")
    print("0) Exit")
    choice = input("Select an option: ").strip()
    return choice


def post_lyrics_actions(chosen: Dict):
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
                download_audio_with_ytdlp(chosen.get("title", ""), chosen.get("artist", ""), audio_format=fmt)
            except Exception as e:
                print("Download failed:", e)
            return
        elif y in ("n", "no", ""):
            print("Not downloading. Returning to main menu.")
            return
        else:
            print("Answer 'y' or 'n'.")


def handle_lyrics_search(genius):
    snippet = input("Paste a distinctive lyrics fragment (blank to cancel):> ").strip()
    if not snippet:
        return
    artist_filter = input("If you know the artist, enter it to narrow results (press Enter to skip): ").strip() or None
    try:
        hits = search_by_lyrics(genius, snippet, artist_filter=artist_filter, max_results=10)
    except Exception as e:
        print("Search failed:", e)
        return
    if not hits:
        print("No matches found.")
        return
    present_choices(hits)
    sel = choose_from_list("Choose a number to view lyrics (0 to cancel): ", len(hits))
    if sel is None:
        return
    chosen = hits[sel]
    print(f"--- {chosen['title']} — {chosen['artist']} ---")
    try:
        lyrics = fetch_lyrics_for_result(genius, chosen)
    except Exception as e:
        print("Error fetching lyrics:", e)
        return
    print(lyrics or "(No lyrics returned)")
    post_lyrics_actions(chosen)


def handle_title_search(genius):
    title = input("Enter song title (blank to cancel): ").strip()
    if not title:
        return
    artist = input("If known, enter artist name to improve matching (press Enter to skip): ").strip() or None
    try:
        hits = search_by_title(genius, title, artist)
    except Exception as e:
        print("Search failed:", e)
        return
    if not hits:
        print("No match found for that title.")
        return
    present_choices(hits)
    sel = choose_from_list("Choose a number to view lyrics (0 to cancel): ", len(hits))
    if sel is None:
        return
    chosen = hits[sel]
    try:
        lyrics = fetch_lyrics_for_result(genius, chosen)
    except Exception as e:
        print("Error fetching lyrics:", e)
        return
    print(f"--- {chosen['title']} — {chosen['artist']} ---")
    print(lyrics or "(No lyrics returned)")
    post_lyrics_actions(chosen)


# --- New: Scraping fallback for album pages ---
def scrape_artist_albums_from_url(artist_url: str, max_albums: int = 200) -> List[Dict]:
    """
    Attempt to scrape an artist page (and a few sensible variants) for album links.
    Returns list of {'id': None, 'name': <album name>, 'url': <full album url>}.
    This is a best-effort fallback when the API/client doesn't expose albums.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; genius-scraper/1.0; +https://example.com)",
        "Accept-Language": "en-US,en;q=0.9",
    }

    candidate_urls = [artist_url.rstrip("/")]
    # try common artist albums listing variants
    candidate_urls.append(candidate_urls[0] + "/albums")
    # also try adding '/discography' as some sites use it
    candidate_urls.append(candidate_urls[0] + "/discography")

    found_albums: List[Dict] = []
    seen_urls = set()

    href_album_re = re.compile(r'/albums/[^/]+/.+', re.I)  # matches /albums/Artist/Album-Name
    href_alt_re = re.compile(r'/albums/[^/]+$', re.I)      # matches /albums/Album-Name (rare)

    for url in candidate_urls:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
        except Exception:
            continue
        if resp.status_code != 200:
            continue

        soup = BeautifulSoup(resp.text, "html.parser")

        # Prefer area with album-related keywords
        sections = []
        for cls in ("albums", "discography", "album-list", "artist-albums", "layout__content", "page"):
            sections.extend(soup.find_all(attrs={"class": re.compile(cls, re.I)}))

        anchors = []
        # Search candidate sections first
        if sections:
            for sec in sections:
                for a in sec.find_all("a", href=True):
                    href = a["href"].strip()
                    if href_album_re.search(href) or href_alt_re.search(href):
                        full = urljoin(url, href)
                        if full in seen_urls:
                            continue
                        title_text = a.get_text(" ", strip=True) or ""
                        # sometimes the anchor text is just "Album" or "View", look for nearby headings
                        if not title_text or len(title_text.split()) <= 1:
                            # try parent or sibling text heuristics
                            parent = a.find_parent()
                            if parent:
                                title_text = parent.get_text(" ", strip=True)
                        title_text = re.sub(r'\s*\|\s*Genius.*$', '', title_text, flags=re.I).strip()
                        title_text = re.sub(r'\s*\(\d+\s*tracks?\)\s*$', '', title_text, flags=re.I).strip()
                        anchors.append((title_text, full))
                        seen_urls.add(full)
                        if len(anchors) >= max_albums:
                            break
                if len(anchors) >= max_albums:
                    break

        # Fallback: scan whole page for /albums/ anchors
        if not anchors:
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href_album_re.search(href) or href_alt_re.search(href):
                    full = urljoin(url, href)
                    if full in seen_urls:
                        continue
                    title_text = a.get_text(" ", strip=True) or ""
                    title_text = re.sub(r'\s*\|\s*Genius.*$', '', title_text, flags=re.I).strip()
                    title_text = re.sub(r'\s*\(\d+\s*tracks?\)\s*$', '', title_text, flags=re.I).strip()
                    anchors.append((title_text, full))
                    seen_urls.add(full)
                    if len(anchors) >= max_albums:
                        break

        # Post-process anchors into album dicts
        for title_text, full in anchors:
            if not title_text:
                # derive a fallback from URL: last segment after second slash in /albums/Artist/Album-Name
                parts = full.rstrip("/").split("/")
                # prefer last part if it's album slug
                if parts:
                    slug = parts[-1]
                    title_text = slug.replace("-", " ").replace("_", " ").strip()
            title_text = re.sub(r'^\d+\.\s*', '', title_text).strip()
            if not title_text:
                continue
            found_albums.append({"id": None, "name": title_text, "url": full})
            if len(found_albums) >= max_albums:
                break

        if found_albums:
            break  # stop once we scraped something sensible from any candidate URL

    return found_albums


def handle_artist_search(genius):
    artist_name = input("Enter artist name (blank to cancel): ").strip()
    if not artist_name:
        return
    try:
        artist_obj, albums = search_artist_and_list_albums(genius, artist_name, max_albums_fetch=500)
    except Exception as e:
        print("Artist search failed:", e)
        return

    if albums:
        # We have album-level information: present albums first
        print(f"Found {len(albums)} albums for '{artist_name}'.")
        for i, a in enumerate(albums, start=1):
            print(f"{i}. {a.get('name')}")
        print("0. Cancel / back")
        sel = choose_from_list("Choose an album to list its songs (0 to cancel): ", len(albums))
        if sel is None:
            return
        album = albums[sel]
        album_id = album.get("id")
        album_name = album.get("name")
        album_url = album.get("url")
        print(f"Fetching songs for album: {album_name} ...")
        songs: List[Dict] = []
        try:
            songs = fetch_album_songs(genius, album_id, album_name_hint=album_name)
        except Exception as e:
            print(f"Failed to fetch album songs using album endpoint: {e}")
            songs = []

        # NEW: if album endpoints failed or returned no songs, try scraping the album page if we have a URL
        if not songs and album_url:
            try:
                print("Attempting to scrape album page for song list (requests + BeautifulSoup)...")
                songs = scrape_artist_albums_from_url(album_url)
                if songs:
                    print(f"Scraped {len(songs)} songs from album page.")
            except Exception as e:
                print("Scraping album page failed:", e)
                songs = []

        if not songs:
            # Fallback: if album-specific endpoint wasn't available, attempt to fetch artist songs and filter by album name.
            print("Album-specific endpoint not available or returned no songs. Falling back to fetching artist songs and filtering by album name (may be slower)...")
            try:
                artist_id = getattr(artist_obj, "id", None) if artist_obj is not None else None
                if artist_id is not None:
                    all_songs = fetch_artist_songs(genius, artist_id, limit=500)
                else:
                    artist_full = genius.search_artist(artist_name, max_songs=200, get_full_info=True)
                    all_songs = []
                    if artist_full and getattr(artist_full, "songs", None):
                        for s in getattr(artist_full, "songs"):
                            all_songs.append({"title": getattr(s, "title", None), "artist": getattr(s, "artist", None), "url": getattr(s, "url", None), "album": getattr(s, "album", None)})
                # filter by album name
                filtered: List[Dict] = []
                for s in all_songs:
                    album_field = s.get("album")
                    if album_field and isinstance(album_field, str):
                        if album_name and album_name.lower() in album_field.lower():
                            filtered.append({"title": s.get("title"), "artist": s.get("artist"), "url": s.get("url")})
                songs = filtered
            except Exception as e:
                print("Fallback fetch failed:", e)
                songs = []

        if not songs:
            print("No songs found for that album.")
            return

        # Present songs
        print(f"Songs in album '{album_name}':")
        for i, s in enumerate(songs, start=1):
            print(f"{i}. {s.get('title')} — {s.get('artist') or artist_name}")
        print("0. Cancel / back")
        sel2 = choose_from_list("Choose a song to view lyrics or download (0 to cancel): ", len(songs))
        if sel2 is None:
            return
        chosen = songs[sel2]
        # ensure artist field is present where possible
        if not chosen.get("artist"):
            chosen["artist"] = artist_name
        print(f"--- {chosen.get('title')} — {chosen.get('artist')} ---")
        try:
            lyrics = fetch_lyrics_for_result(genius, chosen)
        except Exception as e:
            print("Error fetching lyrics:", e)
            lyrics = None
        if lyrics:
            print(lyrics)
        else:
            print("(No lyrics returned or could not fetch.)")
        post_lyrics_actions(chosen)

    else:
        # No album endpoint available or no albums returned; fall back to older behavior: fetch artist songs and group by album
        print("No album-level data available from Genius client. Falling back to previous behavior (fetch artist songs and group by album). This may take longer.")
        try:
            artist_id = getattr(artist_obj, "id", None) if artist_obj is not None else None
            if artist_id is None:
                artist_full = genius.search_artist(artist_name, max_songs=200, get_full_info=True)
                songs_list: List[Dict] = []
                if artist_full and getattr(artist_full, "songs", None):
                    for s in getattr(artist_full, "songs"):
                        songs_list.append({"title": getattr(s, "title", None), "artist": getattr(s, "artist", None), "url": getattr(s, "url", None), "album": getattr(s, "album", None)})
            else:
                songs_list = fetch_artist_songs(genius, artist_id, limit=500)
        except Exception as e:
            print("Failed to fetch artist songs:", e)
            return

        # group by album
        albums_map: Dict[str, List[Dict]] = {}
        for s in songs_list:
            key = s.get("album") or "(no album)"
            albums_map.setdefault(key, []).append(s)

        keys = sorted(albums_map.keys())
        print(f"Found {len(keys)} album groups (including '(no album)').")
        for i, k in enumerate(keys, start=1):
            count = len(albums_map[k])
            print(f"{i}. {k} ({count} songs)")
        print("0. Cancel / back")
        sel = choose_from_list("Choose an album group to list its songs (0 to cancel): ", len(keys))
        if sel is None:
            return
        album_key = keys[sel]
        songs = albums_map[album_key]
        print(f"Songs in album group '{album_key}':")
        for i, s in enumerate(songs, start=1):
            print(f"{i}. {s.get('title')} — {s.get('artist')}")
        print("0. Cancel / back")
        sel2 = choose_from_list("Choose a song to view lyrics or download (0 to cancel): ", len(songs))
        if sel2 is None:
            return
        chosen = songs[sel2]
        print(f"--- {chosen.get('title')} — {chosen.get('artist')} ---")
        try:
            lyrics = fetch_lyrics_for_result(genius, chosen)
        except Exception as e:
            print("Error fetching lyrics:", e)
            lyrics = None
        if lyrics:
            print(lyrics)
        else:
            print("(No lyrics returned or could not fetch.)")
        post_lyrics_actions(chosen)


def main():
    genius = get_genius_client()
    while True:
        choice = main_menu()
        if choice == "1":
            handle_lyrics_search(genius)
        elif choice == "2":
            handle_title_search(genius)
        elif choice == "3":
            handle_artist_search(genius)
        elif choice == "0":
            print("Exiting.")
            return
        else:
            print("Unknown option. Try again.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted. Exiting.")
        sys.exit(0)
