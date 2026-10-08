# skylls webapp

The skylls website and dashboard, deployed on Vercel.

- **`/`** is the landing page: what skylls is, how to install it, and how it works.
- **`/dashboard`**: sign in with GitHub to see your skills, agents and swarms.
  - **Your items:** version, folder and summary, plus who can see each one.
    Share it with a GitHub user, or remove someone.
  - **Invitations** friends sent you: accept them.
  - **Open suggestions** on your items: accept or decline them, with a note.
  - **What friends shared with you**, each with its install command.

skylls has no database: everything lives in each user's GitHub. The dashboard
reads and changes it with the signed-in user's own GitHub access, using the
same logic as the CLI (`../skylls/kinds.py`).

## How it's built

- **No framework, no npm dependencies, no build step.** Static HTML pages, plus
  Vercel Functions in `api/`, each exporting `GET`/`POST(request)` and
  returning a `Response`.
- **Sign-in:** a GitHub OAuth app (`api/auth/*`). The GitHub token is kept in
  an **encrypted, HttpOnly cookie** (AES-256-GCM, `lib/session.js`). It never
  reaches the browser's JavaScript.
- **Changes** (share, unshare, accept, answer) need an `X-Skylls: 1` header,
  which protects against cross-site requests. Pages escape every value that
  comes from GitHub.

| file | what |
|---|---|
| `index.html`, `dashboard.html`, `privacy.html`, `terms.html` | the pages |
| `api/auth/login.js`, `callback.js`, `logout.js` | sign-in with GitHub |
| `api/me.js`, `items.js`, `access.js` | who you are; your and your friends' items + invitations; who can see an item |
| `api/share.js`, `unshare.js`, `invite.js`, `suggestion.js` | the actions |
| `api/marketplace.js` | GitHub Marketplace webhook (signature-checked, acknowledges events) |
| `lib/github.js` | GitHub API + the skylls catalog (same rules as the CLI) |
| `lib/session.js`, `lib/http.js` | encrypted session cookie, JSON helpers |
| `dev.js` | local server that routes like Vercel |
| `test/` | tests and a demo against a fake GitHub |

## Deploy on Vercel

1. **Create a GitHub OAuth app** at
   [github.com/settings/applications/new](https://github.com/settings/applications/new).
   You can also create it under your organization: Settings → Developer
   settings → OAuth Apps.
   - Homepage URL: `https://<your-domain>`
   - Authorization callback URL: `https://<your-domain>/api/auth/callback`
   - Then click "Generate a new client secret".

2. **Create the Vercel project** with **Root Directory = `webapp`**, either by
   importing `jcsancho/skylls` in the Vercel dashboard, or from this folder:
   ```bash
   cd webapp && vercel link
   ```

3. **Set three environment variables** for Production (and Preview, if you
   use it). Never commit them.
   ```bash
   vercel env add GITHUB_CLIENT_ID        # from the OAuth app
   vercel env add GITHUB_CLIENT_SECRET    # from the OAuth app
   vercel env add SESSION_SECRET          # any random string of 32+ characters: openssl rand -hex 32
   ```
   Optional: `APP_URL=https://<your-domain>`, if the public URL differs from
   the one requests arrive on.

4. **Optional: the GitHub Marketplace webhook.** Set
   `MARKETPLACE_WEBHOOK_SECRET` (`openssl rand -hex 32`). In the Marketplace
   listing, set the webhook URL `https://<your-domain>/api/marketplace` and enter
   the same secret. Until the secret is set, the endpoint answers 503.

5. **Deploy:**
   ```bash
   vercel --prod
   ```

GitHub asks users for the `repo` and `read:org` scopes. Those are needed to
read their **private** skylls repos and manage who they're shared with. The
dashboard only touches skylls repos (`skill-*`, `agent-*`, `swarm-*` with the
`skylls` topic, or `skylls-*`).

**Staying signed in.** Keep **"Expire user access tokens"** checked on the
OAuth app.
- **Sessions:** they last **30 days**. GitHub's access token expires every 8
  hours, and the dashboard renews it automatically with the refresh token, so
  users rarely sign in again while a stolen token stays short-lived.
- **Revoked access:** if someone revokes skylls on GitHub, the next renewal
  fails and they're asked to sign in again.
- **Signing out** clears the cookie.

## Run it locally

```bash
node test/demo.js        # sample data and a fake GitHub (sign-in works, no real account): http://localhost:3901
node --test test/        # the tests: sign-in, catalog, share/unshare, invitations, suggestions, CSRF
```

To use your real GitHub locally, create a second OAuth app with the callback
`http://localhost:3901/api/auth/callback`. Then set `GITHUB_CLIENT_ID`,
`GITHUB_CLIENT_SECRET` and `SESSION_SECRET` in your shell and run
`node dev.js`.
