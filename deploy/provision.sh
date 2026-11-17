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
# end. Nothing is started that needs a secret: the update timer is enabled but
# not started, so the first rollout waits until /etc/studious/env is filled in.
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
  studious-restore-test.sh systemd/studious-update.service systemd/studious-update.timer; do
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

# Security updates apply by themselves; a reboot is left to the owner.
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

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

# ---- systemd -----------------------------------------------------------------
log "installing systemd units"
for u in "$SRC"/systemd/*.service "$SRC"/systemd/*.timer; do
  install -m 0644 "$u" "$UNIT_DIR/$(basename "$u")"
done
systemctl daemon-reload
# Enabled, not started: each timer is started by hand in docs/deploy.md once
# what it needs exists (env file, restic repository). They start on their own
# after a reboot.
systemctl enable studious-update.timer studious-backup.timer studious-restore-test.timer >/dev/null

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

  1. Join the tailnet and turn on Tailscale SSH:
       tailscale up --ssh
     then, from the Mac, check:  ssh root@<droplet-tailnet-name>
  2. Fill in the secrets:
       \$EDITOR $ETC_DIR/env           (ANTHROPIC_API_KEY)
       \$EDITOR $ETC_DIR/restic.env    (bucket name and B2 key)
  3. First rollout:  systemctl start studious-update.service
     then:           systemctl start studious-update.timer
  4. HTTPS on the tailnet:  tailscale serve --bg 8000
  5. Backups:  restic init (with the variables from restic.env, see docs/deploy.md),
     systemctl start studious-backup.timer studious-restore-test.timer
  6. Once Tailscale SSH works from the Mac:  ./provision.sh --lock-down
EOF
if [ "${new_password:-}" = "yes" ]; then
  echo
  echo "The restic passphrase was just generated. Copy it into the password manager now:"
  echo "  cat $ETC_DIR/restic-password"
fi
