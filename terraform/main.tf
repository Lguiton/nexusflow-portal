# See terraform/README.md -- unapplied skeleton, written but never run
# against a real account. Resource shapes below were checked against each
# provider's current docs at the time of writing, not against a real
# `terraform plan`.

terraform {
  required_providers {
    vercel = {
      source  = "vercel/vercel"
      version = "~> 3.1"
    }
    render = {
      source  = "render-oss/render"
      version = "~> 1.0"
    }
  }
}

provider "vercel" {
  api_token = var.vercel_api_token
  team      = var.vercel_team_id
}

provider "render" {
  api_key = var.render_api_key
}

resource "vercel_project" "frontend" {
  name      = "eivanta-portal"
  framework = "nextjs"

  git_repository = {
    type = "github"
    repo = var.github_repo
  }

  # The Next.js app lives in frontend/, not the repo root -- this is a
  # commonly-available setting on Vercel projects (dashboard calls it
  # "Root Directory") for exactly this monorepo layout. Not explicitly
  # confirmed in the provider doc excerpt I was able to fetch, though --
  # verify this attribute name survives `terraform plan` before applying;
  # if it doesn't, set the root directory once by hand in the Vercel
  # dashboard instead and drop this line.
  root_directory = "frontend"

  environment = [
    {
      key    = "NEXT_PUBLIC_BACKEND_URL"
      value  = render_web_service.backend.url
      target = ["production", "preview"]
      # The provider docs I fetched say production/preview-targeted inline
      # environment entries must set sensitive = true under some team
      # policies -- set true here to avoid a plan-time rejection, even
      # though NEXT_PUBLIC_* values are meant to be public (they end up
      # in the client bundle regardless of this setting). If your Vercel
      # team's policy doesn't require it, false is the more honest value
      # for a genuinely non-secret URL -- worth revisiting once you can
      # actually run `terraform plan` against it.
      sensitive = true
    },
  ]
}

resource "render_web_service" "backend" {
  name     = "eivanta-backend"
  # owner_id scopes this service to the right Render workspace when an API
  # key has access to more than one -- the exact attribute name wasn't
  # confirmed in the doc excerpt I fetched (only name/plan/region/
  # runtime_source were), so double check this survives `terraform plan`
  # before applying; Render's dashboard is the fallback if it doesn't.
  owner_id = var.render_owner_id
  plan     = "starter"
  region   = "oregon"

  runtime_source = {
    docker = {
      repo_url        = "https://github.com/${var.github_repo}"
      branch          = "main"
      dockerfile_path = "./backend/Dockerfile"
      context         = "./backend"
      auto_deploy     = false # deliberately off -- flip once you trust this config; see README
    }
  }

  env_vars = {
    JWT_SECRET     = { value = var.backend_jwt_secret }
    OPENAI_API_KEY = { value = var.backend_openai_api_key }
    QDRANT_URL     = { value = var.backend_qdrant_url } # points at wherever Qdrant actually ends up hosted -- open per README
  }
}

output "vercel_project_url" {
  value = "https://${vercel_project.frontend.name}.vercel.app"
}

output "render_backend_url" {
  value = render_web_service.backend.url
}
