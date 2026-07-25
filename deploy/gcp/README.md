# GCP Compute Engine Deployment

This application should initially run on one Compute Engine VM. The application has one SQLite journal, background market-data workers, and Server-Sent Events, so it is not suitable for multiple replicas or stateless Cloud Run deployment without an architecture change.

## Prerequisites

- A GCP project with billing enabled
- A domain name with an `A` record ready to point to the VM's external IP
- A GitHub repository containing this project
- Docker installed on the VM

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

Reserve a static IP before creating the VM, then use that IP for the domain's `A` record.

```bash
gcloud compute addresses create trader-helper-ip --region="$GCP_REGION"
gcloud compute addresses describe trader-helper-ip \
  --region="$GCP_REGION" \
  --format='get(address)'
```

Create the VM. An `e2-small` is a sensible starting size for one user; scale after observing memory and CPU usage.

```bash
gcloud compute instances create "$GCP_INSTANCE" \
  --zone="$GCP_ZONE" \
  --machine-type=e2-small \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --boot-disk-size=30GB \
  --boot-disk-type=pd-balanced \
  --address=trader-helper-ip \
  --tags=trader-helper-web \
  --shielded-secure-boot \
  --shielded-vtpm \
  --shielded-integrity-monitoring
```

Create the DNS `A` record for `PUBLIC_HOST` using the reserved address. Wait for DNS to resolve, then connect to the VM and clone the GitHub repository.

On the VM, create a private `.env` file from `.env.example`. Set a unique, long `APP_PASSWORD` and the domain name in `PUBLIC_HOST`. Do not commit this file.

```bash
cp .env.example .env
chmod 600 .env
# Edit .env with the production password and domain name.
docker compose -f compose.yaml -f compose.production.yaml up --build -d
```

Caddy receives ports 80 and 443, obtains and renews the TLS certificate for `PUBLIC_HOST`, and proxies traffic to the application over the private Docker network. The base Compose configuration keeps port 5173 bound to loopback only.

## Post-deploy Checks

```bash
docker compose -f compose.yaml -f compose.production.yaml ps
curl -u "trader:YOUR_APP_PASSWORD" https://YOUR_DOMAIN/health
curl -u "trader:YOUR_APP_PASSWORD" https://YOUR_DOMAIN/ready
```

Create a regular disk-snapshot policy before relying on the journal history. The Docker `trader-data` volume and Caddy certificate data live on the VM boot disk, so a VM replacement without a disk restore loses that state.
