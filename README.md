# generate_xspf

Generate one XSPF playlist per user with short-lived, user-specific signed media URLs and a long-lived signed URL for the playlist itself.

The nginx user map is the **single source of truth**: both `create_xspf.py` and nginx read the same map file. Runtime configuration is passed with command-line arguments only. The script does not read configuration from environment variables.

## Features

- Recursively scans a local media directory for video files.
- Keeps a broad list of supported video extensions.
- Optionally merges external XSPF playlists.
- Adds VLC network-caching metadata.
- Generates one playlist per user declared in the nginx map.
- Signs every local media URL with that user's secret.
- Signs the public XSPF URL with the same user-specific mechanism.
- Uses short-lived media URLs (6 hours by default) that are refreshed whenever playlists are regenerated.
- Keeps each signed playlist URL stable until its configured long-term expiration.
- Writes playlists atomically so clients never read a partially written file.
- Removes generated playlists when a user is removed from the nginx map.
- Revoking a user in the nginx map invalidates both old media URLs and the old playlist URL after nginx is reloaded.

## Requirements

Install the Python dependency:

```bash
pip install -r requirements.txt
```

nginx must be built with the secure link module if you use the included nginx configuration:

```bash
nginx -V 2>&1 | grep -- --with-http_secure_link_module
```

## User map

Install the example map:

```bash
cp xspf-users.map.example /etc/nginx/xspf-users.map
```

Then replace the example secrets:

```nginx
alice "replace-with-a-long-random-secret";
bob   "replace-with-another-long-random-secret";
```

Generate a secret with:

```bash
openssl rand -hex 32
```

The same map file is read by nginx and by `create_xspf.py`, so there is no second user database to synchronize.

The script accepts usernames containing letters, digits, `.`, `_`, and `-`, and secrets containing letters, digits, `.`, `_`, `~`, and `-`.

## Command-line usage

Show every available option:

```bash
python3 create_xspf.py --help
```

The main options are:

```text
--media-root PATH             Local media library root
--output-dir PATH             Generated playlist directory
--users-map PATH              nginx username/secret map
--base-url URL                Public base URL
--url-prefix PATH             Public nginx media prefix
--playlist-url-prefix PATH    Public nginx playlist prefix
--extra-playlist URL          External XSPF to merge; repeatable
--insecure-extra-playlists    Disable TLS verification for external XSPF files
--media-ttl SECONDS           Media URL lifetime (default: 21600 = 6 hours)
--playlist-expiration TIMESTAMP   Signed playlist URL expiration timestamp
--network-caching MS          VLC network cache
```

Defaults are:

```text
--media-root /downloads
--output-dir <media-root>/playlists
--users-map /etc/nginx/xspf-users.map
--base-url https://media.example.com
--url-prefix /library
--playlist-url-prefix /playlists
--media-ttl 21600
--playlist-expiration 2145916800
--network-caching 2000
```

No external playlist is imported unless `--extra-playlist` is explicitly provided.

## Recommended run command

Example using `/downloads` as the media directory and `/downloads/playlists` for generated playlists:

```bash
python3 create_xspf.py \
  --media-root /downloads \
  --output-dir /downloads/playlists \
  --users-map /etc/nginx/xspf-users.map \
  --base-url https://media.example.com \
  --url-prefix /library \
  --playlist-url-prefix /playlists \
  --media-ttl 21600 \
  --playlist-expiration 2145916800
```

To merge one or more external playlists:

```bash
python3 create_xspf.py \
  --media-root /downloads \
  --output-dir /downloads/playlists \
  --users-map /etc/nginx/xspf-users.map \
  --base-url https://media.example.com \
  --url-prefix /library \
  --playlist-url-prefix /playlists \
  --media-ttl 21600 \
  --playlist-expiration 2145916800 \
  --extra-playlist https://example.net/first.xspf \
  --extra-playlist https://example.net/second.xspf
```

TLS certificate verification is enabled for external playlists. Only use `--insecure-extra-playlists` when you intentionally need to fetch from a server whose certificate cannot be verified.

## Signed URL format

Media URLs and playlist URLs use the same signature formula, but they use different expiration values:

```text
base64url(md5(expiration + decoded_path + user_secret))
```

The trailing Base64 `=` padding is removed.

By default, media URLs expire 21,600 seconds (6 hours) after each generation run. The playlist URL uses the fixed long-term expiration `2145916800` (January 1, 2038 UTC).

A generated media URL therefore contains a timestamp near the current time plus six hours, for example:

```text
https://media.example.com/library/Movies/Example%20Movie.mkv?u=alice&e=1790000000&s=TOKEN
```

The playlist URL printed for Alice looks like:

```text
https://media.example.com/playlists/alice.xspf?u=alice&e=2145916800&s=TOKEN
```

The exact media expiration is computed once per script run, so every local media entry generated in that run shares the same expiration. Regenerating the XSPF refreshes those media URLs.

The decoded path is signed before URL percent-encoding. This matches nginx `$uri` when the included nginx configuration is used.

The playlist link is therefore a bearer URL: anyone who has the complete URL can use it while it remains valid. Removing the user from the nginx map and reloading nginx invalidates it.

## nginx configuration

Two example files are included:

- `nginx-secure-link.conf.example` - `map`, `server`, and signed `location` examples compatible with the generated URLs.
- `xspf-users.map.example` - the shared username-to-secret map read by both nginx and Python.

nginx loads the same map file:

```nginx
map $arg_u $xspf_secret {
    default "";
    include /etc/nginx/xspf-users.map;
}
```

Both `/library/` and `/playlists/` use:

```nginx
secure_link $arg_s,$arg_e;
secure_link_md5 "$secure_link_expires$uri$xspf_secret";
```

The nginx media `location` and the script's `--url-prefix` must match. The nginx media `alias` and the script's `--media-root` must also point to the same media library.

The nginx playlist `location` and `--playlist-url-prefix` must match. Its `alias` must point to the same directory as `--output-dir`.

For example:

```nginx
location ^~ /library/ {
    # secure_link checks
    alias /downloads/;
}

location ^~ /playlists/ {
    # secure_link checks
    alias /downloads/playlists/;
}
```

matches:

```bash
--media-root /downloads \
--output-dir /downloads/playlists \
--url-prefix /library \
--playlist-url-prefix /playlists
```

## Printed user URLs

After generation completes, the script prints the short-lived media expiration and one **long-lived signed playlist URL** for every active user:

```text
Media URLs expire at Unix timestamp 1790000000 (21600 seconds from generation).
Signed playlist URLs to give to users:
alice: https://media.example.com/playlists/alice.xspf?u=alice&e=2145916800&s=TOKEN
bob: https://media.example.com/playlists/bob.xspf?u=bob&e=2145916800&s=TOKEN
```

Give each user only their own URL. No separate HTTP Basic Authentication configuration is required by the included example because access to the playlist itself is checked by `secure_link`.

## Revoking a user

Remove the user from `/etc/nginx/xspf-users.map`, regenerate the playlists with the same command, validate nginx, then reload it:

```bash
python3 create_xspf.py \
  --media-root /downloads \
  --output-dir /downloads/playlists \
  --users-map /etc/nginx/xspf-users.map \
  --base-url https://media.example.com \
  --url-prefix /library \
  --playlist-url-prefix /playlists

nginx -t && systemctl reload nginx
```

The generated playlist file for that user is removed. After nginx is reloaded, nginx also rejects that user's previously issued playlist URL and media URLs because the username no longer resolves to a secret.

## Project layout

```text
generate_xspf-main/
├── create_xspf.py
├── nginx-secure-link.conf.example
├── xspf-users.map.example
├── README.md
└── requirements.txt
```
