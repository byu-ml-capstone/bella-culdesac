terraform {
  required_version = ">= 1.5"
  required_providers {
    coolify = {
      source  = "bindtech-xyz/coolify"
      version = "~> 0.1.0"
    }
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
  }
}

provider "coolify" {
  endpoint = var.coolify_endpoint
  token    = var.coolify_token
}

provider "github" {
  token = var.github_token
  owner = var.github_org
}

# ---------------------------------------------------------------------------
# What this lab creates (mirrors Setup Steps 4-9 of the student guide)
# ---------------------------------------------------------------------------
# One `terraform apply` builds the entire Coolify + GitHub wiring:
#
#   - Coolify Project                          (Step 4)
#   - Coolify staging Environment              (Step 4; production auto-created)
#   - Coolify Application: staging             (Step 5)
#   - Coolify Application: production          (Step 6)
#   - COOLIFY_API_TOKEN GitHub secret          (Step 8)
#   - COOLIFY_DEPLOY_WEBHOOK_STAGING secret    (Step 7)
#   - COOLIFY_DEPLOY_WEBHOOK_PROD secret       (Step 9)
#
# Deploy webhook URLs are deterministic from each Application's UUID
# (`<endpoint>/deploy?uuid=<app_uuid>`), so no post-apply UI copy-paste for
# those. The one manual step remaining is pasting the pretty domain into
# Coolify UI per Application (see the "Pretty domains" block at the bottom
# of this file for why).
#
# Requires the class Coolify instance to be running the local patch for
# coollabsio/coolify#11449 — without it, the coolify_application resources
# fail with `HTTP 404: Github App not found` on team-scoped tokens.
# Upstream PR #11451 was closed without merge; the patch is our long-term
# fix for the v4.x Coolify lifetime. See coolify-runbook.md §16
# "Post-install patches" for reapplying after Coolify updates.
# ---------------------------------------------------------------------------

resource "coolify_project" "app" {
  name        = var.repo_name
  description = "Provisioned by Terraform - hello-world-app lab"
}

resource "coolify_environment" "staging" {
  project_uuid = coolify_project.app.uuid
  name         = "staging"
}

# The `production` Environment is auto-created by Coolify when the Project
# is born, so we don't declare it as a resource — the production Application
# below references it by name.

# ---------------------------------------------------------------------------
# Applications (staging + production)
# ---------------------------------------------------------------------------
# Two Applications backed by the same repo, wired to different branches:
# staging → `staging` branch, production → `main`. Both are dockercompose
# build packs pointing at the repo's docker-compose.yaml.
#
# ports_exposes = "80": Coolify silently forces this value server-side for
# dockercompose apps (the field is Coolify's proxy ingress port, not a
# container port). Sending anything else causes the bindtech-xyz provider
# to error with "provider produced inconsistent result" on state read-back.
# Actual container-to-container routing is picked from docker-compose.yaml
# directly by Coolify + Traefik.
#
# is_auto_deploy_enabled = false: Coolify's own GitHub-push auto-deploy
# stays off. The CI workflow (.github/workflows/ci.yml) explicitly POSTs
# each Application's deploy webhook after tests pass, which is the single
# source of "when to deploy". Enabling both paths would double-fire on
# every push.
# ---------------------------------------------------------------------------

resource "coolify_application" "staging" {
  project_uuid     = coolify_project.app.uuid
  environment_uuid = coolify_environment.staging.uuid
  server_uuid      = var.coolify_server_uuid
  github_app_uuid  = var.coolify_github_app_uuid
  git_repository   = "${var.github_org}/${var.repo_name}"
  git_branch       = "staging"
  build_pack       = "dockercompose"
  ports_exposes    = "80"

  is_auto_deploy_enabled = false
}

resource "coolify_application" "production" {
  project_uuid     = coolify_project.app.uuid
  environment_name = "production"
  server_uuid      = var.coolify_server_uuid
  github_app_uuid  = var.coolify_github_app_uuid
  git_repository   = "${var.github_org}/${var.repo_name}"
  git_branch       = "main"
  build_pack       = "dockercompose"
  ports_exposes    = "80"

  is_auto_deploy_enabled = false
}

# ---------------------------------------------------------------------------
# GitHub Actions secrets (consumed by .github/workflows/ci.yml)
# ---------------------------------------------------------------------------
# COOLIFY_API_TOKEN is reused by both staging + production deploy jobs.
# COOLIFY_DEPLOY_WEBHOOK_{STAGING,PROD} are Coolify deploy trigger URLs,
# deterministic from each Application's UUID
# (`<coolify-endpoint>/deploy?uuid=<application_uuid>`) — no need to
# copy them out of Coolify UI post-apply.
# ---------------------------------------------------------------------------

locals {
  # Pretty per-environment URLs — used in outputs and would be used as the
  # `domains` on each Application if the bindtech-xyz provider supported
  # per-service `docker_compose_domains` (see "Pretty domains" block below).
  compose_service_name  = "hello"
  staging_pretty_domain = "http://${var.repo_name}-staging.${var.app_domain_base}"
  prod_pretty_domain    = "http://${var.repo_name}.${var.app_domain_base}"

  # Deploy webhook URLs (POSTed by CI to trigger a Coolify deploy after
  # tests pass). coolify_endpoint already ends with /api/v1, so append
  # /deploy?uuid=... directly.
  webhook_staging = "${var.coolify_endpoint}/deploy?uuid=${coolify_application.staging.uuid}"
  webhook_prod    = "${var.coolify_endpoint}/deploy?uuid=${coolify_application.production.uuid}"
}

resource "github_actions_secret" "coolify_api_token" {
  repository  = var.repo_name
  secret_name = "COOLIFY_API_TOKEN"
  value       = var.coolify_token
}

resource "github_actions_secret" "deploy_webhook_staging" {
  repository  = var.repo_name
  secret_name = "COOLIFY_DEPLOY_WEBHOOK_STAGING"
  value       = local.webhook_staging
}

resource "github_actions_secret" "deploy_webhook_prod" {
  repository  = var.repo_name
  secret_name = "COOLIFY_DEPLOY_WEBHOOK_PROD"
  value       = local.webhook_prod
}

# ---------------------------------------------------------------------------
# Pretty domains — one manual UI click per Application (see outputs.tf)
# ---------------------------------------------------------------------------
# Setting per-service domains on dockercompose Applications isn't something
# terraform can do end-to-end today. Three-deep chain of provider/API
# limitations, all rooted in the coolify provider being immature:
#
#   1. bindtech-xyz/coolify exposes only a flat `domains` field.
#   2. Coolify's API rejects that field for build_pack=dockercompose —
#      must use per-service `docker_compose_domains` instead.
#   3. `docker_compose_domains` requires `docker_compose_raw` to be
#      pre-populated. Coolify's UPDATE endpoint doesn't allow that field,
#      and the provider doesn't expose it at CREATE time. Only paths to
#      populating it are Coolify's first deploy (async) or the UI's
#      "Load Compose File" button (a Livewire action, not a public API).
#
# Nets out to a single UI click per Application. `next_steps` output tells
# the student exactly what to paste. Revisit when either the bindtech-xyz
# provider adds the missing fields, or Coolify v5 ships stable and its
# rewritten API handles per-service domains cleanly.
# ---------------------------------------------------------------------------
