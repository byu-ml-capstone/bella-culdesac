# Bonus: IaC for the Coolify + GitHub wiring

**Prerequisite: finish Setup Steps 1–11 of the student guide by hand at least once.** This bonus lab teaches nothing about *what* Coolify is — you already know that. It teaches **Infrastructure as Code** by re-doing Setup Steps 4–9 as declarative HCL. When you're done, one `terraform apply` recreates the entire Coolify + GitHub wiring for a bare-fresh repo, no clicks required.

## What Terraform creates

Everything in Setup Steps 4–9, in a single apply:

- **Coolify Project** named after your repo (Step 4)
- **`staging` Environment** — the `production` environment is auto-created when the Project is born
- **`staging` Application** wired to your repo's `staging` branch, `dockercompose` build pack, port 8000, auto-deploy off (Step 5)
- **`production` Application** wired to your repo's `main` branch, ditto config (Step 6)
- **`COOLIFY_API_TOKEN` GitHub Actions secret** — shared by both deploy jobs (Step 8)
- **`COOLIFY_DEPLOY_WEBHOOK_STAGING` secret** — URL is `<coolify-endpoint>/deploy?uuid=<staging_app_uuid>`, constructed in HCL from the Application UUID (Step 7)
- **`COOLIFY_DEPLOY_WEBHOOK_PROD` secret** — same shape, prod Application (Step 9)

Push to `staging` → CI runs tests, POSTs the staging webhook, staging deploys. Merge to `main` → CI runs tests, POSTs the prod webhook, prod deploys.

**One thing terraform can't fully automate: pretty domains.** After `terraform apply` succeeds, you'll paste the class-wildcard URL into Coolify's UI (one text field, one Save click, per Application — the `next_steps` output tells you exactly what to paste and where). Without that step, your app serves at a Coolify-auto-generated `<uuid>.128.187.112.8.sslip.io` URL, which is functional but ugly. **Saving the domain is not enough on its own — redeploy afterwards.** Traefik routes on labels baked into the running container, so a container started before you set the domain keeps the old routing rule and your new URL returns `404 page not found`. Hit Redeploy in Coolify (or push again) and it starts working. Why the workaround: (1) the `bindtech-xyz/coolify` provider only exposes a flat `domains` field, (2) Coolify's API rejects that field on dockercompose apps (needs per-service `docker_compose_domains` instead), (3) `docker_compose_domains` requires `docker_compose_raw` to be pre-populated, which Coolify's UPDATE endpoint doesn't accept and the coolify provider doesn't expose at CREATE time. That's a three-deep chain of provider/API limitations — worth fixing upstream but not by adding polling scaffolding to a bonus lab.

**Multi-provider setup.** This lab uses two providers, each doing what it's best at:

- **`bindtech-xyz/coolify`** — Coolify Project, Environment, Applications.
- **`integrations/github`** — GitHub Actions secrets on your student repo.

## Requires a locally-patched Coolify instance

The `coolify_application` resources call `POST /api/v1/applications/private-github-app` with your student team-scoped token. Stock Coolify (as of v4.3.7) has a bug: the endpoint returns `HTTP 404: Github App not found` for GitHub Apps flagged `is_system_wide` — exactly how the class `byu-ml-capstone-coolify` App is registered.

The class Coolify instance runs a local patch that fixes this. If `terraform apply` fails on the Application resources with the 404, the patch got wiped (Coolify auto-updated, or the container was recreated). Reapply from rigel:

```bash
./scripts/repatch-coolify.sh --apply
```

Upstream tracking: [coollabsio/coolify#11449](https://github.com/coollabsio/coolify/issues/11449) (bug), [PR #11451](https://github.com/coollabsio/coolify/pull/11451) (fix — **closed without merge** on 2026-08-21; the fix is expected to land in Coolify v5's API rewrite, no v4.x release will carry it). Until v5 ships stable and rigel migrates, the local patch is the answer. When that happens, retest against v5, and if the bug is gone, delete the patch script (`scripts/repatch-coolify.sh`) and this whole section.

Forking to a different Coolify instance? You'll hit the same 404 unless that instance is also patched.

## Prerequisites

1. **Terraform** (or OpenTofu — same commands):
   ```bash
   brew tap hashicorp/tap
   brew install hashicorp/tap/terraform
   ```
2. **A Coolify API token.** ml-capstone-admin.cs.byu.edu → top-left dashboard menu → **Keys & Tokens → API Tokens → + New Token**. Description = whatever; **Permissions = `root`** — the boxes are mutually exclusive, so `write` and `deploy` cannot both be selected, and Terraform needs both. `root` here is root of your own team only. Click **Create Token**, then copy it immediately (Coolify shows it once).
3. **A GitHub Personal Access Token** with `repo` scope. Easiest: `gh auth token`. Otherwise Settings → Developer settings → Personal access tokens → Tokens (classic) → new one with `repo` scope. Full walkthrough is in `terraform.tfvars.example`.
4. **Your GitHub repo already exists** under `byu-ml-capstone` from templating `hello-world-app` (Setup Step 1).

## Usage

```bash
# 1. Copy the tfvars template + fill in your secrets
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars

# 2. Init (downloads the coolify + github providers)
terraform init

# 3. Plan (dry-run — shows what will be created)
terraform plan

# 4. Apply
terraform apply
```

Seven resources get created (Project + Environment + two Applications + three GitHub secrets). Then follow the `next_steps` output — it tells you which branches to push to trigger each deploy.

## Files

- `main.tf` — providers + Project + Environment + Applications + three secrets
- `variables.tf` — inputs + class-default overrides (server UUID, GitHub App UUID)
- `outputs.tf` — UUIDs, URLs, next-steps message
- `terraform.tfvars.example` — copy-to-tfvars template with detailed comments
- `.gitignore` — blocks `terraform.tfvars`, `.terraform/`, `*.tfstate`

## Cleanup

```bash
terraform destroy
```

Removes the Project (cascades to its Environments and Applications) and all three GitHub secrets. Full teardown.

## The point

You're seeing the shape of declarative infrastructure end-to-end — inputs in tfvars, a plan preview, apply, state file, drift detection, `destroy` reverses everything. That mental shift — "click here, then here, then copy this URL to that other UI" → "declare this shape, let the tool make it happen" — is IaC in one sitting. It generalizes: Terraform for AWS, Kubernetes YAML, Nix, Pulumi, all the same shape.

The two caveats are also the point:

- **This lab depends on a patched Coolify.** That's exactly the kind of real-world "waiting on an upstream fix while running a local patch" situation you hit constantly in production infra work. The dependency is named, the patch is scripted (`scripts/repatch-coolify.sh` on rigel), the upstream ticket and PR are linked, the exit criteria is written down. That whole shape — "we know it's here, we know how to remove it, we know when" — is what managing this class of technical debt looks like.
- **The pretty-domain step is manual.** The bindtech-xyz/coolify provider doesn't model dockercompose per-service domains yet. We tried three ways around it (a `terraform_data` provisioner, a `magodo/restful` operation, a two-step PATCH with `docker_compose_raw`), each hit a different provider or API limitation, and each workaround was more scaffolding than a UI click would ever be. Sometimes IaC's honest answer is "here's the 90% that automates cleanly, plus one documented manual step" instead of a fragile automation that fights the tools.
