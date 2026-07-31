# GCP Compute Engine Deployment

This application should initially run on one Compute Engine VM. The application has one SQLite journal, background market-data workers, and Server-Sent Events, so it is not suitable for multiple replicas or stateless Cloud Run deployment without an architecture change.

## Prerequisites

- A GCP project with billing enabled
- A GitHub repository containing this project
- Docker and Docker Compose installed on the VM

Set these values in your terminal before using the commands below:

```bash
export GCP_PROJECT_ID="your-project-id"
export GCP_REGION="your-region"
export GCP_ZONE="your-zone"
export GCP_INSTANCE="trader-helper-1"
```

Authenticate and select the project:

```bash
gcloud auth login
gcloud config set project "$GCP_PROJECT_ID"
gcloud services enable compute.googleapis.com
```

Create a firewall rule for the HTTPS reverse proxy. Do not expose port 5173 or TWS port 7496.

```bash
gcloud compute firewall-rules create trader-helper-web \
  --network=default \
  --direction=INGRESS \
  --action=ALLOW \
  --rules=tcp:80,tcp:443 \
  --source-ranges=0.0.0.0/0 \
  --target-tags=trader-helper-web
```

Reserve a static IP before creating the VM. Retaining the IP makes redeployments predictable and lets Caddy retain a valid HTTPS hostname.

```bash
gcloud compute addresses create trader-helper-ip --region="$GCP_REGION"
gcloud compute addresses describe trader-helper-ip \
  --region="$GCP_REGION" \
  --format='get(address)'
```

Create the VM. Use an `e2-micro` in `us-central1` for the lowest ongoing cost. It fits the Compute Engine Always Free allowance when the monthly limits apply; the free allowance covers one eligible `e2-micro` VM and up to 30 GB of standard persistent disk, not a guaranteed free external IPv4 address.

```bash
gcloud compute instances create "$GCP_INSTANCE" \
  --zone="$GCP_ZONE" \
  --machine-type=e2-micro \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --boot-disk-size=30GB \
  --boot-disk-type=pd-standard \
  --address=trader-helper-ip \
  --tags=trader-helper-web \
  --no-service-account \
  --no-scopes \
  --shielded-secure-boot \
  --shielded-vtpm \
  --shielded-integrity-monitoring
```

## HTTPS Hostname

For a permanent deployment, create a DNS `A` record for `PUBLIC_HOST` using the reserved address.

For a no-domain staging deployment, use a dynamic hostname from `nip.io`, such as `trader.35.254.11.193.nip.io` for IP `35.254.11.193`. Caddy can obtain a trusted HTTPS certificate for this hostname. It is appropriate for staging but should be replaced by a domain you control before relying on the service long-term.

Do not expose the password-protected app directly over plain HTTP at an IP address.

## VM Setup

Connect to the VM, clone the GitHub repository, and install Docker:

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose
sudo systemctl enable --now docker
```

On the VM, create a private `.env` file from `.env.example`. Set a unique, long `APP_PASSWORD` and the public hostname in `PUBLIC_HOST`. Do not commit this file. `MARKETDATA_TOKEN` is optional: without it, the QQQ Options Opportunity section provides strike, delta, and DTE guidance; with it, the server can select a delayed exact contract after applying liquidity and quote-quality gates. The application caches chains for 30 minutes and enforces a persistent 80-credit daily ceiling.

```bash
cp .env.example .env
chmod 600 .env
# Edit .env with the production password and public hostname.
sudo docker-compose -f compose.yaml -f compose.production.yaml up --build -d
```

Caddy receives ports 80 and 443, obtains and renews the TLS certificate for `PUBLIC_HOST`, and proxies traffic to the application over the private Docker network. The base Compose configuration keeps port 5173 bound to loopback only. Debian 12 ships the `docker-compose` command; on systems with Compose v2, use `docker compose` instead.

## Monitoring Alerts

Set `ALERT_WEBHOOK_URL` in the private `.env` file to an incoming Slack, Discord, or Google Chat webhook. The server checks every symbol once per minute and opens an incident only after three consecutive failures. It monitors missing candles, repeated provider errors, stale active-session data, and data-health blocks. Each incident is stored in SQLite, notified once, and sends a recovery notification when it clears.

The authenticated endpoint `/api/system-health` returns the current findings and recent incident history. Without a webhook URL, monitoring remains active and persistent, but no external message is sent.

Set `TRADE_ALERT_WEBHOOK_URL` for server-side trade lifecycle messages, or set both `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` for Telegram delivery. These alerts cover armed plans, entries, targets, stops, expiry, and invalidation. They continue while the browser is closed. The Provider Health tile shows whether a server alert channel is configured.

The SQLite journal is backed up to the persistent `trader-data` volume every 24 hours by default. Every backup runs `PRAGMA integrity_check`, and the most recent 14 verified copies are retained. `BACKUP_INTERVAL_SECONDS`, `BACKUP_RETENTION`, and `BACKTEST_MAX_CONCURRENCY` can be adjusted in `.env`; keep replay concurrency at `1` unless live request latency remains stable under load.

## Grafana Operations Dashboard

The Compose stack includes private Prometheus, Node Exporter, Loki, and Promtail services plus Grafana at `https://PUBLIC_HOST/grafana/`. Grafana has its own login; set `GRAFANA_ADMIN_USER` and `GRAFANA_ADMIN_PASSWORD` in the private `.env` file. Prometheus scrapes application and VM metrics every 30 seconds. Loki retains container logs for 14 days and exposes them in the operations dashboard. Caddy blocks public access to `/metrics`; only Grafana is exposed through HTTPS.

## Post-deploy Checks

```bash
sudo docker-compose -f compose.yaml -f compose.production.yaml ps
curl https://YOUR_PUBLIC_HOST/health
curl https://YOUR_PUBLIC_HOST/ready
```

Create a regular disk-snapshot policy before relying on the journal history. The Docker `trader-data` volume and Caddy certificate data live on the VM boot disk, so a VM replacement without a disk restore loses that state. Set a Cloud Billing budget alert before deployment; external IPv4 and network egress can still incur charges even when the VM fits the free-tier allowance.
