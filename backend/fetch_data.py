"""
fetch_data.py — Pull real GitHub Issues from public mobile repos.

Run this ONCE before starting the server:
    python fetch_data.py

It saves JSON files to data/ that the RAG pipeline reads on startup.
No API key needed — GitHub public issues work unauthenticated.
(Rate limit: 60 req/hour unauthenticated, 5000/hour with GITHUB_TOKEN)
"""

import json
import os
import time
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# Optional: set GITHUB_TOKEN in .env for higher rate limits
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
HEADERS = {"Accept": "application/vnd.github+json"}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"


def fetch_linked_pr_description(owner: str, repo: str, issue_number: int) -> str:
    """
    For a closed issue, find the PR that fixed it via the timeline API and return
    its title + body (capped). Returns empty string if none found.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/timeline"
    headers = {**HEADERS, "Accept": "application/vnd.github.mockingbird-preview+json"}
    response = requests.get(url, headers=headers, params={"per_page": 100})
    if response.status_code != 200:
        return ""
    for event in response.json():
        if event.get("event") == "cross-referenced":
            issue_data = event.get("source", {}).get("issue", {})
            if issue_data.get("pull_request"):
                title = issue_data.get("title", "")
                body = (issue_data.get("body") or "")[:600]
                return f"Fix PR: {title}\n{body}" if body else f"Fix PR: {title}"
    return ""


def fetch_github_issues(owner: str, repo: str, labels: list[str], max_issues: int = 30) -> list[dict]:
    """
    Fetch issues from a public GitHub repo filtered by label.
    
    Why this approach instead of a Jira dataset?
    - No auth needed for public repos
    - Real bugs from real apps (flutter, react-native)
    - Labels like 'crash', 'regression', 'P0' map directly to our use case
    - Immediately recognizable to ML engineers reviewing your GitHub
    """
    issues = []
    label_str = ",".join(labels)
    url = f"https://api.github.com/repos/{owner}/{repo}/issues"
    since = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "labels": label_str,
        "state": "all",       # include closed (fixed) issues too
        "per_page": 30,
        "sort": "updated",
        "since": since,       # last 3 months only
    }

    print(f"Fetching {owner}/{repo} issues with labels: {labels}")
    response = requests.get(url, headers=HEADERS, params=params)

    if response.status_code == 403:
        print("⚠️  Rate limited. Either wait 1 hour or add GITHUB_TOKEN to .env")
        return []
    if response.status_code != 200:
        print(f"❌ Error {response.status_code}: {response.text[:200]}")
        return []

    raw = response.json()

    for item in raw[:max_issues]:
        # GitHub returns PRs as issues — skip them
        if "pull_request" in item:
            continue

        fix_description = ""
        if item["state"] == "closed":
            fix_description = fetch_linked_pr_description(owner, repo, item["number"])
            time.sleep(0.3)  # stay well under GitHub rate limits

        issues.append({
            "id": f"GH-{'RN' if repo == 'react-native' else owner[:2].upper()}-{item['number']}",   # e.g. GH-FL-1234, GH-RN-1234
            "github_number": item["number"],
            "summary": item["title"],
            "description": (item.get("body") or "")[:800],   # cap at 800 chars
            "fix_description": fix_description,
            "status": "Done" if item["state"] == "closed" else "Open",
            "priority": _infer_priority(item),
            "component": _infer_component(item, repo),
            "platform": _infer_platform(item),
            "labels": [l["name"] for l in item.get("labels", [])],
            "created": item["created_at"][:10],
            "resolved": item.get("closed_at", "")[:10] if item.get("closed_at") else None,
            "url": item["html_url"],
            "repo": f"{owner}/{repo}",
            "source": "github_issues",
        })

    print(f"  ✓ Fetched {len(issues)} issues from {owner}/{repo}")
    time.sleep(1)  # be polite to GitHub rate limits
    return issues


def _infer_priority(item: dict) -> str:
    """Infer priority from GitHub labels since GitHub has no native priority field."""
    label_names = [l["name"].lower() for l in item.get("labels", [])]
    if any(x in label_names for x in ["p0", "critical", "blocker", "severity: crash-failure"]):
        return "P1"
    if any(x in label_names for x in ["p1", "high", "severity: performance"]):
        return "P2"
    if any(x in label_names for x in ["p2", "medium"]):
        return "P3"
    return "P3"


def _infer_component(item: dict, repo: str) -> str:
    """Infer component from labels or title keywords."""
    title = item["title"].lower()
    label_names = " ".join([l["name"].lower() for l in item.get("labels", [])])
    combined = title + " " + label_names

    if any(x in combined for x in ["auth", "login", "token", "session"]):
        return "Authentication"
    if any(x in combined for x in ["crash", "fatal", "anr", "oom"]):
        return "Crash / Stability"
    if any(x in combined for x in ["navigation", "deep link", "routing"]):
        return "Navigation"
    if any(x in combined for x in ["network", "http", "fetch", "api"]):
        return "Networking"
    if any(x in combined for x in ["render", "ui", "layout", "screen"]):
        return "UI / Rendering"
    if any(x in combined for x in ["android"]):
        return "Android"
    if any(x in combined for x in ["ios", "iphone", "ipad"]):
        return "iOS"
    return repo.split("/")[-1].title()


def _infer_platform(item: dict) -> str:
    """Infer platform from labels and title."""
    label_names = " ".join([l["name"].lower() for l in item.get("labels", [])])
    title = item["title"].lower()
    combined = title + " " + label_names

    if "android" in combined and "ios" in combined:
        return "iOS, Android"
    if "android" in combined:
        return "Android"
    if any(x in combined for x in ["ios", "iphone", "ipad", "swift"]):
        return "iOS"
    return "iOS, Android"


def _extract_flutter_changelog_section(changelog: str, version: str) -> str:
    """Extract the changelog bullet points for a specific Flutter version."""
    import re
    # Matches both `## [3.44.4](url)` and `### [3.44.3](url)` patterns
    pattern = rf'#{{2,3}} \[{re.escape(version)}\][^\n]*\n(.*?)(?=\n#{{2,3}} |\Z)'
    m = re.search(pattern, changelog, re.DOTALL)
    if not m:
        return ""
    return m.group(1).strip()[:1200]


def fetch_flutter_releases(months: int = 3) -> list[dict]:
    """Flutter doesn't use GitHub Releases for stable builds.
    Uses the official Flutter infra API + CHANGELOG.md."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)

    # 1. Get stable versions from Flutter's official release manifest
    infra_url = "https://storage.googleapis.com/flutter_infra_release/releases/releases_macos.json"
    r = requests.get(infra_url)
    if r.status_code != 200:
        print(f"❌ Flutter infra API error: {r.status_code}")
        return []

    all_stable = [rel for rel in r.json().get("releases", [])
                  if rel.get("channel") == "stable"]
    seen = set()
    deduped = []
    for rel in all_stable:
        v = rel["version"]
        if v not in seen:
            seen.add(v)
            deduped.append(rel)

    recent = [s for s in deduped
              if datetime.fromisoformat(s["release_date"].replace("Z", "+00:00")) >= cutoff]
    items = recent if recent else deduped[:10]

    # 2. Fetch CHANGELOG.md once for release notes
    changelog = ""
    rc = requests.get("https://raw.githubusercontent.com/flutter/flutter/stable/CHANGELOG.md")
    if rc.status_code == 200:
        changelog = rc.text

    # 3. Build release objects
    releases = []
    for item in items:
        version = item["version"]
        notes = _extract_flutter_changelog_section(changelog, version)
        releases.append({
            "version": f"FL-{version}",
            "release_date": item["release_date"][:10],
            "platform": "iOS, Android",
            "repo": "flutter/flutter",
            "highlights": [],
            "changes": notes or f"Flutter {version} stable release. No detailed changelog available.",
            "known_issues": [],
            "source": "release_notes",
        })

    label = f"last {months} months" if recent else f"latest {len(items)} (infra fallback)"
    print(f"  ✓ Fetched {len(releases)} Flutter stable releases ({label})")
    return releases


def fetch_rn_releases(months: int = 3) -> list[dict]:
    """React Native uses GitHub Releases — fetch them directly."""
    url = "https://api.github.com/repos/facebook/react-native/releases"
    cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)

    all_raw = []
    response = requests.get(url, headers=HEADERS, params={"per_page": 50})
    if response.status_code != 200:
        print(f"❌ Error fetching RN releases: {response.status_code}")
        return []
    all_raw = [r for r in response.json()
               if not r.get("draft") and not r.get("prerelease")]

    recent = [r for r in all_raw
              if datetime.fromisoformat(r["published_at"].replace("Z", "+00:00")) >= cutoff]
    items = recent if recent else all_raw[:10]

    releases = []
    for item in items:
        releases.append({
            "version": f"RN-{item['tag_name']}",
            "release_date": item["published_at"][:10],
            "platform": "iOS, Android",
            "repo": "facebook/react-native",
            "highlights": [],
            "changes": (item.get("body") or "No release notes provided.")[:1200],
            "known_issues": [],
            "source": "release_notes",
        })

    label = f"last {months} months" if recent else "latest (no recent releases found)"
    print(f"  ✓ Fetched {len(releases)} React Native releases ({label})")
    time.sleep(0.5)
    return releases


def generate_release_notes() -> list[dict]:
    """
    Release notes are still fixtures — there's no public API for this.
    We use RM (Release Management) prefix as you requested.
    These are realistic mobile release notes tied to the GitHub repos we're indexing.
    """
    return [
        {
            "version": "RM-2024.1.0",
            "release_date": "2024-01-15",
            "platform": "iOS, Android",
            "repo": "flutter/flutter",
            "highlights": [
                "Flutter 3.19 engine upgrade",
                "Impeller rendering enabled by default on iOS",
                "Android platform view performance improvements",
                "Fixed null safety migration crash in legacy plugins"
            ],
            "changes": "Major engine upgrade to Flutter 3.19. Impeller GPU rendering enabled by default on iOS, replacing Skia. Android platform view rendering refactored for lower latency. Several null safety violations in legacy plugin interop resolved.",
            "known_issues": ["Impeller causes blank screen on iPhone 12 mini — fix in RM-2024.1.1"]
        },
        {
            "version": "RM-2024.1.1",
            "release_date": "2024-01-22",
            "platform": "iOS",
            "repo": "flutter/flutter",
            "highlights": [
                "Impeller blank screen fix for iPhone 12 mini",
                "Metal shader compilation fix"
            ],
            "changes": "Hotfix for Impeller rendering blank screen on iPhone 12 mini and older A14 devices. Metal shader pre-compilation added to resolve first-frame stutter.",
            "known_issues": []
        },
        {
            "version": "RM-2024.2.0",
            "release_date": "2024-02-10",
            "platform": "iOS, Android",
            "repo": "facebook/react-native",
            "highlights": [
                "React Native 0.73.4",
                "New Architecture (Fabric) stability improvements",
                "Hermes engine memory leak fix",
                "iOS 17 gesture recognizer regression fixed"
            ],
            "changes": "React Native 0.73.4 release. New Architecture Fabric renderer improved stability for concurrent mode. Hermes engine patch fixes memory leak in long-running apps. iOS 17 introduced a gesture recognizer conflict with React Native's touch system — patched in this release.",
            "known_issues": ["Android back handler broken on Android 14 with predictive back gesture — tracking in GH-RN-42123"]
        },
        {
            "version": "RM-2024.2.1",
            "release_date": "2024-02-20",
            "platform": "Android",
            "repo": "facebook/react-native",
            "highlights": [
                "Android 14 predictive back gesture fix",
                "Back handler API now supports predictive animations"
            ],
            "changes": "Android 14 introduced predictive back gesture system incompatible with React Native's BackHandler API. This release adds native support for the predictive back gesture, enabling smooth animations on Android 14+.",
            "known_issues": []
        },
        {
            "version": "RM-2024.3.0",
            "release_date": "2024-03-05",
            "platform": "iOS, Android",
            "repo": "flutter/flutter",
            "highlights": [
                "Flutter 3.22 — Impeller on Android (preview)",
                "DevTools 2.32",
                "Web platform rendering improvements",
                "TextField cursor regression fix"
            ],
            "changes": "Impeller GPU renderer enters preview on Android (Vulkan-capable devices). DevTools updated with CPU profiling improvements. TextField cursor position regression from 3.19 resolved — affected RTL text inputs and autocomplete overlays.",
            "known_issues": ["Impeller on Android causes ANR on Samsung Galaxy A-series — tracking in GH-FL-145001"]
        },
        {
            "version": "RM-2024.3.1",
            "release_date": "2024-03-15",
            "platform": "Android",
            "repo": "flutter/flutter",
            "highlights": [
                "Impeller ANR fix for Samsung Galaxy A-series",
                "Vulkan driver compatibility layer added"
            ],
            "changes": "Impeller Vulkan renderer caused ANR on Samsung devices with Mali GPU driver 24.0.x. Added compatibility shim detecting Mali driver version and falling back to OpenGL on affected devices.",
            "known_issues": []
        }
    ]


def main():
    all_issues = []

    flutter_issues = fetch_github_issues(
        owner="flutter",
        repo="flutter",
        labels=["c: crash"],
        max_issues=25
    )
    all_issues.extend(flutter_issues)

    flutter_regression = fetch_github_issues(
        owner="flutter",
        repo="flutter",
        labels=["c: regression"],
        max_issues=25
    )
    all_issues.extend(flutter_regression)

    rn_issues = fetch_github_issues(
        owner="facebook",
        repo="react-native",
        labels=["Bug"],
        max_issues=25
    )
    all_issues.extend(rn_issues)

    if not all_issues:
        print("\n⚠️  No issues fetched.")

    issues_path = DATA_DIR / "github_issues.json"
    with open(issues_path, "w") as f:
        json.dump(all_issues, f, indent=2)
    print(f"\n✅ Saved {len(all_issues)} issues → {issues_path}")

    all_releases = []
    all_releases.extend(fetch_flutter_releases(months=3))
    all_releases.extend(fetch_rn_releases(months=3))

    if not all_releases:
        print("⚠️  No releases fetched — falling back to fixtures")
        all_releases = generate_release_notes()

    releases_path = DATA_DIR / "release_notes.json"
    with open(releases_path, "w") as f:
        json.dump(all_releases, f, indent=2)
    print(f"✅ Saved {len(all_releases)} release notes → {releases_path}")

    print("\nNext step: python main.py")


if __name__ == "__main__":
    main()
