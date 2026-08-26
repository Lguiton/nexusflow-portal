# Eivanta Terraform Skeleton -- Unapplied

**Status: written, never run.** No `terraform init`, `plan`, or `apply` has
happened against this -- I have no Vercel or Render credentials, and even
if I did, standing up real infrastructure is explicitly your call, not
something to do quietly while closing a Phase 6 checklist item. This
exists so the shape of the config is ready when you decide to go, not as
a claim that anything below has been validated against a live account.

## What this covers

- `vercel_project` (frontend) -- via the official `vercel/vercel` provider.
- `render_web_service` (backend) -- via Render's official
  `render-oss/render` provider (their own changelog calls it "early
  access" as of this writing -- worth checking its current maturity
  before relying on it for anything real).

Both resource shapes below were checked against each provider's actual
current docs (not guessed), but neither has been run through a real
`terraform plan`, so there could still be a drift between what the docs
say and what a real account's API actually accepts -- treat the first
`terraform plan` you run as the real verification step, not this file.

## Why these two providers specifically

The SaaS Lifecycle Executive Manual named Vercel (frontend) alongside
Render/Railway/AWS ECS (backend, pick one) without committing to a single
backend target. I picked Render here only because it's the one with an
official Terraform provider today -- Railway and AWS ECS are both
reasonable alternatives and this isn't meant to foreclose them. Say the
word and I'll swap this skeleton to target either instead.

## Before this does anything real

1. `terraform init` (downloads the two providers -- needs network access
   neither of my sandboxes has).
2. Create real API tokens (Vercel: Account Settings -> Tokens. Render:
   Account Settings -> API Keys) and get your Render owner ID (`rnd_...`,
   visible in the Render dashboard URL or via their API).
3. Supply `vercel_api_token`, `render_api_key`, and `render_owner_id` via
   a `terraform.tfvars` file (gitignored -- do not commit real tokens) or
   `TF_VAR_*` environment variables. Never paste real tokens into chat
   with me either.
4. `terraform plan` and actually read the output before ever running
   `terraform apply`.

## What's deliberately not here

- Remote state backend (S3/Terraform Cloud/etc.) -- state would default
  to a local `terraform.tfstate` file, which is fine for a first
  `plan`-only pass but not for anything real; add one before a real
  `apply`, since local state with real infrastructure in it is easy to
  lose or diverge from what's actually deployed.
- DNS/domain + SSL provisioning -- Phase 6's "Domain & SSL" gap is still
  fully open; this skeleton doesn't touch it because no domain registrar
  or DNS provider has been chosen yet.
- Qdrant hosting -- `docker-compose.yml` runs it as a container alongside
  the app for local use; a managed Qdrant Cloud instance (or continuing
  to self-host it next to the backend) is a separate decision this
  skeleton doesn't make for you.
