# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Sentigent, please report it using GitHub's private vulnerability reporting feature. **Do not open a public issue or discussion.**

1. Go to the [Security Advisories](https://github.com/hussi9/sentigent/security/advisories) tab
2. Click "Report a vulnerability"
3. Provide a detailed description, including:
   - How the vulnerability can be exploited
   - What impact it has
   - Steps to reproduce (if applicable)

We will acknowledge your report within 48 hours and work with you to coordinate a fix and public disclosure timeline.

## Security Principles

### Local-First Design

Sentigent is designed with **local-first** principles:

- **No telemetry** — We do not collect usage data, logs, or operational information from your system
- **Data stays on-machine** — All judgment computation, memory, and learning happens locally
- **No external dependencies** — Your operational data is never sent to remote servers (except your chosen LLM provider API for inference)
- **No tracking** — No analytics, no user tracking, no implicit data collection

This means you can safely run Sentigent on sensitive operational data without worrying about data exfiltration.

### What We Assume About Your Environment

Sentigent assumes:

- Your LLM provider (OpenAI, Claude, local models) is trusted with your prompts and inference data
- Your local environment (`~/.sentigent/`, database files, logs) is secured against unauthorized access
- You review and approve all domain profiles and signal definitions before deployment

### What You Should Know

- Sentigent runs entirely in Python; it does not execute arbitrary code
- All external API calls (to LLM providers) are logged and auditable
- If you use the Layer 2 Supabase integration, your data is sent to Supabase servers; review their security policy before enabling
- Dashboard server binds to `localhost` by default; do not expose it to the network without HTTPS and authentication

## Scope

Security vulnerabilities in Sentigent itself include:

- Code execution vulnerabilities (e.g., injection, deserialization)
- Memory safety issues
- Unexpected data leaks from local storage
- Authentication/authorization bypass in the dashboard
- Dependency vulnerabilities that affect the core library

**Out of scope:**
- Issues in your LLM provider's security
- Misconfigurations of your local environment
- Issues in third-party integrations (LangGraph, CrewAI) unless they are Sentigent's fault

## Supported Versions

Security updates are released for the latest version. We recommend staying up to date:

```bash
pip install --upgrade sentigent
```

Check your current version:

```bash
sentigent --version
```

## Security Checklist for Deployment

Before running Sentigent in production:

- [ ] Review all domain profiles in `sentigent/profiles/`
- [ ] Restrict access to `~/.sentigent/` to authorized users only
- [ ] If using Layer 2, ensure Supabase credentials are secret and rotated regularly
- [ ] Test the judgment loop on sample data before running live
- [ ] Monitor logs for unexpected API calls or errors
- [ ] Keep Sentigent and dependencies up to date

## Additional Resources

- [Dependency scanning](https://github.com/hussi9/sentigent/security/dependabot) via Dependabot
- [GitHub Security Advisories](https://github.com/hussi9/sentigent/security/advisories) for published vulnerabilities

Thank you for helping keep Sentigent secure.
