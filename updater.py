"""Checks GitHub for a newer release. Sends nothing about you, just asks GitHub
for the latest version number."""
import json
import re
import urllib.request

from version import REPO, __version__

API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"


def _parse(version):
    """'v1.10.2' -> (1, 10, 2)"""
    return tuple(int(n) for n in re.findall(r"\d+", version)[:3])


def is_newer(latest, current=__version__):
    try:
        return _parse(latest) > _parse(current)
    except ValueError:
        return False


def latest_release():
    """(version, page url) of the newest release on GitHub. Raises on network errors."""
    request = urllib.request.Request(API_URL, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"Maata/{__version__}",
    })
    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.load(response)
    return data["tag_name"].lstrip("v"), data["html_url"]
