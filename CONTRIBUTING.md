# Contributing

Open an issue for a bug or proposal, then send a focused pull request with
the expected behavior and relevant test results. Keep each change small
enough to review. Include a clear explanation and tests for the behavior
your change introduces.

Use synthetic accounts, cookies and media in tests. Never include personal
data, live API keys, session files or network captures. Run the checks listed
in README before submitting. Do not use real TikTok accounts in CI.

Media processing and uniquification live in `modules/uniq.py` and
`web/src/features/uniq/`. UI text belongs in the translation catalog.
Use existing Base UI components and semantic theme tokens.

The Nimbus service is separate. Client changes must run from a clean clone
without private service modules. Keep API contracts backward compatible
and provide a clear failure when a service capability is unavailable.
