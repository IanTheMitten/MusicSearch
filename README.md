````markdown
# MusicSearch

MusicSearch is a Python project for searching song lyrics. This repository contains two versions:

- **MusicSearch_ver1**: Uses [Lyrics.com](https://www.lyrics.com) for fetching lyrics.  
- **MusicSearch_ver2**: Uses the [Genius API](https://genius.com/developers) for fetching lyrics and optionally downloading audio from YouTube.

---

## Prerequisites

- Python 3.8 or higher
- `pip` installed
- Optional (for MusicSearch_ver2 audio downloads): `yt-dlp` installed and available in PATH  

---

## Installation

1. Clone the repository:

```bash
git clone https://github.com/IanTheMitten/MusicSearch.git
cd MusicSearch
````

2. Install Python dependencies:

```bash
pip install -r requirements.txt
```

---

## MusicSearch\_ver1 (Lyrics.com)

1. Navigate to the folder:

```bash
cd MusicSearch
```

2. Run the script:

```bash
python MusicSearch_ver1.py
```

3. Follow on-screen instructions to search for lyrics.

*Note:* Version 1 scrapes Lyrics.com. It may break if the website layout changes.

---

## MusicSearch\_ver2 (Genius API + YouTube audio)

### 1. Obtain a Genius API token

1. Go to [Genius Developers](https://genius.com/developers).
2. Log in or create an account.
3. Click **Create an API Client**.
4. Fill in the required fields (App name, website, etc.) and submit.
5. Copy the **Access Token**.

### 2. Provide your Genius API token

You can either:

* **Set an environment variable** (recommended):

```bash
export GENIUS_CLIENT_ACCESS_TOKEN="your_access_token_here"   # macOS/Linux
setx GENIUS_CLIENT_ACCESS_TOKEN "your_access_token_here"     # Windows
```

* **Or paste the token when prompted** by the script (less secure for public repos).

---

### 3. Run MusicSearch\_ver2

1. Navigate to the folder:

```bash
cd MusicSearch
```

2. Run the script:

```bash
python MusicSearch_ver2.py
```

3. Paste a lyrics snippet when prompted.
4. Select a song from the search results to view full lyrics.
5. Optionally, download audio from YouTube by following prompts (requires `yt-dlp`).

**Audio download details:**

* Default format: `mp3`
* Supported formats: `mp3`, `m4a`, `webm`, `aac`, `wav`, `flac`
* yt-dlp automatically downloads the top YouTube search result matching `artist + title + audio`.

---

## Notes

* Version 1 scrapes Lyrics.com; results may break if the site layout changes.
* Version 2 uses Genius API, which is more reliable.
* Respect Genius API rate limits when running searches.
* Ensure `yt-dlp` is installed if you want audio downloads.

---

## License

MIT License
