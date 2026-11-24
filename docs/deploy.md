# Deploying to the droplet

The runbook for the one-hour session that puts Studious on a DigitalOcean
droplet. The decisions behind it are in `hosting.md` and `next-steps.md`
(session 1, step 6): one container, reachable only over Tailscale, pulled from
GHCR by a timer on the droplet, encrypted backups to Backblaze B2.

> **First run: 2026-11-17 to 11-23**, on Ubuntu 24.04 with a 1 GB droplet,
> every step through 12. It worked as written apart from the notes now in the
> steps below: the DigitalOcean firewall form, the GHCR package that was
> already public, timers that started early after a reboot (fixed in
> `provision.sh`), and a stray process on the speech helper's port.
> `troubleshooting.md` ("Droplet") has what was seen. Fix the script or this
> page as you go.

Who runs what: **Mac** is a terminal on the laptop, **droplet** is a root shell
on the droplet (over SSH), **web** is a browser.

## What gets installed where

| Path on the droplet | What |
|---|---|
| `/opt/studious/compose.yml` | The production compose file (`deploy/compose.yml`) |
| `/usr/local/lib/studious/` | `studious-update.sh`, `studious-backup.sh`, `studious-restore-test.sh` |
| `/etc/systemd/system/studious-*.{service,timer}` | Update every 5 minutes, backup daily 03:30 UTC, restore test Sundays 05:00 UTC. Enabled by hand in steps 8 and 11, not by `provision.sh` |
| `/etc/apt/apt.conf.d/52studious-reboot` | Reboot at 09:00 UTC when a security update needs it (see "Keeping it patched") |
| `/etc/studious/env` | The container's environment: API key and settings (0600) |
| `/etc/studious/restic.env`, `restic-password` | Backup repository, B2 key, passphrase (0600) |
| `/srv/studious/data` | The data directory, owned by UID 10001, bind-mounted at `/data` |
| `/var/lib/studious/failed-image` | ID of an image that failed its healthcheck, so it is not retried |

How an update reaches the droplet: a push to `main` passes CI, the `publish`
job pushes `ghcr.io/zurt/studious:main` and `:sha-<commit>`, and within five
minutes `studious-update.timer` pulls `:main`. If the image ID changed and no
job is queued or running, it runs `docker compose up -d`, waits for the
healthcheck and, if that fails, puts the previous image back and exits non-zero.

## 0. Before you start

- Merge the branch with `deploy/` and the CI changes, and let the first
  `publish` job on `main` finish. Check github.com/zurt?tab=packages for
  `studious`. The droplet has nothing to pull until then.
- The production Anthropic key (Keychain item `ANTHROPIC_API_KEY_PROD`) has a
  spend cap in the Anthropic console.
- The Mac is on the tailnet (`tailscale status`).
- A password manager entry is ready for the restic passphrase.

## 1. Backblaze B2 bucket and key (web)

1. Create a bucket: private, any unique name, default encryption on. Note the
   name. (restic encrypts everything itself; the bucket never sees plaintext.)
2. App Keys, add an application key: **restricted to that one bucket**, read
   and write. Copy the keyID and the application key now; the key is shown
   once. Do not use the master key.

## 2. Create the droplet (web)

- Image: **Ubuntu 24.04 LTS x64**. (`provision.sh` installs `docker-compose-v2`,
  which the 24.04 archive has.)
- Size: Basic, regular, **1 GB RAM**, 25 GB disk (the cheapest). The container
  is limited to 640 MiB (`hosting.md`, "Memory"). The library was 728 MB on
  2026-11-13, so the disk is enough for the data, the 818 MB image and a
  `store`-only restore test. Resize the disk if it fills (`df -h`).
- Region: any. It matters only for the round trip to the Anthropic API
  (`hosting.md`); the Mac reaches it over the tailnet either way.
- Networking: IPv4 only; leave IPv6 off. Nothing here uses it.
- Authentication: an SSH key, no password. A key made just for the droplet
  (`ssh-keygen -t ed25519 -f ~/.ssh/studious_droplet`, then `ssh-add
  --apple-use-keychain ~/.ssh/studious_droplet` to keep its passphrase in the
  Keychain) can be revoked without touching anything else. After step 5 it is
  only needed from the Recovery Console. Leave DigitalOcean's paid backups
  off; restic is the backup.
- Note the public IP. You use it once, in the next step.

## 3. Provision (Mac, then droplet)

Mac:

```bash
ssh -i ~/.ssh/studious_droplet root@<droplet-public-ip>
```

Droplet:

```bash
git clone https://github.com/zurt/studious.git
cd studious/deploy
./provision.sh
```

`provision.sh` installs Docker, the compose plugin, restic and
unattended-upgrades from Ubuntu, and Tailscale from Tailscale's apt
repository; adds a 1 GB swap file; creates `/srv/studious/data` and
`/etc/studious`; installs the scripts, compose file and units; sets up ufw
(deny incoming, allow `tailscale0` and UDP 41641, allow SSH for now); turns
on the 09:00 UTC automatic reboot. It does not enable the timers: steps 8 and
11 do, once what each needs exists. It is safe to run again, and it never
overwrites the files in `/etc/studious`.

At the end it prints the restic passphrase it generated. **Copy it into the
password manager now.** Without it the backups cannot be read, including after
the droplet is gone.

## 4. Join the tailnet (droplet, then Mac)

Droplet:

```bash
tailscale up --ssh
tailscale set --auto-update
```

Open the login URL it prints in a browser on the Mac and approve the machine.
The second command lets Tailscale update itself: unattended-upgrades only
takes Ubuntu's own packages, and Tailscale is the only way in after step 5.
Then, in the Tailscale admin console (web), open the droplet's menu and choose
**Disable key expiry**, or it drops off the tailnet when the key expires.

Mac, in a new terminal (leave the first SSH session open):

```bash
tailscale status                       # the droplet is listed
ssh root@<droplet-tailnet-name>        # Tailscale SSH, no key needed
```

Do not go on until the second command works. If typing feels laggy, `tailscale
ping <droplet-tailnet-name>` says whether the path is `via DERP(...)` (a
relay) or direct; new connections often start on a relay and go direct
within seconds.

## 5. Close public SSH (droplet, then web)

Droplet:

```bash
cd ~/studious/deploy
./provision.sh --lock-down
```

It removes the ufw rule for port 22. Check from the Mac: `ssh -o ConnectTimeout=5
root@<droplet-public-ip>` must time out, and the tailnet SSH from step 4 must
still work in a new terminal.

Second layer (web): Networking, Firewalls, create a firewall (any name, e.g.
`studious`) with **one inbound rule, UDP 41641 from anywhere** (Tailscale's
direct connections), no SSH, no HTTP, no HTTPS; outbound all. In the rule
form, set **Type to Custom**: "All UDP" hides the port field. Protocol UDP,
port 41641, sources All IPv4 and All IPv6 only (remove the droplet's own tag
if the form adds it). Delete the default SSH rule, and apply the firewall to
the droplet. Tailscale also works through relays without that rule, so it
only improves speed.

Recovery if you lock yourself out: DigitalOcean's web **Recovery Console** (droplet
page, Access) does not use the network. Open public SSH again from there with
`ufw allow 22/tcp`.

Why the container is safe either way: Docker's published ports bypass ufw, so
the firewall alone would not protect port 8000. `compose.yml` binds it to
`127.0.0.1`, and only `tailscale serve` (step 9) exposes it, to the tailnet.

## 6. Make the GHCR package public (web)

The repo is public and the image holds no secrets, so the droplet can pull
without a credential. github.com/zurt?tab=packages, open `studious`, Package
settings, Change visibility, Public. A package created by the first `publish`
run is private until you do this. Once it is public (it was by the first
run), this step is just the check below.

Check from the droplet (no login on this machine):

```bash
docker pull ghcr.io/zurt/studious:main
```

If you prefer it private: create a classic personal access token with only
`read:packages` (GHCR does not accept fine-grained tokens), and on the droplet
run `docker login ghcr.io -u zurt --password-stdin` and paste it. That puts a
read-only credential in `/root/.docker/config.json` on the droplet, the one
exception to "no credential beyond `GITHUB_TOKEN`".

## 7. Fill in the secrets (Mac, droplet)

Mac: put the production key on the clipboard without printing it.

```bash
security find-generic-password -a "$USER" -w -s ANTHROPIC_API_KEY_PROD | pbcopy
```

Droplet:

```bash
nano /etc/studious/env         # paste after ANTHROPIC_API_KEY=
```

Add `WANIKANI_API_TOKEN=` if you use it. Leave the Mac routes commented for now
(step 12). Then `nano /etc/studious/restic.env`: the bucket name and the B2
keyID and application key from step 1. Clear the clipboard afterwards.

## 8. First rollout (droplet)

```bash
systemctl start studious-update.service    # waits for the healthcheck, up to 3 minutes
journalctl -u studious-update -n 30 --no-pager
docker ps
curl -s http://127.0.0.1:8000/api/health   # {"ok":true}
systemctl enable --now studious-update.timer
```

The log should say `first install of sha256:...` and `rollout done`. If it
does not, read `docker logs studious` and `troubleshooting.md`.

## 9. HTTPS on the tailnet (droplet, web, Mac)

Web: in the Tailscale admin console, DNS, turn on **HTTPS Certificates** if it
is off.

Droplet:

```bash
tailscale serve --bg 8000
tailscale serve status
```

Mac: open `https://<droplet-tailnet-name>/` (it prints the full
`.ts.net` name). Use `serve`, never `funnel`: funnel publishes to the internet.

## 10. Move the data (Mac, droplet)

The container must not run during the copy, and the Mac backend must not
write to `backend/data` afterwards.

Mac: stop `make run-backend` (Ctrl-C in its terminal) and check it is gone:
`curl -s -m 2 http://127.0.0.1:8000/api/health` prints nothing. Note the
size and counts:

```bash
du -sh backend/data
find backend/data -type f -not -name .DS_Store | wc -l
wc -l backend/data/store/*.jsonl
```

Droplet: stop the container and the update timer, and check the space.

```bash
systemctl stop studious-update.timer
docker compose -f /opt/studious/compose.yml stop
df -h /srv
```

Mac: copy over the tailnet. Mind the trailing slashes.

```bash
rsync -a --stats --exclude .DS_Store \
  backend/data/ root@<droplet-tailnet-name>:/srv/studious/data/
```

Droplet: fix the owner and compare.

```bash
chown -R 10001:10001 /srv/studious/data
find /srv/studious/data -type f | wc -l
wc -l /srv/studious/data/store/*.jsonl
```

The counts must equal the Mac's. Then start it again:

```bash
systemctl start studious-update.service
systemctl start studious-update.timer
```

Open the web app (step 9) and look at a document, the vocab list and the study
queue. Leave `backend/data` on the Mac as it is, as a second copy, until a
restore test has passed (step 12). After that, nothing should run against it
(`next-steps.md`, step 3).

Reference data: if `backend/data/refs` existed, it came across. If not,
build it in the container:

```bash
docker exec studious python scripts/fetch_refs.py
```

## 11. Backups (droplet)

```bash
set -a; . /etc/studious/restic.env; set +a
restic init
systemctl start studious-backup.service     # the first one uploads the whole library
journalctl -u studious-backup -n 20 --no-pager
restic snapshots
systemctl start studious-restore-test.service
journalctl -u studious-restore-test -n 30 --no-pager
systemctl enable --now studious-backup.timer studious-restore-test.timer
```

The backup log ends in `studious-backup: done`; the restore test's in
`ok (restored: full)` (or `store`). A failure from before `restic init` (a
`404` and "Is there a repository at the following location?") is a timer that
ran too early: clear it with `systemctl reset-failed` once a manual run
passes.

The restore test restores the latest snapshot to a temp directory, checks the
repository (reading 5% of the data), parses every `store/*.jsonl`, and compares
older files with the live ones by checksum. It restores everything only if the
snapshot fits in 70% of the free disk; otherwise it restores `store/` only and
says so in the log. Force one with `RESTORE_SUBSET=store` or `full` (set it in
`/etc/systemd/system/studious-restore-test.service` with `Environment=`).

A passed test means the passphrase works. Check the passphrase in the password
manager now by reading it back against `/etc/studious/restic-password`.

## 12. Speech and Anki on the Mac (Mac, droplet)

Both stay on the Mac and are reached over the tailnet (`hosting.md`, "New
homes"). Worked as written on the first run.

1. Mac: start the helper in its own terminal and publish it:
   ```bash
   make say-helper
   curl -s http://127.0.0.1:8766/health     # {"ok": true, "service": "studious-say-helper", ...}
   tailscale serve --bg --tcp 8766 tcp://127.0.0.1:8766
   ```
   An HTML "File not found" page instead of that JSON, or `Address already
   in use` from `make say-helper`, means something else holds the port
   (`troubleshooting.md`).
2. Mac, with Anki open:
   ```bash
   curl -s http://127.0.0.1:8765 -d '{"action":"version","version":6}'
   tailscale serve --bg --tcp 8765 tcp://127.0.0.1:8765
   tailscale serve status
   ```
3. Droplet: both must answer before going on.
   ```bash
   curl -s http://<mac-tailnet-name>:8766/health
   curl -s http://<mac-tailnet-name>:8765 -d '{"action":"version","version":6}'
   ```
4. Droplet: uncomment `STUDIOUS_TTS_ENGINE`, `STUDIOUS_SAY_HELPER_URL` and
   `ANKI_CONNECT_URL` in `/etc/studious/env`, with the Mac's tailnet name.
   Apply it when no job is running (the container restarts):
   `docker compose -f /opt/studious/compose.yml up -d --force-recreate`.
5. Once, to make clips for the moved library (Settings > Speech's "Generate
   now" only covers items already waiting):
   ```bash
   curl -s -X POST http://127.0.0.1:8000/api/tts/catch-up \
     -H 'Content-Type: application/json' -d '{"all": true}'
   ```
   The Mac makes them in the background; keep the helper running until the
   pending count in Settings > Speech is zero.
6. In the app: play a word's audio, and press the Anki sync button.

The `tailscale serve` routes survive a Mac reboot; the helper does not (no
LaunchAgent yet), so run `make say-helper` again after a login.

## After that

Check on things (droplet):

```bash
systemctl list-timers 'studious-*'            # when each last ran and runs next
systemctl status studious-update.service      # failed means the last rollout or pull failed
journalctl -u studious-update -n 50 --no-pager
journalctl -u studious-backup -u studious-restore-test --since '7 days ago' --no-pager
docker ps; docker logs --tail 50 studious
df -h /srv; free -m
restic snapshots                              # after sourcing /etc/studious/restic.env
```

`systemctl --failed` is the one-line check. A timer that fails sends nothing
anywhere by itself; look weekly until you have decided on an alert.

An update waiting for a running job logs `new image ... is waiting` and exits
0, so it does not show as failed.

### Keeping it patched

- **Ubuntu packages** (Docker, the compose plugin, restic, OpenSSL, ...):
  unattended-upgrades, daily.
- **Reboots** for kernel and glibc fixes: automatic at 09:00 UTC when one is
  pending (`/etc/apt/apt.conf.d/52studious-reboot`). The time is the
  droplet's own zone, UTC by default (`timedatectl`). Everything comes back
  by itself; a job running at that moment is lost.
- **Tailscale**: its own updater (`tailscale set --auto-update`, step 4).
- **The image**: Dependabot PRs for Python, npm, Actions and the base images,
  and a weekly CI audit. Merging to `main` publishes, and the droplet pulls
  within 5 minutes.

```bash
cat /var/run/reboot-required.pkgs 2>/dev/null   # what wants a reboot, if anything
grep -i 'packages that will be upgraded' /var/log/unattended-upgrades/unattended-upgrades.log | tail
unattended-upgrade --dry-run --debug 2>&1 | head  # after editing the apt config
```

In that dry run's output, `ErrorText: ''` on a download line is not an error.

### Roll back by hand

The update timer would roll forward again to `:main`, so stop it first.

```bash
systemctl stop studious-update.timer
STUDIOUS_IMAGE=ghcr.io/zurt/studious:sha-<full-commit-sha> \
  docker compose -f /opt/studious/compose.yml up -d
```

The previous image is also kept locally as `ghcr.io/zurt/studious:previous`.
When `main` is fixed, `systemctl start studious-update.timer` resumes updates:
the next run sees the new `:main` and rolls it out.

### Restore from backup for real

Droplet (on a new droplet, do steps 2 to 4 and 7 first, and put the
passphrase from the password manager into `/etc/studious/restic-password`):

```bash
systemctl stop studious-update.timer studious-backup.timer
docker compose -f /opt/studious/compose.yml stop
mv /srv/studious/data /srv/studious/data.broken
set -a; . /etc/studious/restic.env; set +a
restic snapshots
restic restore latest --host studious --tag studious --target /
chown -R 10001:10001 /srv/studious/data
systemctl start studious-update.service
systemctl enable --now studious-update.timer studious-backup.timer studious-restore-test.timer
```

On a new droplet `provision.sh` has not enabled the timers; `enable --now` at
the end does, and on the old droplet it just starts them again.

`restic restore` puts files back at their original path, so `--target /`
recreates `/srv/studious/data`. A snapshot other than the latest: use its ID
from `restic snapshots`. One file or directory: add `--include
/srv/studious/data/store` and a scratch `--target`, then copy it over. Delete
`data.broken` once the app looks right.

### Other tasks

- Change a setting: edit `/etc/studious/env`, then, with no job running,
  `docker compose -f /opt/studious/compose.yml up -d --force-recreate`.
- Only `main` publishes images; there is no way to deploy a branch.
- Rebuild the droplet: step 2 and on, then restore (above) instead of step 10.
