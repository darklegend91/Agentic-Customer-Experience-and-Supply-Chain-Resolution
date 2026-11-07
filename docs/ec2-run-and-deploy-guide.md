# Run and deploy the EC2 investigation demo

This guide covers local startup, copying source to the EC2 host, building the API image there, and connecting the existing Streamlit frontend. It describes the **synthetic investigation demo** used in this project; it is not a production customer-support deployment.

## EC2 details captured in this chat

The instance shell reported Ubuntu user `ubuntu`, `x86_64`, 2 CPUs, 3.7 GiB RAM, and a 24 GiB root filesystem. Docker and Docker Compose were installed and `docker run hello-world` succeeded. The commands used AWS region `ap-southeast-2`, instance ID `i-072934e47193d3e22`, and public IP `3.27.207.159` at that time. Public IPs can change after a stop/start. The exact EC2 instance type was not confirmed in the shell output; check it in **AWS Console → EC2 → Instances → select the instance → Instance type**.

The API runs as one Docker container on EC2. The Streamlit frontend remains on Streamlit Community Cloud. This demo uses one API process so Laya and MiniLM are loaded once. Do not start the root `docker-compose.yml` on this small instance: that profile also starts a worker and UI, each of which can consume additional memory.

## Run locally

From the repository root, install the dependencies into the project virtual environment if needed:

```bash
python3 -m venv .venv-multi
./.venv-multi/bin/python -m pip install --upgrade pip
./.venv-multi/bin/python -m pip install -r requirements.txt
```

Create the ignored `.env` from `.env.example`, then configure development-only Neon and Milvus values and the Laya endpoint. Never commit `.env` or paste credentials into source or chat. Start the API and Streamlit in separate terminals:

```bash
APP_ENV=local EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 \
  ./.venv-multi/bin/python -m uvicorn backend.app.main:app \
  --host 127.0.0.1 --port 8000
```

```bash
./.venv-multi/bin/python -m streamlit run frontend/app.py \
  --server.address 127.0.0.1 --server.port 8501
```

Open `http://127.0.0.1:8501`. Check the API with `curl -fsS http://127.0.0.1:8000/health`. `APP_ENV` must be explicitly set to `local`, `dev`, or `development`; an empty value or production environment is rejected by the local-development guard.

The legacy Render blueprint no longer sets `APP_ENV=local`. If that value is still present in the Render dashboard, remove it there too; a hosted Render service must not identify itself as local development to enable fixture routes.

## Connect to EC2 from macOS

Use the same macOS Terminal session in which this worked:

```bash
ssh -i ~/Downloads/agentic-support-server-key-pair.pem ubuntu@3.27.207.159 'whoami'
```

The expected output is `ubuntu`. The earlier `Load key ... Operation not permitted` message was a local macOS file-access error: `chmod 400` controls Unix permissions but cannot grant an app access to the Downloads folder. If it returns, use Terminal.app with Downloads access, or copy the key from the working Terminal into `~/.ssh` and use that copy:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
cp ~/Downloads/agentic-support-server-key-pair.pem ~/.ssh/agentic-support-server-key-pair.pem
chmod 400 ~/.ssh/agentic-support-server-key-pair.pem
ssh -i ~/.ssh/agentic-support-server-key-pair.pem ubuntu@3.27.207.159 'whoami'
```

Run `rsync` from the repository root in that same working Terminal. This sends source changes without sending private environment files, model caches, or local data. It intentionally has no `--delete` flag, so existing server files are not removed:

```bash
rsync -avz --progress \
  -e 'ssh -i ~/.ssh/agentic-support-server-key-pair.pem' \
  --exclude='/.git/' \
  --exclude='/.env' --exclude='/.env.*' \
  --exclude='/deploy/.env.api' --exclude='/deploy/.env.ec2' \
  --exclude='/deploy/.env.ec2-proxy' \
  --exclude='/.venv*/' --exclude='**/.venv*/' \
  --exclude='data/raw/' --exclude='data/synthetic/' \
  --exclude='models/' --exclude='passwords/' \
  --exclude='*.pem' --exclude='secrets.toml' \
  --exclude='~$*' \
  --exclude='.streamlit/secrets.toml' \
  ./ ubuntu@3.27.207.159:/home/ubuntu/agentic-support/
```

If your current public IP has changed, replace `3.27.207.159` in the commands with the current value shown on the EC2 instance page. The SSH security-group rule must allow port 22 from your current public IP.

## Build and start the API on EC2

Connect to the instance and move into the project directory:

```bash
ssh -i ~/.ssh/agentic-support-server-key-pair.pem ubuntu@3.27.207.159
cd ~/agentic-support
```

Create the private runtime file from the checked-in example, then edit it. Use development-only credentials. `DATABASE_URL` must be the read-only development fixture connection; `MILVUS_URI` and `MILVUS_TOKEN` must point to the development policy collection. Keep LLM and Langfuse tracing disabled for this demo. Do not reuse tokens copied from old reports or example files.

```bash
cp deploy/.env.ec2.example .env.ec2
chmod 600 .env.ec2
nano .env.ec2
```

Build on EC2 from the source instead of copying a large Docker image archive. `deploy/Dockerfile.ec2` starts from the pinned CPU-only dependency image and downloads the pinned English Laya checkpoint in a cached layer. Later source-only updates can reuse the image layers:

```bash
sudo docker build --platform linux/amd64 \
  -f deploy/Dockerfile.ec2 -t agentic-support:ec2-demo .
```

Run the offline image check before starting the API:

```bash
sudo docker run --rm --network none --cpus 2 --memory 3g --memory-swap 3g \
  --entrypoint python agentic-support:ec2-demo scripts/verify_ec2_image.py
```

Start the one-container demo and inspect its health/logs:

```bash
sudo docker compose -f deploy/docker-compose.ec2-demo.yml up -d --no-build
curl -fsS http://127.0.0.1:8000/health
sudo docker compose -f deploy/docker-compose.ec2-demo.yml ps
sudo docker compose -f deploy/docker-compose.ec2-demo.yml logs --tail=100 api
sudo docker stats --no-stream
```

Port 8000 binds to loopback on the EC2 host. Do not open port 8000 in the AWS security group.

## Add HTTPS and connect Streamlit Cloud

The HTTPS proxy is Caddy. It exposes ports 80 and 443, obtains an IP certificate, and requires `X-Demo-Token` for application paths; `/health` remains public. Create `.env.ec2-proxy` on EC2 with the current public IP and a random token of at least 32 characters. Keep this file private and set mode `600`. Then start both Compose files:

```bash
sudo docker compose \
  -f deploy/docker-compose.ec2-demo.yml \
  -f deploy/docker-compose.ec2-https.yml up -d --no-build
curl -fsS https://3.27.207.159/health
```

In the EC2 security group, allow TCP 80 and 443 from the intended clients, and keep TCP 8000 closed. If you want the API reachable only by Streamlit Cloud, the current Caddy token is the access control for non-health routes; keep it private.

In Streamlit Community Cloud, open **Manage app → Settings → Secrets**. Merge these values into the existing secrets without replacing unrelated entries:

```toml
API_BASE_URL = "https://3.27.207.159"
API_BASE_URL_LOCKED = "true"
ALLOW_REMOTE_API = "true"
DEMO_API_TOKEN = "the same random token configured in .env.ec2-proxy"
```

Use the current public IP if it differs. Save the settings, open the **Investigation workbench**, check API health, then run a sample investigation. A Laya-backed result should identify provider `laya`; `tfidf_fallback` means the model did not answer and the request requires human review.

## Updating after a code change

From the Mac repository root, run the same `rsync` command above. Then SSH to EC2 and rebuild/restart:

```bash
cd ~/agentic-support
sudo docker build --platform linux/amd64 \
  -f deploy/Dockerfile.ec2 -t agentic-support:ec2-demo .
sudo docker compose \
  -f deploy/docker-compose.ec2-demo.yml \
  -f deploy/docker-compose.ec2-https.yml up -d --no-build
sudo docker compose -f deploy/docker-compose.ec2-demo.yml logs --tail=100 api
```

Keep the Docker build cache; avoid `--no-cache`, which repeats the heavyweight model download. Check storage and disk headroom with:

```bash
sudo docker system df
df -h /
```

## Troubleshooting

- **`Load key ... Operation not permitted`:** macOS prevented this shell app from reading the key in Downloads. Use the working Terminal session or move the key to `~/.ssh`; `chmod` alone does not change macOS privacy access.
- **`Permission denied (publickey)`:** confirm the key pair selected at EC2 launch matches this file, use username `ubuntu` for the Ubuntu AMI, and verify the current public IP and port 22 security-group rule. In this chat, `whoami` returned `ubuntu`, so SSH authentication succeeded in that Terminal session.
- **`rsync` EOF / child exited 255`:** rsync could not establish SSH; fix the key-load/authentication error first. The successful `whoami` command confirms the remote login path works.
- **API health is not ready:** allow model startup time, then inspect the API logs and `docker stats`; the container health check allows a 180-second startup period.
- **Classification shows `tfidf_fallback`:** confirm the image verification step reports provider `laya` and check container logs for model-load or inference errors.
- **IP changed:** update `.env.ec2-proxy`, the Streamlit `API_BASE_URL`, and the security-group rules. An Elastic IP prevents changes to the instance's public address.

For the full rationale behind the image, model-cache, and memory choices, see [the EC2 demo notes](ec2-demo.md). The complete workflow deployment is a different Compose profile documented in [the private demo runbook](deployment.md); it requires more resources and is not the configuration described here.
