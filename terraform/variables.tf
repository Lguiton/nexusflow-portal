# See terraform/README.md before touching anything here -- this whole
# directory is an unapplied skeleton, not a live config.

variable "vercel_api_token" {
  description = "Vercel API token (Account Settings -> Tokens). Never commit a real value -- pass via terraform.tfvars (gitignored) or TF_VAR_vercel_api_token."
  type        = string
  sensitive   = true
}

variable "vercel_team_id" {
  description = "Optional: Vercel team ID, only needed if this project should live under a team rather than your personal account."
  type        = string
  default     = null
}

variable "render_api_key" {
  description = "Render API key (Account Settings -> API Keys). Never commit a real value -- pass via terraform.tfvars (gitignored) or TF_VAR_render_api_key."
  type        = string
  sensitive   = true
}

variable "render_owner_id" {
  description = "Render owner ID (rnd_...) that the backend service should be created under."
  type        = string
}

variable "github_repo" {
  description = "owner/repo slug on GitHub that both the Vercel project and Render service should deploy from."
  type        = string
  default     = "LGuiton/eivanta-portal"
}

variable "backend_jwt_secret" {
  description = "Real production JWT_SECRET for the deployed backend. Deliberately has no default -- `terraform apply` fails loudly if you forget to supply it, rather than silently deploying with an empty/weak secret. Pass via TF_VAR_backend_jwt_secret or a gitignored terraform.tfvars, never a literal in a committed .tf file."
  type        = string
  sensitive   = true
}

variable "backend_openai_api_key" {
  description = "Real production OpenAI API key for the deployed backend. Same handling as backend_jwt_secret above."
  type        = string
  sensitive   = true
}

variable "backend_qdrant_url" {
  description = "URL of wherever Qdrant ends up hosted for production -- a separate open decision (managed Qdrant Cloud vs. continuing to self-host it next to the backend), see README."
  type        = string
  default     = ""
}
