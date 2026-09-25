# NOVA AI on AWS (Terraform)

The scale-out production layout from `docs/48_PRODUCTION_ARCHITECTURE.md`. The single-server
setup in `infra/deploy/` (Docker Compose + Caddy) is the simpler alternative.

```
WAF → ALB (HTTPS, 3 AZs, idle 350 s) → web (Next.js BFF, ECS Fargate)
                                        └─ Service Connect → api (FastAPI) ─┬─ RDS PostgreSQL 16 (Multi-AZ)
                                           worker (arq) ────────────────────┼─ ElastiCache Redis (TLS, replica)
                                                                            ├─ S3 files (versioned, encrypted)
                                                                            └─ internal NLB → sandbox runners
                                                                               (EC2, isolated subnets, gVisor)
```

| Module | What it creates |
|---|---|
| `network` | VPC, public/private/isolated subnets in 3 AZs, NAT, VPC endpoints for the isolated tier |
| `rds` | PostgreSQL 16, gp3, encrypted, TLS-only, 14-day PITR, deletion protection |
| `redis` | Redis 7 replication group, TLS + AUTH token, automatic failover |
| `s3` | Private bucket, versioning, SSE, TLS-only policy, CORS for presigned uploads |
| `ecs_service` | Fargate task + service, IAM roles, logs, CPU autoscaling, Service Connect |
| `sandbox_asg` | Runner hosts (no internet), internal NLB, IMDSv2 hop limit 1 |
| `observability` | SNS alerts + CloudWatch alarms (5xx, latency, CPU, storage, Redis memory, runners) |

Secrets (database/Redis URLs, auth secrets, SMTP, Sentry and, in server key mode, the
Groq key) live in one Secrets Manager secret and are injected into containers; they never reach
browsers, images or logs. Groq is the only LLM provider and is called only by api/worker.

## Use

```sh
cd envs/production
cp backend.hcl.example backend.hcl            # S3 state bucket + DynamoDB lock table
cp terraform.tfvars.example terraform.tfvars  # domain, ACM cert, ECR registry, image tag, bucket
terraform init -backend-config=backend.hcl
terraform plan -out plan && terraform apply plan
```

Deploys: push images tagged with the git SHA to ECR, run the `migrate` task once
(`aws ecs run-task --cluster nova-production --task-definition migrate --launch-type FARGATE
--network-configuration ...` using the `private_subnet_ids` / `migrate_security_group_id`
outputs), then `terraform apply -var image_tag=<sha>` (ECS rolls with circuit-breaker rollback).
Point the domain at the `alb_dns_name` output.

Before first apply: build a sandbox AMI with gVisor (`runsc`) installed and set
`sandbox_ami_id`; the isolated subnets have no internet to download it at boot.

Validate locally without AWS credentials: `make tf-validate`.
