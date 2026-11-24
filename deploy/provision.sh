#!/usr/bin/env bash
# Set up a fresh Ubuntu LTS droplet (24.04) to run Studious. Run once as root
# from a copy of this directory (docs/deploy.md, step 3). Safe to run again: it
# installs what is missing, refreshes the scripts, compose file and units, and
# never overwrites /etc/studious/env, restic.env or the restic password.
#
#   sudo ./provision.sh              provision
#   sudo ./provision.sh --lock-down  remove public SSH (after Tailscale SSH works)
#
# What it does NOT do: join the tailnet. `tailscale up` needs a browser login or
# a key, and no key is baked into anything. It prints the manual commands at the
# end. Nothing is started or enabled that needs a secret or a repository: each
# timer is enabled by hand (`systemctl enable --now`) at the step of
# docs/deploy.md where what it needs exists. An enabled timer starts on its own
# at boot, and the automatic reboot below can come before `restic init`.
#
# Network. ufw denies all incoming, allows everything arriving on tailscale0
# and Tailscale's own UDP 41641, and allows public SSH until --lock-down.
# Docker's published ports are NAT rules that bypass ufw, so the firewall alone
# would not protect the container. That is why deploy/compose.yml binds the
# port to 127.0.0.1 only: do not change it to a bare "8000:8000". Add the
# DigitalOcean cloud firewall as a second layer (docs/deploy.md, step 5).
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR=/usr/local/lib/studious
APP_DIR=/opt/studious
ETC_DIR=/etc/studious
SBIN_DIR=/usr/local/sbin
RO_USER=studious-ro
DATA_DIR=/srv/studious/data
UNIT_DIR=/etc/systemd/system
LOCKED_MARKER="$ETC_DIR/locked-down"
CONTAINER_UID=10001

log() { echo "provision: $*"; }
fail() { echo "provision: FAIL: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "run as root"

# --lock-down: close public SSH. Separate on purpose, run only after you have
# opened an SSH session over Tailscale from the Mac and seen it work.
lock_down() {
  command -v tailscale >/dev/null || fail "tailscale is not installed; run ./provision.sh first"
  tailscale ip -4 >/dev/null 2>&1 || fail "this droplet is not on a tailnet yet (tailscale up --ssh)"
  log "removing public SSH (22/tcp). Keep your Tailscale SSH session open until you have checked a new one."
  ufw delete allow 22/tcp >/dev/null 2>&1 || true
  ufw delete allow OpenSSH >/dev/null 2>&1 || true
  mkdir -p "$ETC_DIR"
  touch "$LOCKED_MARKER"
  ufw status verbose
  log "done. Public SSH is closed; also remove it from the DigitalOcean cloud firewall if you added it."
}

case "${1:-}" in
  "") ;;
  --lock-down)
    lock_down
    exit 0
    ;;
  *) fail "usage: provision.sh [--lock-down]" ;;
esac

for f in compose.yml env.example restic.env.example studious-update.sh studious-backup.sh \
  studious-restore-test.sh studious-status.sh studious-logs.sh studious-stats.sh sudoers-studious-ro \
  systemd/studious-update.service systemd/studious-update.timer; do
  [ -f "$SRC/$f" ] || fail "$SRC/$f is missing: run this from a full copy of the repo's deploy/ directory"
done

export DEBIAN_FRONTEND=noninteractive
# shellcheck source=/dev/null
. /etc/os-release
[ "${ID:-}" = "ubuntu" ] || fail "written for Ubuntu (this is ${ID:-unknown})"
codename="${VERSION_CODENAME:?no VERSION_CODENAME in /etc/os-release}"

# ---- Packages ----------------------------------------------------------------
log "installing packages from the Ubuntu archive"
apt-get update -qq
# docker.io and the compose plugin are the distribution's builds, patched by
# unattended-upgrades with the rest of the system.
apt-get install -y -qq docker.io docker-compose-v2 restic unattended-upgrades \
  ufw curl ca-certificates gnupg util-linux python3
docker compose version >/dev/null 2>&1 || fail "docker compose is not available: is docker-compose-v2 in this release's archive?"

# Tailscale from its own signed apt repository: the key goes to /usr/share/keyrings
# and the repo line names it with signed-by, so only that key can sign it.
if ! command -v tailscale >/dev/null; then
  log "adding Tailscale's apt repository"
  install -d -m 0755 /usr/share/keyrings
  curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/${codename}.noarmor.gpg" \
    -o /usr/share/keyrings/tailscale-archive-keyring.gpg
  echo "deb [signed-by=/usr/share/keyrings/tailscale-archive-keyring.gpg] https://pkgs.tailscale.com/stable/ubuntu ${codename} main" \
    >/etc/apt/sources.list.d/tailscale.list
  apt-get update -qq
  apt-get install -y -qq tailscale
fi
systemctl enable --now tailscaled >/dev/null 2>&1 || true
systemctl enable --now docker >/dev/null 2>&1 || true

# Security updates apply by themselves. Kernel and glibc fixes need a reboot,
# done automatically at 09:00 droplet time (UTC: 1am Pacific in winter, 2am in
# summer), only when /var/run/reboot-required exists. That is after the 03:30
# backup and the Sunday 05:00 restore test. The container (restart:
# unless-stopped), `tailscale serve --bg` and the enabled timers come back by
# themselves; a job running at that moment is lost. A file of our own, so the
# package's 50unattended-upgrades stays untouched; later files win.
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
cat >/etc/apt/apt.conf.d/52studious-reboot <<'EOF'
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "09:00";
EOF

# unattended-upgrades only takes Ubuntu's own origins, not Tailscale's apt
# repository, so Tailscale updates itself. On a first run, before `tailscale
# up`, this may not apply, which is why the steps printed at the end repeat it.
tailscale set --auto-update >/dev/null 2>&1 || log "tailscale set --auto-update did not apply yet; run it after tailscale up"

# ---- Swap ----------------------------------------------------------------------
# 1 GB of RAM: a pull or a restic run can spike. The container itself is kept out
# of swap by memswap_limit in compose.yml.
if [ "$(swapon --show --noheadings | wc -l)" -eq 0 ]; then
  log "creating a 1 GB swap file"
  fallocate -l 1G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
fi

# ---- Directories and files ------------------------------------------------------
log "creating $DATA_DIR and $ETC_DIR"
install -d -m 0750 -o "$CONTAINER_UID" -g "$CONTAINER_UID" "$DATA_DIR"
# A re-run must not walk a library of page images, so chown only the top level.
chown "$CONTAINER_UID:$CONTAINER_UID" "$DATA_DIR"
install -d -m 0700 "$ETC_DIR"

# Config files are only created when absent. They hold secrets: never overwrite.
[ -f "$ETC_DIR/env" ] || install -m 0600 "$SRC/env.example" "$ETC_DIR/env"
[ -f "$ETC_DIR/restic.env" ] || install -m 0600 "$SRC/restic.env.example" "$ETC_DIR/restic.env"
if [ ! -f "$ETC_DIR/restic-password" ]; then
  log "generating the restic passphrase in $ETC_DIR/restic-password"
  (umask 077 && head -c 48 /dev/urandom | base64 -w0 >"$ETC_DIR/restic-password")
  new_password=yes
fi

log "installing scripts to $LIB_DIR and the compose file to $APP_DIR"
install -d -m 0755 "$LIB_DIR" "$APP_DIR"
for s in studious-update.sh studious-backup.sh studious-restore-test.sh; do
  install -m 0755 "$SRC/$s" "$LIB_DIR/$s"
done
install -m 0644 "$SRC/compose.yml" "$APP_DIR/compose.yml"

# ---- Read-only user -----------------------------------------------------------
# $RO_USER troubleshoots over Tailscale SSH (docs/deploy.md) and is the account
# `make pull-data` copies the data with. It reads the journal and, through a
# group, the data directory. It is not in docker (root-equivalent), sudo or adm.
# What it may run as root is a few fixed scripts: sudoers-studious-ro.
log "setting up the read-only user $RO_USER"
data_group="$(getent group "$CONTAINER_UID" | cut -d: -f1 || true)"
if [ -z "$data_group" ]; then
  groupadd --gid "$CONTAINER_UID" studious-data
  data_group=studious-data
fi
if ! id "$RO_USER" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash --user-group "$RO_USER"
fi
# No password: Tailscale SSH logs in without keys or passwords.
passwd -l "$RO_USER" >/dev/null
usermod -aG "systemd-journal,$data_group" "$RO_USER"
for g in docker sudo adm; do
  gpasswd -d "$RO_USER" "$g" >/dev/null 2>&1 || true
done

# The directory is 0750 container:container, so the group sees in only when the
# files inside are group-readable. The app writes 0644 now, but older audio
# clips are 0600 (tempfile.mkstemp). This is stat only, a few thousand files,
# unlike the recursive chown above that a re-run must avoid.
find "$DATA_DIR" -type f ! -perm -g=r -exec chmod g+r {} +
find "$DATA_DIR" -type d ! -perm -g=rx -exec chmod g+rx {} +

log "installing the read-only wrappers to $SBIN_DIR and the sudoers file"
for w in studious-status studious-logs studious-stats; do
  install -m 0755 -o root -g root "$SRC/$w.sh" "$SBIN_DIR/$w"
done
# A bad sudoers file can lock sudo out, so check it before it is in place.
visudo -cf "$SRC/sudoers-studious-ro" >/dev/null || fail "$SRC/sudoers-studious-ro does not pass visudo -c"
install -m 0440 -o root -g root "$SRC/sudoers-studious-ro" /etc/sudoers.d/studious-ro

# ---- systemd -----------------------------------------------------------------
log "installing systemd units"
for u in "$SRC"/systemd/*.service "$SRC"/systemd/*.timer; do
  install -m 0644 "$u" "$UNIT_DIR/$(basename "$u")"
done
systemctl daemon-reload
# Not enabled here: docs/deploy.md enables each timer with `systemctl enable
# --now` once what it needs exists (step 8: the env file; step 11: the restic
# repository). Enabled early, a reboot started them before then, and the first
# droplet logged a failed backup and restore test before `restic init`
# (2026-11-22). A re-run leaves timers that are already enabled as they are.

# ---- Firewall ----------------------------------------------------------------
log "configuring ufw"
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow in on tailscale0 >/dev/null
ufw allow 41641/udp >/dev/null
if [ -f "$LOCKED_MARKER" ]; then
  log "public SSH stays closed ($LOCKED_MARKER exists)"
else
  ufw allow 22/tcp >/dev/null
fi
ufw --force enable >/dev/null
ufw status verbose

cat <<EOF

provision: done. Next, by hand (docs/deploy.md has the detail):

  1. Join the tailnet, turn on Tailscale SSH and Tailscale's own updates:
       tailscale up --ssh
       tailscale set --auto-update
     then, from the Mac, check:  ssh root@<droplet-tailnet-name>
  2. Once Tailscale SSH works from the Mac:  ./provision.sh --lock-down
  3. Fill in the secrets:
       \$EDITOR $ETC_DIR/env           (ANTHROPIC_API_KEY)
       \$EDITOR $ETC_DIR/restic.env    (bucket name and B2 key)
  4. First rollout:  systemctl start studious-update.service
     then:           systemctl enable --now studious-update.timer
  5. HTTPS on the tailnet:  tailscale serve --bg 8000
  6. Backups:  restic init (with the variables from restic.env, see docs/deploy.md),
     systemctl enable --now studious-backup.timer studious-restore-test.timer
EOF
if [ "${new_password:-}" = "yes" ]; then
  echo
  echo "The restic passphrase was just generated. Copy it into the password manager now:"
  echo "  cat $ETC_DIR/restic-password"
fi
