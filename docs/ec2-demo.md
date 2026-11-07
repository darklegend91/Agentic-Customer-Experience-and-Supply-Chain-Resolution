# EC2 investigation demo

This profile targets the selected 2-vCPU, 4-GiB x86_64 EC2 host. The frontend
stays on Streamlit Community Cloud. Only one API process runs on EC2, so Laya
and MiniLM are loaded once. It uses fictional development data and supports
the Investigate Tool and data explorer, not durable workflows or approvals.

## Image and resource choices

- Reuse the inspected, digest-pinned existing CPU-only dependency image instead
  of resolving and installing PyTorch on EC2. Its runtime dependencies are
  fixed by that base image; changes to requirements.txt need a rebuilt base.
- Add the English Laya checkpoint at a pinned revision. MiniLM is already
  cached in the base. Runtime model loading is offline.
- Download models before copying app code so code-only updates reuse that
  expensive layer. Download as appuser to avoid a subsequent ownership change
  to model files. Keep one English checkpoint; multilingual routing is outside
  this demo profile.
- Cap numerical-library thread settings at two, use one Uvicorn process, a
  3-GiB container limit, and bounded logs. Laya reported one PyTorch thread in
  the native check. The limit leaves room for Ubuntu, Docker, and the proxy.
- A 120-second request deadline is temporary batch-evaluation headroom; it
  does not optimize the existing sequential semantic evaluation loop.

## Build and verify before adding credentials

If using the prepared image archive, load it instead of building:

```bash
sudo docker load -i ~/agentic-ec2-demo-image.tar.gz
```

For a source-only installation, build from the project root. Skip this command
if you loaded the prepared image archive:

```bash
sudo docker build --platform linux/amd64 -f deploy/Dockerfile.ec2 -t agentic-support:ec2-demo .
```

Verify the loaded or built image:

```bash
sudo docker run --rm --network none --cpus 2 --memory 3g --memory-swap 3g \
  --entrypoint python agentic-support:ec2-demo scripts/verify_ec2_image.py
```

The verified Mac build used deploy/Dockerfile.ec2-local with the local-model
stage and a named laya-checkpoint context holding the five required files from
the same pinned snapshot. deploy/Dockerfile.ec2 is the standalone EC2 path: it
fetches those assets from Hugging Face and needs no named build context. The
archive contains the built image, so loading it skips either build path.

The offline check requires provider `laya`, no fallback, a normalized 384-value
MiniLM embedding, CPU-only PyTorch, successful FastAPI health, and a Laya-backed
response from POST /tickets/classify.
It reports the peak memory and timings for that host. It does not establish
classification accuracy, external database connectivity, or full request latency.

## Configure and start

```bash
cp deploy/.env.ec2.example .env.ec2
chmod 600 .env.ec2
nano .env.ec2
sudo docker compose -f deploy/docker-compose.ec2-demo.yml up -d --no-build
curl -fsS http://127.0.0.1:8000/health
sudo docker compose -f deploy/docker-compose.ec2-demo.yml logs --tail=50 api
sudo docker stats --no-stream
```

Use the existing development-only, read-only Neon connection and Milvus
credential. Do not reuse the published example workflow tokens. This demo
does not need workflow migrations or a workflow database.

The API port binds to loopback. Add the HTTPS proxy before connecting Streamlit.

Do not start the root docker-compose.yml on this small host: that configuration
also runs a worker and a frontend and can allocate separate model copies.

## HTTPS using the EC2 IP address

Create a private proxy environment file in the project root. Use the instance's
current public IP and generate a random token; keep this file outside Git.

```bash
python3 - <<'PY'
from pathlib import Path
import secrets
p = Path('.env.ec2-proxy')
if p.exists():
    raise SystemExit('Existing proxy settings retained; edit them deliberately.')
p.write_text('PUBLIC_API_IP=3.27.207.159\nDEMO_API_TOKEN=' + secrets.token_urlsafe(32) + '\n')
p.chmod(0o600)
PY
sudo docker compose -f deploy/docker-compose.ec2-demo.yml \
  -f deploy/docker-compose.ec2-https.yml up -d --no-build
curl -fsS https://3.27.207.159/health
```

Allow inbound TCP 80 and 443 in the EC2 security group. Keep port 8000 private.
Caddy obtains and renews a public Let's Encrypt IP certificate with the
`shortlived` ACME profile. Its persistent volume retains certificates and
renewal state. The health endpoint is public; all other paths require the
`X-Demo-Token` header. The proxy refuses to start with a missing or short token.
See the [Caddy TLS documentation](https://caddyserver.com/docs/caddyfile/directives/tls)
and [Let's Encrypt IP certificate announcement](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability).

The IP can change after stopping and starting the instance unless it is
reserved. If it changes, update both proxy and Streamlit settings.

## Connect the Streamlit frontend

Publish the frontend patch that sends `X-Demo-Token` only to the exact configured
HTTPS API URL and includes `schema_version` in chat investigation requests.
In Streamlit Community Cloud, open **Manage app → Settings → Secrets**. Merge
these four settings into the existing secrets, retaining the other keys:

```toml
API_BASE_URL = "https://3.27.207.159"
API_BASE_URL_LOCKED = "true"
ALLOW_REMOTE_API = "true"
DEMO_API_TOKEN = "the exact token from .env.ec2-proxy"
```

Use quoted strings for the two flags: Streamlit exports root-level string
secrets as environment variables. The remote-API flag enables the fixture
client; the token provides gateway authentication. The URL lock prevents
changing the destination in the sidebar. Save the secrets and select
**Investigate Tool**, then test API health and a sample investigation.

For this deployment, a private file containing the actual four values was
prepared at `~/Downloads/agentic-streamlit-ec2-secrets.toml` on the Mac. Do not
commit that file or replace unrelated existing Streamlit secrets with it.

## Check storage

```bash
sudo docker image inspect agentic-support:ec2-demo --format '{{.Size}}'
sudo docker system df
df -h /
```

The complete image must be larger than the old image because the old image
omitted the Laya weights. Keep the existing build cache for code updates;
rebuilding with --no-cache would repeat expensive downloads.
