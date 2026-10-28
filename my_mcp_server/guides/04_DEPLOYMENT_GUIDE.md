# Deploy the MCP server to AWS: ECR + ECS Fargate

So far the server runs on your laptop at `http://127.0.0.1:9001/mcp`. This guide puts it in AWS, so agents anywhere can use it:

- **ECR** (Elastic Container Registry) stores the server as a container image.
- **ECS Fargate** runs that image. You don't manage any servers: you say "run 1 copy of this image", and AWS does it.

```
 docker build ── push ─────────────▶ ECR (stores the image)
                                      │ pull
                                      ▼
 Agent ── HTTP ──▶ Load balancer ──▶ ECS Fargate task ──▶ public APIs
                   port 80,          server.py on port 9001
                   your IP only        ▲           │
                                       │ secrets   ▼ print()
                                Secrets Manager  CloudWatch Logs
```

| AWS piece | Its job here |
|---|---|
| **ECR repository** | Stores the image you build on your laptop. |
| **ECS cluster, service and task** | A *task* is one running copy of the container. The *service* keeps 1 task running, and replaces it if it stops. The *cluster* groups services. |
| **Task definition** | The recipe for a task: which image, how much CPU and memory, which port, which secrets. |
| **Application Load Balancer (ALB)** | A fixed public address. It forwards requests to the task, and calls `/health` to check the task is up. |
| **Secrets Manager** | Keeps `MCP_API_KEY` and `USERS_API_TOKEN`. ECS hands them to the container as environment variables when it starts. |
| **IAM execution role** | Lets ECS pull the image, read the two secrets and write logs, on your behalf. |
| **CloudWatch Logs** | Where `print()` output goes, including the `[tool] ...` lines. |
| **Security groups** | Firewalls. The load balancer accepts only your IP address; the task accepts only the load balancer. |

> **Cost:** the load balancer and the task are billed for every hour they run, even when idle. Delete everything when you're done ([Clean up](#clean-up)).

---

## What makes the server ready for a container

These changes are already in `mcp_server/`.

**1. `server.py` reads `HOST` from the environment.** On your laptop it listens on `127.0.0.1`, which accepts connections from the same computer only. Inside a container, "the same computer" is just the container, so the load balancer couldn't get in. The `Dockerfile` sets `HOST=0.0.0.0`, which means "accept connections on every network interface".

On `127.0.0.1`, the MCP SDK also checks each request's `Host` header, to block *DNS rebinding* attacks from web pages. On `0.0.0.0` it skips that check, so requests addressed to the load balancer's name get through. In AWS, the security groups and the API key protect the server instead.

**2. `server.py` reads `SERVER_URL` from the environment.** This is the address clients use. The server publishes it in its auth metadata (`/.well-known/oauth-protected-resource/mcp`). In AWS, that's the load balancer's address, so the task definition sets it.

**3. `server.py` has a `/health` route.** The load balancer calls it every few seconds. `ok` means the task is healthy; no answer means it isn't, and ECS replaces the task. It's a `custom_route`, which skips the API key check, because the load balancer has no key. That's also why it must never return anything secret.

**4. A `Dockerfile`** describes the image:

| Line | Why |
|---|---|
| `FROM python:3.13-slim` | Start from a small official Python image, the same version as `.python-version`. |
| `COPY --from=ghcr.io/astral-sh/uv:0.9.27 /uv /bin/uv` | Copy the `uv` tool in. A fixed version means the build gives the same result every time. |
| `COPY pyproject.toml uv.lock ./` and `RUN uv sync --locked ...` | Install the exact versions in `uv.lock`. Docker caches this step, so when only `server.py` changes, the next build skips it. |
| `COPY server.py ./` | Copy the code, and **only** the code. |
| `ENV ... HOST=0.0.0.0 PYTHONUNBUFFERED=1` | Listen on all interfaces, and send `print()` lines to the logs straight away instead of in batches. |
| `RUN useradd --system app` and `USER app` | Don't run as root. If someone ever broke in through the server, they'd get fewer rights. |
| `CMD ["python", "server.py"]` | What runs when the container starts. |

**5. A `.dockerignore`** keeps `.env`, `.venv` and `deploy/` out of the build. **The image must never contain your `.env`**: anyone who can pull an image can read every file in it. In AWS, the secrets come from Secrets Manager instead.

---

## Before you start

- An AWS account, and a user or role that can create IAM roles, ECR, ECS, load balancers and secrets.
- The [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html), signed in: `aws sts get-caller-identity` should print your account.
- [Docker Desktop](https://www.docker.com/products/docker-desktop/), running.
- A **bash** shell. On a Mac, type `bash` first (the default shell, zsh, splits variables differently). On Windows, use WSL.

Run every command from the `mcp_server/` folder, in **one terminal**: later steps use variables that earlier steps set. If you close the terminal, run Step 0 again, then look up the other values as shown in [Clean up](#clean-up).

## Step 0. Set up your terminal

```bash
cd mcp_server
mkdir -p deploy      # the JSON files written below go here. git ignores this folder

export AWS_REGION=ap-south-1   # Mumbai. Use the region closest to your users
export AWS_PAGER=""            # print results directly, instead of opening them in a pager
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGISTRY=$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
IMAGE=$REGISTRY/my-mcp-server
TAG=v1
echo "Deploying to account $ACCOUNT_ID in $AWS_REGION"
```

## Step 1. Build the image and test it on your laptop

Stop `uv run server.py` first if it's running, because both use port 9001.

```bash
docker build --platform linux/arm64 -t my-mcp-server .
docker run --rm -p 9001:9001 -e MCP_API_KEY=12345ABCDE -e USERS_API_TOKEN=test my-mcp-server
```

**Why `--platform linux/arm64`?** The image must match the CPU it runs on. We'll run the task on AWS Graviton (ARM64) CPUs, which cost less than x86. Apple Silicon Macs build ARM64 images natively; on an Intel or Windows machine Docker Desktop emulates ARM64, so the build is slower. (To use x86 instead, build with `--platform linux/amd64` and set `"cpuArchitecture": "X86_64"` in Step 7.)

In a second terminal, test it:

```bash
curl http://127.0.0.1:9001/health                                       # ok
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:9001/mcp  # 401: no key
```

Then run the LangChain agent as usual (`cd ../langchain_client && uv run agent.py`). It connects to `127.0.0.1:9001`, and Docker forwards that port to the container. The `[tool] ...` lines appear in the `docker run` terminal. Press `Ctrl+C` there to stop the container.

## Step 2. Push the image to ECR

```bash
aws ecr create-repository --repository-name my-mcp-server --image-scanning-configuration scanOnPush=true
aws ecr get-login-password | docker login --username AWS --password-stdin $REGISTRY
docker tag my-mcp-server $IMAGE:$TAG
docker push $IMAGE:$TAG
```

- `get-login-password | docker login` gives Docker a 12-hour password for your registry.
- `docker tag` gives the image its full name: `<registry>/<repository>:<tag>`.
- **Use a new tag for every version** (`v1`, `v2`…), not `latest`. Then ECS always knows exactly which image it runs, and rolling back means picking the previous version.
- `scanOnPush=true` makes ECR check the image for known vulnerabilities. See the results in the ECR console.

## Step 3. Store the secrets in Secrets Manager

```bash
MCP_KEY_ARN=$(aws secretsmanager create-secret --name my-mcp-server/MCP_API_KEY \
  --secret-string "$(openssl rand -hex 32)" --query ARN --output text)
USERS_TOKEN_ARN=$(aws secretsmanager create-secret --name my-mcp-server/USERS_API_TOKEN \
  --secret-string "demo-users-api-token" --query ARN --output text)
```

- The server is now on the internet, so its key is 64 random characters, not `12345ABCDE`. You'll read it back in Step 9.
- `USERS_API_TOKEN` is a demo value, because JSONPlaceholder ignores it. For a real API, store its real credential here.
- An ARN (Amazon Resource Name) is the unique ID of anything in AWS. The next steps refer to the secrets by ARN.

## Step 4. Create the task execution role

ECS needs permission to pull your image, read the two secrets and write logs. You give it that permission through an IAM **role** that ECS tasks may use:

```bash
cat > deploy/ecs-trust.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "ecs-tasks.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
EOF

cat > deploy/read-secrets.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "secretsmanager:GetSecretValue",
    "Resource": ["$MCP_KEY_ARN", "$USERS_TOKEN_ARN"]
  }]
}
EOF

aws iam create-role --role-name my-mcp-server-execution \
  --assume-role-policy-document file://deploy/ecs-trust.json
aws iam attach-role-policy --role-name my-mcp-server-execution \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
aws iam put-role-policy --role-name my-mcp-server-execution --policy-name read-mcp-secrets \
  --policy-document file://deploy/read-secrets.json
```

- `ecs-trust.json` says **who** may use the role: ECS tasks.
- `AmazonECSTaskExecutionRolePolicy` is AWS's ready-made policy for pulling images from ECR and writing logs.
- `read-secrets.json` allows reading **these two secrets only**. That's least privilege: a mistake can't expose your other secrets.

> ECS has two kinds of role. The **execution role** (this one) is what ECS needs to *start* your container. A **task role** is what your *code* may do in AWS, such as reading from S3. Our server calls no AWS APIs, so it doesn't need one.

## Step 5. Create the log group

```bash
aws logs create-log-group --log-group-name /ecs/my-mcp-server
aws logs put-retention-policy --log-group-name /ecs/my-mcp-server --retention-in-days 7
```

Everything the container prints goes here. Seven days of retention keeps storage costs down.

## Step 6. Create the load balancer

We use your account's **default VPC** (your private network in AWS), which has one public subnet in each availability zone. A load balancer needs subnets in at least two zones.

```bash
VPC_ID=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true \
  --query 'Vpcs[0].VpcId' --output text)
SUBNETS=$(aws ec2 describe-subnets --filters Name=vpc-id,Values=$VPC_ID Name=default-for-az,Values=true \
  --query 'Subnets[].SubnetId' --output text)
MY_IP=$(curl -s https://checkip.amazonaws.com)
echo "VPC $VPC_ID | subnets $SUBNETS | your IP $MY_IP"
```

If the VPC shows as `None`, your account has no default VPC. Create one with `aws ec2 create-default-vpc` and run the block again.

**Two security groups:** the load balancer accepts port 80 from **your IP only**, and the task accepts port 9001 from **the load balancer only**:

```bash
ALB_SG=$(aws ec2 create-security-group --group-name my-mcp-server-alb --vpc-id $VPC_ID \
  --description "MCP server load balancer" --query GroupId --output text)
aws ec2 authorize-security-group-ingress --group-id $ALB_SG --protocol tcp --port 80 --cidr $MY_IP/32

TASK_SG=$(aws ec2 create-security-group --group-name my-mcp-server-task --vpc-id $VPC_ID \
  --description "MCP server tasks" --query GroupId --output text)
aws ec2 authorize-security-group-ingress --group-id $TASK_SG --protocol tcp --port 9001 --source-group $ALB_SG
```

For a class, allow your office's IP range instead of `$MY_IP/32`. Avoid `0.0.0.0/0` (the whole internet) while the server uses plain HTTP: the API key would travel unencrypted.

**The load balancer, its target group, and a listener:**

```bash
ALB_ARN=$(aws elbv2 create-load-balancer --name my-mcp-server --subnets $SUBNETS --security-groups $ALB_SG \
  --query 'LoadBalancers[0].LoadBalancerArn' --output text)
ALB_DNS=$(aws elbv2 describe-load-balancers --load-balancer-arns $ALB_ARN \
  --query 'LoadBalancers[0].DNSName' --output text)

TG_ARN=$(aws elbv2 create-target-group --name my-mcp-server --protocol HTTP --port 9001 \
  --vpc-id $VPC_ID --target-type ip \
  --health-check-path /health --health-check-interval-seconds 10 --healthy-threshold-count 2 \
  --query 'TargetGroups[0].TargetGroupArn' --output text)

aws elbv2 create-listener --load-balancer-arn $ALB_ARN --protocol HTTP --port 80 \
  --default-actions Type=forward,TargetGroupArn=$TG_ARN
echo "The server will be at http://$ALB_DNS/mcp"
```

- The **target group** is the list of tasks that should get traffic. ECS adds and removes tasks itself. `--target-type ip` is required for Fargate, because every task gets its own IP address.
- The **health check** calls `/health` every 10 seconds. Two `ok` answers in a row mark a task healthy.
- The **listener** takes requests on port 80 and forwards them to the target group.

## Step 7. Register the task definition

The task definition is the recipe for running the container. This command writes it with your values filled in, then registers it with ECS:

```bash
cat > deploy/task-definition.json <<EOF
{
  "family": "my-mcp-server",
  "requiresCompatibilities": ["FARGATE"],
  "networkMode": "awsvpc",
  "cpu": "256",
  "memory": "512",
  "runtimePlatform": {"cpuArchitecture": "ARM64", "operatingSystemFamily": "LINUX"},
  "executionRoleArn": "arn:aws:iam::$ACCOUNT_ID:role/my-mcp-server-execution",
  "containerDefinitions": [
    {
      "name": "mcp-server",
      "image": "$IMAGE:$TAG",
      "essential": true,
      "portMappings": [{"containerPort": 9001, "protocol": "tcp"}],
      "environment": [
        {"name": "SERVER_URL", "value": "http://$ALB_DNS/mcp"}
      ],
      "secrets": [
        {"name": "MCP_API_KEY", "valueFrom": "$MCP_KEY_ARN"},
        {"name": "USERS_API_TOKEN", "valueFrom": "$USERS_TOKEN_ARN"}
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/my-mcp-server",
          "awslogs-region": "$AWS_REGION",
          "awslogs-stream-prefix": "mcp"
        }
      }
    }
  ]
}
EOF

aws ecs register-task-definition --cli-input-json file://deploy/task-definition.json \
  --query 'taskDefinition.revision' --output text
```

| Field | Meaning |
|---|---|
| `family` | The task definition's name. Each time you register it, the revision number goes up: `my-mcp-server:1`, `:2`… |
| `cpu`, `memory` | 0.25 vCPU and 512 MB, the smallest Fargate size. Plenty for this server. |
| `runtimePlatform` | Graviton (ARM64) CPUs, to match the image from Step 1. |
| `networkMode: awsvpc` | Each task gets its own network interface and IP address. Fargate requires it. |
| `environment` | Plain settings, visible in the console. |
| `secrets` | Secret settings. ECS reads them from Secrets Manager when the task **starts**, and passes them in as environment variables. `server.py` reads them with `os.environ`, just as it reads `.env` on your laptop. |
| `logConfiguration` | Send everything the container prints to the log group from Step 5. |

## Step 8. Create the cluster and the service

```bash
aws ecs create-cluster --cluster-name my-mcp-cluster

aws ecs create-service --cluster my-mcp-cluster --service-name my-mcp-server \
  --task-definition my-mcp-server --desired-count 1 --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$(echo $SUBNETS | tr ' ' ',')],securityGroups=[$TASK_SG],assignPublicIp=ENABLED}" \
  --load-balancers targetGroupArn=$TG_ARN,containerName=mcp-server,containerPort=9001

aws ecs wait services-stable --cluster my-mcp-cluster --services my-mcp-server && echo "The service is up"
```

- `--desired-count 1`: keep exactly one task running. Why not more? See [Before production](#before-production).
- `assignPublicIp=ENABLED`: the task needs the internet to pull its image, read its secrets and call the public weather, store and users APIs. In the default VPC's public subnets, that takes a public IP. Nobody can use that IP to reach the server, though: the task's security group only lets the load balancer in.
- `--load-balancers`: register the task's port 9001 in the target group from Step 6.
- The `wait` takes a few minutes. ECS pulls the image, starts the task, and waits for two good health checks.

## Step 9. Test it and connect an agent

```bash
curl http://$ALB_DNS/health                                           # ok
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://$ALB_DNS/mcp  # 401: no key

MCP_KEY=$(aws secretsmanager get-secret-value --secret-id my-mcp-server/MCP_API_KEY \
  --query SecretString --output text)
curl -s -X POST http://$ALB_DNS/mcp \
  -H "Authorization: Bearer $MCP_KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'
```

The last command should print `data: {"jsonrpc":"2.0","id":1,"result":{...` with `"serverInfo":{"name":"my-mcp-server"...`. The server is running in AWS.

**Connect the LangChain or LangGraph agent:**

1. Print the URL and the key: `echo "http://$ALB_DNS/mcp"; echo "$MCP_KEY"`
2. In the client's `agent.py`, set `MCP_URL` to that URL. In its `.env`, set `MCP_API_KEY` to that key.
3. Run the agent: `uv run agent.py`.
4. In another terminal, watch the server's `[tool] ...` lines arrive in CloudWatch: `aws logs tail /ecs/my-mcp-server --follow`

Change `MCP_URL` and `MCP_API_KEY` back when you go back to the local server.

---

## Deploy a new version

After you change `server.py`, build and push a new tag, register a new task definition revision, and point the service at it:

```bash
TAG=v2
docker build --platform linux/arm64 -t my-mcp-server .
docker tag my-mcp-server $IMAGE:$TAG
docker push $IMAGE:$TAG
# Now run the "cat > deploy/task-definition.json" command from Step 7 again: it uses $TAG.
aws ecs register-task-definition --cli-input-json file://deploy/task-definition.json \
  --query 'taskDefinition.revision' --output text
aws ecs update-service --cluster my-mcp-cluster --service my-mcp-server --task-definition my-mcp-server
aws ecs wait services-stable --cluster my-mcp-cluster --services my-mcp-server && echo "$TAG is live"
```

ECS starts a new task, waits until it's healthy, then stops the old one, so the server stays available. A client in the middle of an MCP session may need to reconnect, because its session lived in the old task. (Our LangChain and LangGraph agents open a new session for every tool call, so they don't notice.)

- **Roll back:** `aws ecs update-service --cluster my-mcp-cluster --service my-mcp-server --task-definition my-mcp-server:1`
- **Changed a secret?** Tasks read secrets only when they start, so start fresh ones: `aws ecs update-service --cluster my-mcp-cluster --service my-mcp-server --force-new-deployment`

## Clean up

Delete everything, so nothing keeps billing. If you've closed the terminal since Step 8, run Step 0 again, then these lines to find the IDs:

```bash
ALB_ARN=$(aws elbv2 describe-load-balancers --names my-mcp-server --query 'LoadBalancers[0].LoadBalancerArn' --output text)
TG_ARN=$(aws elbv2 describe-target-groups --names my-mcp-server --query 'TargetGroups[0].TargetGroupArn' --output text)
ALB_SG=$(aws ec2 describe-security-groups --filters Name=group-name,Values=my-mcp-server-alb --query 'SecurityGroups[0].GroupId' --output text)
TASK_SG=$(aws ec2 describe-security-groups --filters Name=group-name,Values=my-mcp-server-task --query 'SecurityGroups[0].GroupId' --output text)
```

Then delete, in this order:

```bash
aws ecs delete-service --cluster my-mcp-cluster --service my-mcp-server --force
aws ecs wait services-inactive --cluster my-mcp-cluster --services my-mcp-server
aws ecs delete-cluster --cluster my-mcp-cluster

aws elbv2 delete-load-balancer --load-balancer-arn $ALB_ARN
aws elbv2 wait load-balancers-deleted --load-balancer-arns $ALB_ARN
aws elbv2 delete-target-group --target-group-arn $TG_ARN
aws ec2 delete-security-group --group-id $TASK_SG   # "DependencyViolation"? Wait a minute and run it again
aws ec2 delete-security-group --group-id $ALB_SG

aws secretsmanager delete-secret --secret-id my-mcp-server/MCP_API_KEY --force-delete-without-recovery
aws secretsmanager delete-secret --secret-id my-mcp-server/USERS_API_TOKEN --force-delete-without-recovery
aws logs delete-log-group --log-group-name /ecs/my-mcp-server
aws iam delete-role-policy --role-name my-mcp-server-execution --policy-name read-mcp-secrets
aws iam detach-role-policy --role-name my-mcp-server-execution \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
aws iam delete-role --role-name my-mcp-server-execution
aws ecr delete-repository --repository-name my-mcp-server --force
rm -rf deploy
```

Old task definition revisions cost nothing, so you can leave them.

---

## Before production

This guide gets the server running. Before real users rely on it:

- **HTTPS.** Get a domain name and a free certificate from AWS Certificate Manager (ACM). Add an HTTPS listener on port 443, and redirect port 80 to it. Then set `SERVER_URL` to `https://mcp.yourdomain.com/mcp`. Without HTTPS, anyone on the network path can read the API key.
- **Private subnets.** Run tasks without public IPs, in private subnets. They then reach ECR, Secrets Manager and CloudWatch through a NAT gateway or VPC endpoints.
- **More than one task.** By default, the MCP SDK keeps each client's *session* in the memory of the task that started it. With two tasks, a client's next request may reach the other task, and get `Session not found`. Our server doesn't need sessions (it never sends messages to the client on its own), so run it **stateless**: `mcp.run(transport="streamable-http", ..., stateless_http=True)`. Then any task can answer any request, and you can add ECS auto scaling.
- **OAuth instead of a shared key.** See [03_OAUTH_GUIDE.md](03_OAUTH_GUIDE.md).
- **Automate it.** Write this setup as code (AWS CDK, Terraform or CloudFormation) instead of typing CLI commands. Build and deploy from CI, for example GitHub Actions signing in to AWS with OIDC, so there are no long-lived AWS keys in CI.

---

## Troubleshooting

To see why a task stopped:

```bash
aws ecs describe-services --cluster my-mcp-cluster --services my-mcp-server --query 'services[0].events[:5].message'
aws ecs describe-tasks --cluster my-mcp-cluster --query 'tasks[0].[stoppedReason,containers[0].reason]' \
  --tasks $(aws ecs list-tasks --cluster my-mcp-cluster --desired-status STOPPED --query 'taskArns[0]' --output text)
aws logs tail /ecs/my-mcp-server --since 30m
```

In the console: **ECS → Clusters → my-mcp-cluster → Services → my-mcp-server**, then the **Events**, **Tasks** and **Logs** tabs.

| Symptom | Likely cause | Fix |
|---|---|---|
| Task stops with `exec format error` | The image was built for a different CPU than the task's | Build with `--platform linux/arm64`, to match `"cpuArchitecture": "ARM64"` |
| `CannotPullContainerError`, or `ResourceInitializationError: unable to pull secrets or registry auth` | The task can't reach ECR or Secrets Manager | Check `assignPublicIp=ENABLED` and that the subnets are public. Check the image name and tag in the task definition |
| `AccessDeniedException ... secretsmanager:GetSecretValue` | The execution role may not read that secret | Check the ARNs in `deploy/read-secrets.json` (Step 4) |
| Logs show `KeyError: 'MCP_API_KEY'` | The secret isn't passed to the container | Check the `secrets` block of the task definition |
| Tasks keep starting and stopping; targets `unhealthy` | The health check fails | Check the path is `/health`, and that the logs say `Uvicorn running on http://0.0.0.0:9001` |
| `503 Service Temporarily Unavailable` from the load balancer | No healthy task yet | Wait for `services-stable`. Check `aws elbv2 describe-target-health --target-group-arn $TG_ARN` |
| `curl` to the load balancer hangs, then times out | Your IP address isn't allowed in (did it change?) | Run the `authorize-security-group-ingress` command for port 80 again, with your new IP |
| `401 Unauthorized` | Wrong or missing key | Read the key again (Step 9). Send `Authorization: Bearer <key>` |
| `create-service` fails: `Unable to assume the service linked role` | A brand-new account hasn't used ECS before | `aws iam create-service-linked-role --aws-service-name ecs.amazonaws.com`, then try again |
| `Session not found` with more than one task | Each task keeps its own sessions | Use `stateless_http=True` (see [Before production](#before-production)), or keep 1 task |
| `create-load-balancer` says the subnets are invalid, on a Mac | zsh didn't split `$SUBNETS` into separate words | Run the commands in `bash` |
