# Architecture Pattern Collection

Rather than building a YAML from scratch to fit a requirement, starting from one of these nearby patterns and editing the difference produces a more stable diagram with no structural breakage. Start by picking the pattern closest to the requirement on this page, load its YAML, then add/remove nodes and change labels to match. Every pattern has been confirmed with `zook validate` to produce zero warnings.

If the requirement changes but the type (the compute execution model) doesn't need to, you only need to swap labels or counts within the pattern. If the type itself doesn't fit the requirement (e.g. picking an EC2-based pattern when the requirement says "no server management"), switch to a different pattern instead.

## `3tier-web-app.yaml` — the classic 3-tier web app

Multiple EC2 web servers across AZs behind an ALB, with an RDS in each AZ for redundancy. Reach for this first for "I want to build a new web app" or "no special requirements, just go with a proven setup." This assumes you'll manage server start/stop and OS patching yourself, so if reducing operational load matters, `serverless-api.yaml` or `container-platform.yaml` below fit better.

## `serverless-api.yaml` — an API with no server management wanted

API Gateway receives HTTPS requests, Lambda processes them, and DynamoDB persists the data. Auth is via Cognito. Fits requirements like "no server management," "irregular/low-frequency traffic," or "start small and grow." The first choice when always-on containers or VMs aren't wanted.

## `event-driven-processing.yaml` — asynchronous, loosely-coupled processing

EventBridge detects an upload to S3, SQS buffers it, and Lambda processes it. Completion is announced via SNS. Choose this for requirements like "no synchronous response needed," "downstream backpressure shouldn't block ingestion," or "the same event needs to reach multiple consumers." Not a fit when a result must be returned immediately after the request.

## `container-platform.yaml` — a platform that keeps running as containers

ECS (Fargate) behind an ALB runs the application, persisting to Aurora and caching sessions in ElastiCache. Fits "we already have a Docker image" or "want less server management, but still want to run as a container unit." Choose this over fine-grained per-function billing when you want an always-running service.

## `static-site-cdn.yaml` — serving a static site / SPA

Route53 resolves the domain, and CloudFront serves static files from S3. Fits "no backend processing, or it's a separately-deployed API" and "serving a static site or SPA." Combine with `serverless-api.yaml` if dynamic server-side processing is also required.

## `gcp-serverless-api.yaml` — GCP version of the serverless API

The GCP counterpart of `serverless-api.yaml`. API Gateway receives HTTPS requests, Cloud Functions processes them, and Firestore persists the data. Auth is via Identity Platform. Choose this when GCP is explicitly required.

## `azure-container-app.yaml` — Azure version of the container platform

The Azure counterpart of `container-platform.yaml`. Front Door receives HTTPS, Container Apps runs the app, and Cosmos DB persists the data. Auth is via Entra ID. Choose this when Azure is explicitly required.

## Choosing a Pattern

First read off two things from the requirements:

1. **Is a cloud provider specified?** If not stated, start from the AWS version; if GCP/Azure is specified, use the corresponding GCP/Azure version (currently only `serverless-api.yaml`/`container-platform.yaml` have GCP/Azure counterparts).
2. **Is there a preference for the compute execution model?** If server management should be avoided, use `serverless-api.yaml`; if it's container-based on an existing Docker image, use `container-platform.yaml`; with no special requirement, use `3tier-web-app.yaml`; if asynchronous/event-driven is explicit, use `event-driven-processing.yaml`; if the delivery target is static content only, use `static-site-cdn.yaml`.

For requirements that don't fit any single pattern, either combine multiple patterns (e.g. static-site delivery + a serverless API) or build a new one from scratch while referring to `docs/yaml-spec.md` and `zook icons list`. Usable service names are limited to the Tier-1 vocabulary (26 AWS / 19 GCP / 18 Azure services) documented in `docs/icon-registry-and-vocabulary.md`, so if the requirement calls for something outside that set, either substitute the closest available service or check with the user.
