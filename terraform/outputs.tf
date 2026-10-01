output "project_uuid" {
  description = "Coolify Project UUID — match against the URL bar in Coolify UI to jump to your Project."
  value       = coolify_project.app.uuid
}

output "staging_env_uuid" {
  description = "Coolify staging Environment UUID."
  value       = coolify_environment.staging.uuid
}

output "staging_app_uuid" {
  description = "Coolify staging Application UUID."
  value       = coolify_application.staging.uuid
}

output "production_app_uuid" {
  description = "Coolify production Application UUID."
  value       = coolify_application.production.uuid
}

output "staging_url" {
  description = "URL where staging serves AFTER you paste it into Coolify UI (see next_steps). Coolify's auto-generated sslip.io URL is available via `terraform state show coolify_application.staging` under the `fqdn` field if you want to hit the app before setting the pretty domain."
  value       = local.staging_pretty_domain
}

output "prod_url" {
  description = "URL where production serves AFTER you paste it into Coolify UI (see next_steps). Same auto-sslip.io caveat as staging_url."
  value       = local.prod_pretty_domain
}

output "next_steps" {
  description = "What to do after `terraform apply` succeeds."
  value = <<-EOT

    Terraform created:
      Coolify Project:        ${var.repo_name}   (uuid=${coolify_project.app.uuid})
      Coolify Environments:   staging, production
      Coolify Applications:   staging  (uuid=${coolify_application.staging.uuid})
                              production (uuid=${coolify_application.production.uuid})
      GitHub Actions secrets: COOLIFY_API_TOKEN
                              COOLIFY_DEPLOY_WEBHOOK_STAGING
                              COOLIFY_DEPLOY_WEBHOOK_PROD

    ONE UI click remaining per Application, then you're done (see the
    "Pretty domains" note in this file's header for why terraform can't do
    this last step end-to-end today):

      Coolify UI -> your Project (${var.repo_name}) -> staging environment
        -> your Application -> Configuration -> Domains -> under service
        `${local.compose_service_name}`, paste:
          ${local.staging_pretty_domain}
        -> Save

      Repeat for the production Application, pasting:
          ${local.prod_pretty_domain}

    Then to deploy:

      1. `git push origin staging` — CI runs tests, then POSTs the staging
         webhook. Watch the deploy in Coolify UI, then hit:
           ${local.staging_pretty_domain}

      2. Open a PR from `staging` to `main`, merge — CI runs tests, then POSTs
         the production webhook. Watch the deploy in Coolify UI, then hit:
           ${local.prod_pretty_domain}

    Tear it down when you're done exploring:
      terraform destroy
  EOT
}
