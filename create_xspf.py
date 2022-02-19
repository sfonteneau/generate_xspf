#!/usr/bin/env python3
"""Generate one XSPF playlist per user with stable signed URLs.

The nginx user map is the single source of truth for users and secrets.
Runtime configuration is provided with command-line arguments only; no
environment variables are read.
"""

import argparse
import base64
import hashlib
import os
import re
import shlex
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
import xml.etree.ElementTree as ET

import requests


PERMANENT_EXPIRATION = 2145916800
DEFAULT_NETWORK_CACHING = 2000

VIDEO_EXTENSIONS = {
    ".3g2", ".3gp", ".3gp2", ".3gpp", ".amv", ".asf", ".avi", ".bik",
    ".crf", ".dav", ".divx", ".drc", ".dv", ".dvr-ms", ".evo", ".f4v",
    ".flv", ".gvi", ".gxf", ".iso", ".m1v", ".m2v", ".m2t", ".m2ts",
    ".m4v", ".mkv", ".mov", ".mp2", ".mp2v", ".mp4", ".mp4v", ".mpe",
    ".mpeg", ".mpeg1", ".mpeg2", ".mpeg4", ".mpg", ".mpv2", ".mts",
    ".mtv", ".mxf", ".mxg", ".nsv", ".nuv", ".ogg", ".ogm", ".ogv",
    ".ogx", ".ps", ".rec", ".rm", ".rmvb", ".rpl", ".thp", ".tod",
    ".ts", ".tts", ".txd", ".vob", ".vro", ".webm", ".wm", ".wmv",
    ".wtv", ".xesc",
}

XSPF_NS = "http://xspf.org/ns/0/"
VLC_NS = "http://www.videolan.org/vlc/playlist/ns/0/"
ET.register_namespace("", XSPF_NS)
ET.register_namespace("vlc", VLC_NS)


@dataclass(frozen=True)
class Config:
    media_root: Path
    output_dir: Path
    users_map: Path
    base_url: str
    url_prefix: str
    playlist_url_prefix: str
    extra_playlists: tuple[str, ...]
    verify_tls: bool
    expiration: int
    network_caching: int


def parse_args(argv: list[str] | None = None) -> Config:
    """Parse command-line options and return normalized configuration."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate one XSPF playlist per nginx-map user with stable "
            "secure_link-compatible URLs."
        )
    )
    parser.add_argument(
        "--media-root",
        type=Path,
        default=Path("/downloads"),
        metavar="PATH",
        help="local media library root (default: /downloads)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        metavar="PATH",
        help="playlist output directory (default: <media-root>/playlists)",
    )
    parser.add_argument(
        "--users-map",
        type=Path,
        default=Path("/etc/nginx/xspf-users.map"),
        metavar="PATH",
        help="nginx username/secret map (default: /etc/nginx/xspf-users.map)",
    )
    parser.add_argument(
        "--base-url",
        default="https://media.example.com",
        metavar="URL",
        help="public base URL (default: https://media.example.com)",
    )
    parser.add_argument(
        "--url-prefix",
        default="/library",
        metavar="PATH",
        help="public nginx media prefix (default: /library)",
    )
    parser.add_argument(
        "--playlist-url-prefix",
        default="/playlists",
        metavar="PATH",
        help="public nginx playlist prefix (default: /playlists)",
    )
    parser.add_argument(
        "--extra-playlist",
        action="append",
        default=[],
        metavar="URL",
        help="external XSPF URL to merge; may be specified multiple times",
    )
    parser.add_argument(
        "--insecure-extra-playlists",
        action="store_true",
        help="disable TLS certificate verification for external playlists",
    )
    parser.add_argument(
        "--expiration",
        type=int,
        default=PERMANENT_EXPIRATION,
        metavar="UNIX_TIMESTAMP",
        help=f"signed URL expiration timestamp (default: {PERMANENT_EXPIRATION})",
    )
    parser.add_argument(
        "--network-caching",
        type=int,
        default=DEFAULT_NETWORK_CACHING,
        metavar="MS",
        help=f"VLC network cache in milliseconds (default: {DEFAULT_NETWORK_CACHING})",
    )

    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        parser.error("--base-url must start with http:// or https://")

    url_prefix = "/" + args.url_prefix.strip("/")
    if url_prefix == "/":
        parser.error("--url-prefix cannot be the site root '/' ")

    playlist_url_prefix = "/" + args.playlist_url_prefix.strip("/")
    if playlist_url_prefix == "/":
        parser.error("--playlist-url-prefix cannot be the site root '/' ")

    if args.expiration <= 0:
        parser.error("--expiration must be a positive Unix timestamp")
    if args.network_caching < 0:
        parser.error("--network-caching cannot be negative")

    output_dir = args.output_dir or (args.media_root / "playlists")

    return Config(
        media_root=args.media_root,
        output_dir=output_dir,
        users_map=args.users_map,
        base_url=base_url,
        url_prefix=url_prefix,
        playlist_url_prefix=playlist_url_prefix,
        extra_playlists=tuple(args.extra_playlist),
        verify_tls=not args.insecure_extra_playlists,
        expiration=args.expiration,
        network_caching=args.network_caching,
    )


def qname(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


def sign_path(path: str, expiration: int, secret: str) -> str:
    """Return the token expected by nginx secure_link_md5."""
    payload = f"{expiration}{path}{secret}".encode("utf-8")
    digest = hashlib.md5(payload).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def build_signed_url(
    path: str,
    username: str,
    secret: str,
    config: Config,
) -> str:
    """Build a signed media URL for one user."""
    token = sign_path(path, config.expiration, secret)
    return (
        f"{config.base_url}{quote(path, safe='/')}"
        f"?u={quote(username, safe='')}&e={config.expiration}&s={token}"
    )


def build_playlist_url(username: str, secret: str, config: Config) -> str:
    """Return a signed public URL for a user's generated XSPF playlist."""
    playlist_path = f"{config.playlist_url_prefix}/{username}.xspf"
    return build_signed_url(playlist_path, username, secret, config)


def prettify_title(filename: str) -> str:
    """Convert a filename into a human-readable title."""
    return Path(filename).stem.replace(".", " ").replace("_", " ")


def load_users(users_map: Path) -> dict[str, str]:
    """Load and validate users directly from the nginx map include file.

    Expected entries look like:
        alice "a-long-random-secret";
    """
    if not users_map.exists():
        raise FileNotFoundError(f"nginx user map not found: {users_map}")

    users: dict[str, str] = {}
    username_pattern = re.compile(r"[A-Za-z0-9._-]+")
    secret_pattern = re.compile(r"[A-Za-z0-9._~-]+")

    for line_number, raw_line in enumerate(
        users_map.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        lexer = shlex.shlex(raw_line, posix=True, punctuation_chars=";")
        lexer.whitespace_split = True
        lexer.commenters = "#"

        try:
            tokens = list(lexer)
        except ValueError as exc:
            raise ValueError(
                f"Invalid nginx map syntax at {users_map}:{line_number}: {exc}"
            ) from exc

        if not tokens:
            continue

        if len(tokens) != 3 or tokens[2] != ";":
            raise ValueError(
                f"Invalid nginx map entry at {users_map}:{line_number}: "
                f"expected 'username \"secret\";'"
            )

        username, secret, _ = tokens

        if not username_pattern.fullmatch(username):
            raise ValueError(
                f"Invalid username at {users_map}:{line_number}: {username!r}. "
                "Use only letters, digits, dot, underscore, and hyphen."
            )
        if username in {"default", "hostnames", "include", "volatile"}:
            raise ValueError(
                "Reserved nginx map keyword cannot be used as a username: "
                f"{username!r}"
            )
        if not secret or not secret_pattern.fullmatch(secret):
            raise ValueError(
                f"Invalid secret for {username!r} at {users_map}:{line_number}. "
                "Use a literal secret containing only letters, digits, dot, "
                "underscore, tilde, or hyphen."
            )
        if username in users:
            raise ValueError(
                f"Duplicate username {username!r} in {users_map}:{line_number}"
            )

        users[username] = secret

    if not users:
        raise ValueError(f"No users found in nginx map: {users_map}")

    return users


def find_local_videos(media_root: Path, output_dir: Path) -> list[Path]:
    """Return local video files in a stable order."""
    if not media_root.exists():
        raise FileNotFoundError(f"Media directory not found: {media_root}")

    # If playlists are stored below the media root, do not needlessly traverse
    # that subtree while looking for video files.
    output_dir_resolved = output_dir.resolve(strict=False)

    def is_video(path: Path) -> bool:
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
            return False
        try:
            path.resolve(strict=False).relative_to(output_dir_resolved)
            return False
        except ValueError:
            return True

    return sorted(
        (path for path in media_root.rglob("*") if is_video(path)),
        key=lambda path: path.relative_to(media_root).as_posix().lower(),
    )


def fetch_xspf(url: str, verify_tls: bool) -> str:
    """Download one external XSPF playlist."""
    response = requests.get(url, verify=verify_tls, timeout=20)
    response.raise_for_status()
    return response.text


def parse_xspf(xml_content: str) -> list[dict[str, str]]:
    """Extract title and location fields from an external XSPF playlist."""
    root = ET.fromstring(xml_content)
    namespace = {"xspf": XSPF_NS}

    tracks: list[dict[str, str]] = []
    for track in root.findall(".//xspf:track", namespace):
        title_element = track.find("xspf:title", namespace)
        location_element = track.find("xspf:location", namespace)
        if location_element is None or not location_element.text:
            continue

        title = (
            title_element.text.strip()
            if title_element is not None and title_element.text
            else prettify_title(location_element.text.rsplit("/", 1)[-1])
        )
        tracks.append(
            {"title": title, "location": location_element.text.strip()}
        )

    return tracks


def load_external_tracks(config: Config) -> list[dict[str, str]]:
    """Load optional external playlists without failing local generation."""
    result: list[dict[str, str]] = []
    seen_titles: set[str] = set()

    for playlist_url in config.extra_playlists:
        try:
            for track in parse_xspf(fetch_xspf(playlist_url, config.verify_tls)):
                if track["title"] in seen_titles:
                    continue
                seen_titles.add(track["title"])
                result.append(track)
        except Exception as exc:
            print(
                f"Warning: could not import {playlist_url}: {exc}",
                file=sys.stderr,
            )

    return result


def add_track(
    track_list: ET.Element,
    playlist_extension: ET.Element,
    track_id: int,
    title: str,
    location: str,
    network_caching: int,
    album: str | None = None,
) -> None:
    """Append one track and its VLC-specific metadata to the playlist."""
    track = ET.SubElement(track_list, qname(XSPF_NS, "track"))
    ET.SubElement(track, qname(XSPF_NS, "title")).text = title
    ET.SubElement(track, qname(XSPF_NS, "location")).text = location

    if album:
        ET.SubElement(track, qname(XSPF_NS, "album")).text = album

    extension = ET.SubElement(
        track,
        qname(XSPF_NS, "extension"),
        {"application": "http://www.videolan.org/vlc/playlist/0"},
    )
    ET.SubElement(extension, qname(VLC_NS, "id")).text = str(track_id)
    ET.SubElement(extension, qname(VLC_NS, "option")).text = (
        f"network-caching={network_caching}"
    )

    ET.SubElement(
        playlist_extension,
        qname(VLC_NS, "item"),
        {"tid": str(track_id)},
    )


def build_playlist(
    username: str,
    secret: str,
    local_files: list[Path],
    external_tracks: list[dict[str, str]],
    config: Config,
) -> bytes:
    """Build one complete XSPF playlist for a user."""
    playlist = ET.Element(qname(XSPF_NS, "playlist"), {"version": "1"})

    timestamp = time.strftime("%Y-%m-%d %H:%M")
    total = len(local_files) + len(external_tracks)
    ET.SubElement(playlist, qname(XSPF_NS, "title")).text = (
        f"{username} - {total} tracks ({timestamp})"
    )

    track_list = ET.SubElement(playlist, qname(XSPF_NS, "trackList"))
    playlist_extension = ET.SubElement(
        playlist,
        qname(XSPF_NS, "extension"),
        {"application": "http://www.videolan.org/vlc/playlist/0"},
    )

    track_id = 0
    seen_titles: set[str] = set()

    for file_path in local_files:
        relative_path = file_path.relative_to(config.media_root)
        signed_path = f"{config.url_prefix}/{relative_path.as_posix()}"
        title = prettify_title(relative_path.name)
        album = relative_path.parent.as_posix().replace("/", " - ")
        if album == ".":
            album = None

        add_track(
            track_list,
            playlist_extension,
            track_id,
            title,
            build_signed_url(signed_path, username, secret, config),
            config.network_caching,
            album,
        )
        seen_titles.add(title)
        track_id += 1

    # External playlist URLs are kept exactly as provided by their source.
    # They cannot be re-signed without knowing the remote server's secret.
    for track in external_tracks:
        title = track["title"]
        if title in seen_titles:
            continue
        add_track(
            track_list,
            playlist_extension,
            track_id,
            title,
            track["location"],
            config.network_caching,
        )
        seen_titles.add(title)
        track_id += 1

    tree = ET.ElementTree(playlist)
    try:
        ET.indent(tree, space="  ")
    except AttributeError:
        pass

    return ET.tostring(playlist, encoding="utf-8", xml_declaration=True)


def write_atomically(target: Path, content: bytes) -> None:
    """Publish a file atomically so readers never see a partial playlist."""
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_bytes(content)
    os.chmod(temporary, 0o644)
    os.replace(temporary, target)


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv)

    try:
        users = load_users(config.users_map)
        local_files = find_local_videos(config.media_root, config.output_dir)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    external_tracks = load_external_tracks(config)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    generated_names: set[str] = set()
    for username, secret in sorted(users.items(), key=lambda item: item[0].lower()):
        target = config.output_dir / f"{username}.xspf"
        content = build_playlist(
            username,
            secret,
            local_files,
            external_tracks,
            config,
        )
        write_atomically(target, content)
        generated_names.add(target.name)
        print(
            f"{username}: {len(local_files) + len(external_tracks)} tracks -> {target}"
        )

    # The output directory is dedicated to generated playlists, so remove
    # playlists for users that have been deleted from the nginx user map.
    for orphan in config.output_dir.glob("*.xspf"):
        if orphan.name not in generated_names:
            orphan.unlink()
            print(f"{orphan.stem}: playlist removed (user no longer authorized)")

    print("\nSigned playlist URLs to give to users:")
    for username in sorted(users, key=str.lower):
        print(f"{username}: {build_playlist_url(username, users[username], config)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
